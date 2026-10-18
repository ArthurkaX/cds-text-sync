using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal static class SyncGit
    {
        internal const int FetchWaitMs = 30000;

        // The run's branch, or the commit a detached HEAD is at; both null
        // without git or a repository.
        internal static string Branch(string folder, out string detachedAt)
        {
            detachedAt = null;
            if (folder.Length == 0) return null;
            var branch = Git(folder, "symbolic-ref -q --short HEAD", false);
            if (branch != null) return branch;
            detachedAt = Git(folder, "rev-parse --short HEAD", false);
            return null;
        }

        // The header's last commit of the folder's HEAD; null without one.
        internal static string LastCommit(string folder)
        {
            return folder.Length == 0 ? null : WidgetMenu.LastCommit(Git(folder, "log -1 --format=%s%x09%ct", false), DateTime.Now);
        }

        // How far *branch* is from its upstream's last fetched state, as git
        // counts it ("ahead<TAB>behind"); null without a branch or an upstream.
        internal static string Tracking(string folder, string branch)
        {
            return branch == null ? null : Git(folder, "rev-list --left-right --count HEAD...@{upstream}", false);
        }

        // `git fetch` of the branch's remote that never asks: a remote that
        // wants a password git does not hold fails instead of prompting.
        // False when it fails, git is missing or it is still running after
        // FetchWaitMs.
        internal static bool Fetch(string folder)
        {
            var quiet = new Dictionary<string, string> { { "GCM_INTERACTIVE", "never" }, { "SSH_ASKPASS_REQUIRE", "never" } };
            try
            {
                using (var process = GitRun.Start(folder, "fetch --quiet", quiet, false, false, false))
                {
                    if (process.WaitForExit(FetchWaitMs)) return process.ExitCode == 0;
                    process.Kill();
                    return false;
                }
            }
            catch (InvalidOperationException) { return false; }
        }

        // Local branches, most recent first.
        internal static IEnumerable<string> BranchNames(string folder)
        {
            return (Git(folder, "for-each-ref --sort=-committerdate --format=%(refname:short) refs/heads", true) ?? "")
                .Split('\n').Select(name => name.Trim());
        }

        // git's output: its first line, or all of it with *whole*; null when
        // it fails, says nothing or is not installed.
        internal static string Git(string folder, string args, bool whole)
        {
            GitRun run;
            try { run = GitRun.In(folder, args); }
            catch (InvalidOperationException) { return null; }
            var output = run.ExitCode != 0 ? "" : run.Output.Trim();
            if (output.Length == 0) return null;
            return whole ? output : output.Split('\n').First().Trim();
        }
    }
}
