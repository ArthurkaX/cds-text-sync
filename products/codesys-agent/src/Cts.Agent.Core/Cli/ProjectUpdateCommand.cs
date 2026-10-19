using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // Pull the team's branch and carry its view into the open project.
    public static class ProjectUpdateCommand
    {
        public static readonly CliCommand Command = new CliCommand
        {
            Name = "project",
            Sub = "update",
            Summary = "Pull the team's work into the open project",
            Description = "Pulls the branch and imports its changes. Refused while the PLC is online or when the IDE has unsynced edits. When the team changed the same lines, git stops the pull with the files it could not merge and nothing is imported: resolve them in your git program (cts open), commit the merge, then run cts project update again.",
            TimeoutKey = "sync_compare_text",
            Execute = Execute,
            Build = Build,
        };

        static IDictionary<string, object> Execute(CliCall call)
        {
            string folder;
            bool owner;
            string published = null;
            try
            {
                if (string.IsNullOrWhiteSpace(call.Hello.SyncFolder)) throw new InvalidOperationException("no sync folder: cts set-sync-folder chooses one");
                folder = GitRepository.Repository(call.Hello.SyncFolder);
                var status = call.Call("project.status", new Dictionary<string, object>(), 10);
                var plc = status.TryGetValue("plc", out var value) ? value as IDictionary<string, object> : null;
                if (Equals(plc != null && plc.TryGetValue("online", out var online) ? online : null, true))
                    throw new InvalidOperationException("The IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat `cts project update`.");
                owner = ProjectInfo.IsOwner(ProjectInfo.ProjectIdOf(folder));
                if (!owner)
                {
                    var lfs = GitRun.In(folder, "lfs version");
                    if (lfs.ExitCode != 0) throw new InvalidOperationException("the project file is published with Git LFS, which this git lacks: install it (git for Windows includes it), then run git lfs install");
                    published = GitRepository.Run(folder, "ls-files -z -- *.project").Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries).SingleOrDefault();
                    if (published == null) throw new InvalidOperationException("the repository has no published project file (*.project)");
                    if (GitRepository.Run(folder, "log -1 --format=%H HEAD -- " + ProcessArgs.Quote(published)).Trim().Length == 0)
                        throw new InvalidOperationException("the published project file has no commit: " + published);
                }
                if (HasMerge(folder)) throw Refused("git has a merge unfinished: " + UnfinishedMerge);
                var compare = ComparePlanner.Plan(call);
                CheckNoIdeChanges(compare);
                if (owner) RequireUpstream(folder);
            }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException)
            {
                throw Refused(error.Message);
            }

            var result = new Dictionary<string, object>();
            try
            {
                if (!owner)
                {
                    // The IDE's saves into the tracked file would stop the pull.
                    call.Call("project.close", new Dictionary<string, object> { { "discard", true } }, 60);
                    // git skips the file on a colleague's PC (TeamGuard): seen again, it can be put back.
                    TeamGuard.Skip(folder, published, false);
                    GitRepository.Run(folder, "checkout HEAD -- " + ProcessArgs.Quote(published));
                }
                IDictionary<string, object> pulled = null;
                try { pulled = Pull(folder); }
                catch (InvalidOperationException error) when (!owner) { result["pull_error"] = error.Message; }
                if (!owner && pulled == null) result["pull_error"] = "the branch has no upstream to pull from";
                else if (pulled != null) result["pulled"] = pulled;
                if (!owner)
                {
                    PutPublished(folder, published, call.Hello.ProjectPath);
                    var latest = GitRepository.Run(folder, "log -1 --format=%H HEAD -- " + ProcessArgs.Quote(published)).Trim();
                    var view = ViewFolder.Of(folder);
                    SyncBase.RecordFromCommit(folder, ExportCommand.Relative(folder, view), latest);
                    call.Call("project.open", new Dictionary<string, object> { { "path", call.Hello.ProjectPath } }, 180);
                    result["published"] = latest;
                    result["project_file"] = published;
                }
            }
            catch (CliFailure) { throw; }
            catch (Exception error) when (error is InvalidOperationException || error is ArgumentException || error is AgentException || error is IOException)
            {
                if (!owner) throw Refused(error.Message + "; the project is closed: cts project open --path " + call.Hello.ProjectPath + " opens it again");
                throw Refused(error.Message);
            }
            finally { if (!owner) TeamGuard.Skip(folder, published, true); }
            TeamGuard.Apply(folder, owner, TeamGuard.Exe);
            call.Options.Params["save"] = true;
            try
            {
                var imported = ImportCommand.Run(call, false);
                foreach (var pair in imported) result[pair.Key] = pair.Value;
            }
            catch (CliFailure error)
            {
                throw Refused((owner ? "" : "the IDE has the published project, but ") + "cts import cannot carry the branch into the IDE: " + error.Message);
            }
            result["to"] = GitRepository.Position(folder);
            return result;
        }

        internal static IDictionary<string, object> Pull(string folder)
        {
            if (!HasUpstream(folder)) return null;
            var before = Convert.ToString(GitRepository.Position(folder)["commit"]);
            var pull = GitRun.In(folder, "pull --no-rebase");
            if (pull.ExitCode == 0) return new Dictionary<string, object> { { "from", before }, { "to", GitRepository.Position(folder)["commit"] } };
            var unmerged = GitRepository.Run(folder, "diff --name-only --diff-filter=U -z").Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries);
            if (unmerged.Length == 0) throw new InvalidOperationException("git pull did not go through, nothing was imported: " + pull.Message);
            throw new InvalidOperationException("git pull stopped at " + unmerged.Length + " file(s) both sides changed, nothing was imported: " + string.Join(", ", unmerged.Take(5)) + "; " + UnfinishedMerge);
        }

        static bool HasUpstream(string folder)
        {
            var upstream = GitRun.In(folder, "rev-parse --abbrev-ref --symbolic-full-name @{u}");
            return upstream.ExitCode == 0;
        }

        const string UnfinishedMerge = "resolve the files in your git program (cts open), commit the merge, then cts project update again";

        // The published project as the pull left it, in place of the file the
        // IDE opens; git lfs pull when a pointer stands in for it.
        static void PutPublished(string folder, string published, string openPath)
        {
            var tracked = Path.Combine(folder, published.Replace('/', Path.DirectorySeparatorChar));
            if (IsLfsPointer(tracked)) GitRepository.Run(folder, "lfs pull --include=" + ProcessArgs.Quote(published));
            if (IsLfsPointer(tracked)) throw new InvalidOperationException(published + " is a Git LFS pointer, not the project: git lfs pull fetches it");
            if (!ProjectFiles.SamePath(tracked, openPath)) File.Copy(tracked, openPath, true);
        }

        static bool IsLfsPointer(string path)
        {
            var head = new byte[LfsPointer.Length];
            using (var file = File.OpenRead(path))
            {
                var read = file.Read(head, 0, head.Length);
                return read == head.Length && System.Text.Encoding.ASCII.GetString(head) == LfsPointer;
            }
        }

        const string LfsPointer = "version https://git-lfs";

        static bool HasMerge(string folder)
        {
            var merge = GitRun.In(folder, "rev-parse -q --verify MERGE_HEAD");
            return merge.ExitCode == 0;
        }

        internal static void CheckNoIdeChanges(IDictionary<string, object> compare)
        {
            if (!Equals(compare.ContainsKey("base") ? compare["base"] : null, true)
                || !compare.TryGetValue("summary", out var value) || !(value is IDictionary<string, object> summary)) return;
            var changed = JsonMap.Int(summary, "ide_changed") + JsonMap.Int(summary, "both");
            if (changed > 0) throw new InvalidOperationException("the IDE changed " + changed + " object(s) since the last sync (cts compare names them): cts sync carries them to disk, then cts commit takes them into the branch");
        }

        internal static void RequireUpstream(string folder)
        {
            if (!HasUpstream(folder))
                throw Refused("the branch has no upstream to pull from: git branch --set-upstream-to=origin/<branch> names one");
        }

        static CliFailure Refused(string message) => new CliFailure("project-update", "refused", message, "cts project update --help", 1);

        static Answer Build(IDictionary<string, object> data)
        {
            var to = data["to"] as IDictionary<string, object>;
            var answer = new Answer().Add("published", Short(data, "published"));
            if (to != null) answer.Add("branch", to.ContainsKey("branch") ? to["branch"] : null).Add("commit", Short(to, "commit"));
            if (data.TryGetValue("pulled", out var value) && value is IDictionary<string, object> pulled)
                answer.Add("pulled", !Equals(pulled["from"], pulled["to"])).Add("up_to_date", Equals(pulled["from"], pulled["to"]));
            answer.Add("project_file", data.ContainsKey("project_file") ? data["project_file"] : null);
            if (data.TryGetValue("pull_error", out var pullError)) answer.Detail("git pull did not go through, the IDE has the branch as it was: " + pullError);
            var imported = ImportCommand.Build(data);
            foreach (var pair in imported.Pairs) answer.Add(pair.Key, pair.Value);
            foreach (var detail in imported.Details) answer.Detail(detail);
            return answer;
        }

        static object Short(IDictionary<string, object> data, string key) => data.TryGetValue(key, out var value) && value != null ? Convert.ToString(value).Substring(0, Math.Min(8, Convert.ToString(value).Length)) : null;
    }
}
