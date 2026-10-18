using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Cli
{
    // A colleague's PC keeps to its part in git too.  The project file its
    // CODESYS saves stays out of its commits (git's skip-worktree: git does
    // not see the file change), and git's pre-push hook runs `cts hook
    // pre-push`, which refuses a push to the team's default branch and one of
    // commits that change a project file.  Both are this PC's, set by `cts
    // set-sync-folder` and `cts project update` for the role this PC has; the
    // hook asks the role at each push.  `git push --no-verify` passes it: the
    // hard rule is the server's branch protection.
    internal static class TeamGuard
    {
        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "hook",
            Arguments = "pre-push REMOTE [URL] | merge-driver BASE OURS THEIRS [PATH]",
            ArgumentLimit = 5,
            Summary = "What git runs on this PC: the pre-push check and the merge of the objects' XML",
            Description = "cts set-sync-folder sets both up in the sync folder's git, on every PC. "
                + "merge-driver: git merges a view .xml (a task, a Library Manager, any object kept as XML) element by element instead of refusing the whole file: each side's changed values are kept, and the items of a list (a task's program calls, the libraries and their placeholders) are told apart by name, so both sides' additions stay, in order. "
                + "Two sides that changed one value, or one removed an item the other changed, are a conflict git reports, the file left as this branch had it: take a side in your git program. "
                + "It is named in .git/info/attributes (*.xml merge=cts) and git config merge.cts; on a PC without it, the repository's .gitattributes keeps the whole file as one side. "
                + "pre-push: git runs it before a push, with the refs it pushes on standard input (.git/hooks/pre-push, which also runs git lfs pre-push). "
                + "On a PC that is not the project's owner it refuses a push to the remote's default branch (its HEAD, else main and master): the owner merges into it. "
                + "It also refuses commits that change a *.project file: only the owner publishes the project file (cts commit --publish). "
                + "On the owner's PC, and in a folder without a project id, it lets everything pass. git push --no-verify skips it; the server's branch protection is the rule that holds.",
            LocalExecute = (options, host, work) => options.Arguments.Count > 0 && options.Arguments[0] == "merge-driver"
                ? MergeDriver.Run(options.Arguments)
                : PrePush(options.Arguments, work, Console.In.ReadToEnd()),
            Build = data => data.ContainsKey("merged") ? new Answer().Add("merged", data["merged"]) : new Answer().Add("role", data["role"]).Add("refs", data["refs"]),
        };

        // The cts.exe the hook runs: this one.
        internal static string Exe => System.Diagnostics.Process.GetCurrentProcess().MainModule.FileName;

        const string Marker = "# cts: ";
        const string NoCommit = "0000000000000000000000000000000000000000";

        internal static IDictionary<string, object> PrePush(IList<string> arguments, string work, string input)
        {
            if (arguments.Count < 2 || arguments[0] != "pre-push") throw Refuse("usage: cts hook pre-push REMOTE [URL]");
            var remote = arguments[1];
            var root = GitRepository.Run(work, "rev-parse --show-toplevel").Trim();
            var refs = input.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries).Select(line => line.Split(' ')).Where(fields => fields.Length == 4).ToList();
            var id = ProjectInfo.IdOf(root);
            var owner = id == "" || ProjectInfo.IsOwner(id);
            var data = new Dictionary<string, object> { { "role", owner ? "owner" : "colleague" }, { "refs", refs.Count } };
            if (owner) return data;
            var protectedBranches = DefaultBranches(root, remote);
            var problems = new List<string>();
            foreach (var fields in refs)
            {
                var branch = fields[2].StartsWith("refs/heads/", StringComparison.Ordinal) ? fields[2].Substring("refs/heads/".Length) : null;
                if (branch != null && protectedBranches.Contains(branch))
                    problems.Add("the owner pushes " + branch + ", the team's default branch: push your work on a branch of its own (cts branch NAME) and the owner merges it");
                if (fields[1] == NoCommit) continue;
                // Commits no remote has: the ones made on this PC, not the
                // owner's publishes it fetched (a new remote has none of them).
                var range = fields[1] + " --not --remotes" + (fields[3] == NoCommit ? "" : " " + fields[3]);
                var touching = GitRepository.Run(root, "rev-list " + range + " -- *.project").Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);
                if (touching.Length > 0)
                    problems.Add(touching.Length + " commit(s) for " + fields[2] + " change the project file (" + string.Join(", ", touching.Take(3).Select(c => c.Substring(0, 8)))
                        + "): only the owner publishes it; take the change out in your git program (the file as the branch had it)");
            }
            if (problems.Count > 0) throw Refuse("this PC is a colleague's (Alt+Q, Settings, This PC), so nothing was pushed:\n- " + string.Join("\n- ", problems.Distinct()));
            return data;
        }

        // The remote's default branch, as the clone saw it; main and master
        // when the remote has none recorded.
        static ISet<string> DefaultBranches(string root, string remote)
        {
            var head = GitRun.In(root, "symbolic-ref -q --short refs/remotes/" + remote + "/HEAD");
            if (head.ExitCode == 0 && head.Output.Trim().StartsWith(remote + "/", StringComparison.Ordinal))
                return new HashSet<string>(StringComparer.Ordinal) { head.Output.Trim().Substring(remote.Length + 1) };
            return new HashSet<string>(StringComparer.Ordinal) { "main", "master" };
        }

        // This PC's part in *folder*: the tracked project files skipped by
        // git on a colleague's PC, seen on the owner's; the pre-push hook and
        // the XML merge driver, both run by *cts*.  Says what it did.
        internal static IDictionary<string, object> Apply(string folder, bool owner, string cts)
        {
            var projects = GitRepository.Run(folder, "ls-files -z -- *.project").Split(new[] { '\0' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var project in projects) Skip(folder, project, !owner);
            return new Dictionary<string, object> { { "skipped", owner ? 0 : projects.Length }, { "hook", InstallHook(folder, cts) }, { "merge_driver", MergeDriver.Register(folder, cts) } };
        }

        internal static void Skip(string folder, string project, bool skip)
        {
            GitRepository.Run(folder, "update-index " + (skip ? "--skip-worktree" : "--no-skip-worktree") + " -- " + ProcessArgs.Quote(project));
        }

        // "installed", "current", or "kept" for a hook of the user's own,
        // which cts leaves alone.
        static string InstallHook(string folder, string cts)
        {
            var path = Path.GetFullPath(Path.Combine(folder, GitRepository.Run(folder, "rev-parse --git-path hooks/pre-push").Trim()));
            var wanted = Hook(cts);
            var existing = File.Exists(path) ? File.ReadAllText(path) : null;
            if (existing == wanted) return "current";
            if (existing != null && !existing.Contains(Marker) && !LfsOnly(existing)) return "kept";
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, wanted, new UTF8Encoding(false));
            return "installed";
        }

        // The hook git lfs install writes: cts' hook runs git lfs pre-push itself.
        static bool LfsOnly(string hook) => hook.Split('\n').Select(line => line.Trim())
            .Where(line => line.Length > 0 && !line.StartsWith("#", StringComparison.Ordinal))
            .All(line => line.StartsWith("command -v git-lfs", StringComparison.Ordinal) || line.StartsWith("git lfs pre-push", StringComparison.Ordinal));

        static string Hook(string cts) =>
            "#!/bin/sh\n"
            + Marker + "a colleague's PC does not push the team's default branch or the project file (cts hook --help).\n"
            + "refs=$(cat)\n"
            + "cts=\"" + cts.Replace('\\', '/') + "\"\n"
            + "if [ -f \"$cts\" ]; then\n"
            + "  printf '%s\\n' \"$refs\" | \"$cts\" hook pre-push \"$@\" >/dev/null || exit 1\n"
            + "fi\n"
            + "command -v git-lfs >/dev/null 2>&1 || exit 0\n"
            + "printf '%s\\n' \"$refs\" | git lfs pre-push \"$@\"\n";

        static CliFailure Refuse(string message) => new CliFailure("hook", "refused", message, "cts hook --help", 1);
    }
}
