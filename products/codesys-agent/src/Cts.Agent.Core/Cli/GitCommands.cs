using System;
using System.Collections.Generic;
using System.Linq;

using Cts.Agent;

namespace Cts.Cli
{
    // Local, git-only commands. Supplying --sync-folder keeps agent discovery out of the path.
    public static class GitCommands
    {
        internal static readonly CliOption SyncFolder = CliOption.Text("--sync-folder", "sync_folder", "PATH", "The sync folder (default: the one the open project names, asked from the in-IDE agent)");

        public static readonly CliCommand Branch = new CliCommand
        {
            Name = "branch", Arguments = "[NAME]", ArgumentLimit = 1, ArgumentHelp = "The branch to create",
            Summary = "List the sync folder's branches, or create one and switch to it",
            Description = "Without a name: the branches of the sync folder's repository and the one checked out. With a name: create that branch at the current commit and check it out; the files and the IDE stay as they are, so the project needs nothing carried.",
            Options = new[] { SyncFolder },
            LocalExecute = (options, host, work) => Run("branch", options, host, work), Build = BranchLine,
        };
        public static readonly CliCommand Log = new CliCommand
        {
            Name = "log", Summary = "List the sync folder's commits, with their tags and the ones downloaded to a PLC",
            Description = "The latest commits of the branch checked out, newest first: the short id, date, subject, the branches and tags at each and \"downloaded\" on a commit a cts download put on a PLC (cts plc-crc names the one the PLC runs now). Any of them is a target for cts checkout.",
            Options = new[] { CliOption.Int("-n", "limit", "How many commits (default 20)"), CliOption.Int("--limit", "limit", "How many commits (default 20)"), CliOption.Switch("--all", "all", "Every branch and tag, not only the one checked out"), SyncFolder },
            LocalExecute = (options, host, work) => Run("log", options, host, work), Build = LogLine,
        };
        public static readonly CliCommand Push = new CliCommand
        {
            Name = "push", Summary = "Send the sync folder's branch to the team's repository (git push)",
            Description = "git push of the branch checked out: to its upstream, else, the first time, to the repository's only remote, which becomes its upstream (git push -u). The project file's Git LFS objects go first. Only what is committed goes (cts commit first): the team gets the folder's files; the project file only when its owner published it (cts commit --publish), and edits the IDE holds unsaved or uncommitted never. git refuses when the remote has commits the branch lacks: pull them first (cts project update). git asks no password on a terminal: its credential helper answers, or the push fails and says so.",
            Options = new[] { SyncFolder }, LocalExecute = (options, host, work) => Run("push", options, host, work), Build = PushLine,
        };

        static IDictionary<string, object> Run(string verb, CliOptions options, IAgentHost host, string work)
        {
            try
            {
                var folder = Folder(options, host, work);
                if (verb == "branch")
                {
                    var name = options.Arguments.FirstOrDefault();
                    if (!string.IsNullOrEmpty(name)) name = GitRepository.Create(folder, name);
                    var data = new Dictionary<string, object>(GitRepository.Position(folder)) { { "branches", GitRepository.Branches(folder) }, { "tags", GitRepository.Tags(folder) } };
                    if (!string.IsNullOrEmpty(name)) data["created"] = name;
                    return data;
                }
                if (verb == "log")
                {
                    var limit = options.Params.TryGetValue("limit", out var n) ? Convert.ToInt32(n) : 20;
                    return new Dictionary<string, object>(GitRepository.Position(folder)) { { "commits", GitRepository.History(folder, limit, options.Params.ContainsKey("all")) } };
                }
                return GitRepository.Push(folder);
            }
            catch (Exception e) when (e is InvalidOperationException || e is ArgumentException)
            {
                throw new CliFailure(verb, "refused", e.Message, "cts " + verb + " --help", 1);
            }
            catch (AgentException e)
            {
                throw new CliFailure(verb, "refused", e.Message, "cts " + verb + " --help", 1);
            }
        }

        // The sync folder's repository root: --sync-folder, else the one the open project names.
        internal static string Folder(CliOptions options, IAgentHost host, string work)
        {
            string folder;
            if (options.Params.TryGetValue("sync_folder", out var named)) folder = Convert.ToString(named);
            else
            {
                var picked = AgentChoice.Pick(host, "cts cannot find the sync folder", options.TargetPid(), options.ExpectProject, work);
                using (var connection = picked.Key)
                {
                    var status = connection.Call("project.status", new Dictionary<string, object>(), 10000) as IDictionary<string, object>;
                    folder = status != null && status.TryGetValue("sync_folder", out var sync) ? sync as string : null;
                }
                if (string.IsNullOrEmpty(folder)) throw new InvalidOperationException("no sync folder: cts set-sync-folder chooses one (or pass --sync-folder)");
            }
            return GitRepository.Repository(folder);
        }

        static Answer BranchLine(IDictionary<string, object> data)
        {
            var names = data["branches"] as IList<string> ?? new List<string>();
            var current = data["branch"] as string;
            var answer = new Answer().Add("branch", current ?? "detached").Add("branches", names.Count).Add("tags", (data["tags"] as IList<string>)?.Count ?? 0);
            if (data.TryGetValue("created", out var created)) answer.Add("created", created);
            foreach (var name in names) answer.Detail((name == current ? "* " : "  ") + name);
            return answer;
        }
        static Answer LogLine(IDictionary<string, object> data)
        {
            var commits = data["commits"] as IList<IDictionary<string, object>> ?? new List<IDictionary<string, object>>();
            var answer = new Answer().Add("branch", data["branch"] ?? "detached").Add("commit", Short(data["commit"])).Add("commits", commits.Count);
            foreach (var entry in commits)
            {
                var marks = new List<string>();
                if (Equals(entry["head"], true)) marks.Add("HEAD");
                marks.AddRange((IEnumerable<string>)entry["branches"]);
                marks.AddRange(((IEnumerable<string>)entry["tags"]).Select(tag => "tag: " + tag));
                var line = Short(entry["commit"]) + " " + entry["date"] + " " + entry["subject"];
                if (marks.Count > 0) line += " (" + string.Join(", ", marks) + ")";
                if (Equals(entry["downloaded"], true)) line += " downloaded";
                answer.Detail(line);
            }
            return answer.Whole();
        }
        static Answer PushLine(IDictionary<string, object> data) => new Answer().Add("branch", data["branch"]).Add("to", data["upstream"]).Add("commits", data["commits"]);
        static object Short(object value) { var text = Convert.ToString(value); return string.IsNullOrEmpty(text) ? null : text.Substring(0, Math.Min(8, text.Length)); }
    }
}
