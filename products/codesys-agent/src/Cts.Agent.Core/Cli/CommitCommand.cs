using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // `cts commit -m MESSAGE`: git commit of the sync folder's files on its
    // branch; a difference between the IDE and the disk is only a warning.
    public static class CommitCommand
    {
        static readonly IDictionary<string, string> CtsIdentity = new Dictionary<string, string>
        {
            { "GIT_AUTHOR_NAME", "cts" }, { "GIT_AUTHOR_EMAIL", "cts@localhost" },
            { "GIT_COMMITTER_NAME", "cts" }, { "GIT_COMMITTER_EMAIL", "cts@localhost" },
        };

        public static readonly CliCommand Command = new CliCommand
        {
            Name = "commit",
            Summary = "Commit the sync folder's files on its branch",
            Description = "Record the sync folder on its branch: git add -A and git commit with the message, of the files as they are on disk; the IDE is not read or written. Every change git does not ignore is committed, files cts does not manage included, but never a *.project: the project file in the repository is its owner's, published with --publish. The IDE's project is not saved (cts save does that). With --tag the commit (or HEAD, when there was nothing to commit) is tagged, so cts checkout can go back to it.\n\n"
                + "When the IDE and the disk differ (cts compare names how), the commit still goes and says so in a [WARN] line: cts export or cts sync first carries the IDE's edits into the files. Refused when no branch is checked out (cts branch NAME starts one) or the tag exists. The user's git identity is used, cts' own when git has none; hooks run.\n\n"
                + "--publish (the project's owner only: the machine that gave it its id, or cts set-sync-folder --owner) also saves the project and commits its file under Git LFS, the base a colleague opens before cts import: the file the repository tracks, else the open one when it lies in the repository, else <name>.project at its root (published=PATH on the line).",
            TimeoutKey = "sync_compare_text",
            Options = new[]
            {
                CliOption.Text("-m", "message", "MESSAGE", "The commit message"),
                CliOption.Text("--message", "message", "MESSAGE", "The commit message"),
                CliOption.Text("--tag", "tag", "NAME", "Tag the commit with this name (an annotated tag)"),
                CliOption.Switch("--publish", "publish", "Also save the project and commit its file (Git LFS), the base the team opens; the owner's only"),
                CliOption.Text("--sync-folder", "sync_folder", "PATH", "Refuse unless the open project's sync folder is this one"),
            },
            Execute = Execute,
            Build = Line,
        };

        static IDictionary<string, object> Execute(CliCall call)
        {
            if (!call.Options.Params.TryGetValue("message", out var given) || string.IsNullOrWhiteSpace(Convert.ToString(given)))
                throw new CliFailure("commit", "usage", "-m MESSAGE is required: the commit message", "cts commit --help", 2);
            var message = Convert.ToString(given);
            var tag = call.Options.Params.TryGetValue("tag", out var named) ? Convert.ToString(named) : "";
            var publish = call.Options.Params.ContainsKey("publish");
            string folder;
            string target;
            try
            {
                if (string.IsNullOrEmpty(call.Hello.SyncFolder)) throw new InvalidOperationException("the open project has no sync folder: cts set-sync-folder PATH sets one");
                folder = GitRepository.Repository(call.Hello.SyncFolder);
                Check(folder, tag);
                target = publish ? Publishable(folder, call.Hello.ProjectPath) : null;
            }
            catch (InvalidOperationException error)
            {
                throw new CliFailure("commit", "refused", error.Message, "cts commit --help", 1);
            }
            var data = new Dictionary<string, object>();
            var differ = Differences(call, data);
            try
            {
                if (target != null)
                {
                    call.Call("project.save", new Dictionary<string, object>());
                    data["published"] = Stage(folder, call.Hello.ProjectPath, target);
                }
                var identity = Identity(folder);
                GitRepository.Run(folder, "add -A -- . \":(exclude)*.project\"");
                var files = GitRepository.Run(folder, "diff --cached --name-only -z").Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries).Length;
                if (files > 0) GitRepository.RunWithInput(folder, "commit -q -F -", identity, message);
                if (tag.Length > 0) GitRepository.RunWithInput(folder, "tag -a " + ProcessArgs.Quote(tag) + " -F -", identity, message);
                data["committed"] = files > 0;
                data["files"] = files;
            }
            catch (InvalidOperationException error)
            {
                throw new CliFailure("commit", "refused", error.Message + "; nothing committed", "cts commit --help", 1);
            }
            foreach (var pair in GitRepository.Position(folder)) data[pair.Key] = pair.Value;
            if (tag.Length > 0) data["tag"] = tag;
            // The label names the commit the IDE's code is: only when the IDE
            // and the files agree, and not on a published file, saved before its commit.
            if (target == null && differ == 0) ProjectSource.Mark(call, folder, ViewFolder.Of(folder), data);
            // The commit holds the files, never the project file: say so when
            // the IDE still has edits its project file lacks.
            if (target == null && Equals(call.Call("project.status", new Dictionary<string, object>()).TryGetValue("unsaved_changes", out var unsaved) ? unsaved : null, true))
                data["ide_unsaved"] = true;
            return data;
        }

        // How many objects the IDE and the disk hold differently, by cts
        // compare, into data["differ"]; -1 with data["compare_error"] when
        // the compare failed.  Never stops the commit: it commits the disk.
        static int Differences(CliCall call, IDictionary<string, object> data)
        {
            try
            {
                var summary = (IDictionary<string, object>)ComparePlanner.Plan(call)["summary"];
                var count = new[] { "modified", "added", "deleted", "not_importable", "ide_changed" }.Sum(key => JsonMap.Int(summary, key));
                data["differ"] = count;
                return count;
            }
            catch (CliFailure error)
            {
                data["compare_error"] = error.Message;
                return -1;
            }
        }

        // What the commit would fail on, before anything moves: a
        // detached HEAD (the commit would belong to no branch) and a tag name
        // that is not valid or already taken.
        static void Check(string folder, string tag)
        {
            if (GitRepository.Position(folder)["branch"] == null)
                throw new InvalidOperationException("not on a branch (a tag or commit is checked out): cts branch NAME starts one here");
            if (tag.Length == 0) return;
            var valid = GitRun.In(folder, "check-ref-format " + ProcessArgs.Quote("refs/tags/" + tag));
            if (valid.ExitCode != 0) throw new InvalidOperationException(tag + " is not a valid tag name");
            var taken = GitRun.In(folder, "rev-parse --verify --quiet " + ProcessArgs.Quote("refs/tags/" + tag));
            if (taken.ExitCode == 0) throw new InvalidOperationException("tag " + tag + " already exists");
        }

        // Where --publish puts the open *project*: the project file the
        // repository tracks, else the open one when it lies in the
        // repository, else a file of its name at the root. Refused on a
        // machine that is not the project's owner, without Git LFS, or with
        // several project files tracked: before the sync, so nothing moved.
        static string Publishable(string folder, string project)
        {
            if (string.IsNullOrEmpty(project)) throw new InvalidOperationException("no project is open");
            if (!ProjectInfo.IsOwner(ProjectInfo.ProjectIdOf(folder)))
                throw new InvalidOperationException("only the project's owner publishes its file, and this machine is not it (cts set-sync-folder --owner makes it the owner)");
            var lfs = GitRun.In(folder, "lfs version");
            if (lfs.ExitCode != 0)
                throw new InvalidOperationException("the project file is published with Git LFS, which this git lacks: install it (git for Windows includes it), then run git lfs install");
            var tracked = GitRepository.Run(folder, "ls-files -z -- *.project").Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries);
            if (tracked.Length > 1) throw new InvalidOperationException("the repository tracks several project files (" + string.Join(", ", tracked) + "): keep one");
            if (tracked.Length == 1) return Path.Combine(folder, tracked[0].Replace('/', Path.DirectorySeparatorChar));
            var relative = Relative(folder, project);
            return relative != null ? project : Path.Combine(folder, Path.GetFileName(project));
        }

        // Copies the saved *project* to *target* when that is another file
        // and stages it under Git LFS; its path in the repository.
        static string Stage(string folder, string project, string target)
        {
            if (!string.Equals(Path.GetFullPath(target), Path.GetFullPath(project), StringComparison.OrdinalIgnoreCase)) File.Copy(project, target, true);
            GitRepository.Run(folder, "lfs track \"*.project\"");
            var relative = Relative(folder, target);
            GitRepository.Run(folder, "add -- .gitattributes " + ProcessArgs.Quote(relative));
            return relative;
        }

        // *path* relative to *folder* with forward slashes, or null when it lies outside.
        static string Relative(string folder, string path)
        {
            var root = Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var full = Path.GetFullPath(path);
            if (!full.StartsWith(root, StringComparison.OrdinalIgnoreCase)) return null;
            return full.Substring(root.Length).Replace(Path.DirectorySeparatorChar, '/');
        }

        // The environment of a commit made for the user: none when git has
        // the user's name and e-mail, cts' own identity otherwise.
        static IDictionary<string, string> Identity(string folder)
        {
            var name = GitRun.In(folder, "config user.name");
            var email = GitRun.In(folder, "config user.email");
            return name.ExitCode == 0 && email.ExitCode == 0 ? null : CtsIdentity;
        }

        static Answer Line(IDictionary<string, object> data)
        {
            var commit = Convert.ToString(data["commit"]);
            var answer = new Answer().Add("branch", data["branch"]).Add("commit", commit.Substring(0, Math.Min(8, commit.Length))).Add("files", data["files"]);
            if (data.ContainsKey("tag")) answer.Add("tag", data["tag"]);
            if (data.ContainsKey("published")) answer.Add("published", data["published"]);
            var differ = data.TryGetValue("differ", out var counted) ? Convert.ToInt32(counted, CultureInfo.InvariantCulture) : 0;
            if (differ > 0)
                answer.Add("ide_differs", differ).Detail("[WARN] the IDE and the disk differ in " + differ + " object(s), and the commit holds the disk's: cts compare names them; cts export or cts sync carries the IDE's edits into the files, then cts commit again");
            if (data.TryGetValue("compare_error", out var failed))
                answer.Detail("[WARN] the IDE was not compared with the disk (" + failed + "); the commit holds the disk's files");
            if (Equals(data.ContainsKey("ide_unsaved") ? data["ide_unsaved"] : null, true))
                answer.Detail("the IDE project stays unsaved: the commit holds the folder's files, not the project file; cts save when the engineer wants it saved");
            return answer;
        }
    }
}
