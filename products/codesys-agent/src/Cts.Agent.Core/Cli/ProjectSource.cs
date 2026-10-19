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
        internal static void Mark(CliCall call, string folder, string view, IDictionary<string, object> output)
        {
            var position = GitRepository.Position(folder);
            var commit = position["commit"] as string;
            if (commit == null) return;
            var uncommitted = GitRepository.Run(folder, "status --porcelain -- " + ProcessArgs.Quote(view)).Length > 0;
            var source = (position["branch"] as string ?? "detached") + "@" + commit.Substring(0, 8) + (uncommitted ? " +uncommitted" : "");
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
