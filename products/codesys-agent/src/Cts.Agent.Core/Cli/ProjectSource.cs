using System;
using System.Collections.Generic;
using System.Globalization;
using Cts.Agent;

namespace Cts.Cli
{
    // The label `cts-source` in Project Information: the branch and commit
    // the IDE's code came from, "+uncommitted" when the view held changes no
    // commit has.  Set after an import or a sync that carried everything and
    // after a commit, so a project file opened anywhere says where its code
    // came from (`cts status`, CODESYS' Project Information).  Only a label:
    // edits after it are what cts compare finds.
    internal static class ProjectSource
    {
        const string Uncommitted = " +uncommitted";

        // The commit a `cts-source` *label* names; null when the view held
        // changes no commit has, or the label names none.
        internal static string Commit(string label)
        {
            var source = ProjectInfo.SourceOf(label);
            var at = source.LastIndexOf('@');
            return at < 0 || source.EndsWith(Uncommitted, StringComparison.Ordinal) ? null : source.Substring(at + 1);
        }

        // How many commits the folder's HEAD is past the commit a `cts-source`
        // *label* names, when HEAD descends from it: the project file was saved
        // before them (or a pull brought them), so the IDE lacks what they
        // changed. Null when the label names no commit HEAD descends from.
        internal static int? Behind(string folder, string label)
        {
            var commit = Commit(label);
            if (commit == null || GitRun.In(folder, "merge-base --is-ancestor " + ProcessArgs.Quote(commit) + " HEAD").ExitCode != 0) return null;
            var count = GitRun.In(folder, "rev-list --count " + ProcessArgs.Quote(commit) + "..HEAD");
            return count.ExitCode == 0 && int.TryParse(count.Output.Trim(), NumberStyles.None, CultureInfo.InvariantCulture, out var n) ? n : (int?)null;
        }

        internal static void Mark(CliCall call, string folder, string view, IDictionary<string, object> output)
        {
            var position = GitRepository.Position(folder);
            var commit = position["commit"] as string;
            if (commit == null) return;
            var uncommitted = GitRepository.Run(folder, "status --porcelain -- " + ProcessArgs.Quote(view)).Length > 0;
            var source = (position["branch"] as string ?? "detached") + "@" + commit.Substring(0, 8) + (uncommitted ? Uncommitted : "");
            try
            {
                call.Call("project.source", new Dictionary<string, object>
                {
                    { "source", source },
                    { "when", DateTime.Now.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture) },
                });
                output["source"] = source;
            }
            catch (CliFailure error) when (error.Declined) { output["source_error"] = error.Message; }
        }
    }
}
