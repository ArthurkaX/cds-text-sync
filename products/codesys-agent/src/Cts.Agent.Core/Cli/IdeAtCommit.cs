using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // Whether the IDE holds exactly the sync folder's commit: there is a sync
    // base, nothing is uncommitted (the open project's own file aside) and
    // cts compare finds no difference. cts checkout needs it before it
    // switches; cts download records the commit the PLC's code came from then.
    internal static class IdeAtCommit
    {
        // Throws InvalidOperationException naming what is off.
        internal static void Require(CliCall call, string folder)
        {
            var baseRef = GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}");
            if (baseRef.ExitCode != 0) throw new InvalidOperationException("no sync base yet: run cts export first");
            if (GitRepository.Position(folder)["commit"] == null) throw new InvalidOperationException("the sync folder's repository has no commit yet: cts commit makes the first");
            var paths = FolderGit.Uncommitted(folder, call.Hello.ProjectPath);
            if (paths.Count > 0) throw new InvalidOperationException("uncommitted changes in the sync folder, cts commit them first: " + string.Join(", ", paths.Take(5)) + (paths.Count > 5 ? " (+" + (paths.Count - 5) + " more)" : ""));
            var summary = ComparePlanner.Plan(call)["summary"] as IDictionary<string, object>;
            var differs = string.Join(" ", summary.Where(pair => pair.Key != "unchanged" && Convert.ToInt32(pair.Value) != 0).OrderBy(pair => pair.Key).Select(pair => pair.Key + "=" + pair.Value));
            if (differs.Length > 0) throw new InvalidOperationException("the IDE and the sync folder differ (" + differs + "): cts compare names the objects; cts sync, cts import or cts export brings them together");
        }
    }
}
