using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ComparePlanner
    {
        const string StaleReason = "the project file is older than the folder; cts import brings it up to date";

        // A project file saved before the folder's last imports, opened again,
        // holds an older view than the base. Its `cts-source` *label* names the
        // commit its code came from: where the IDE holds that commit's file and
        // the base another, that file's base is the commit's, so the folder's
        // newer text is a change on disk cts import carries, not an edit in the
        // IDE cts sync would undo. Returns the paths so taken.
        static ISet<string> StaleBase(string folder, string viewRelative, string label, IViewFiles ideFiles, ref IViewFiles baseView, ContentKeyCache contentKeys)
        {
            var stale = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var commit = ProjectSource.Commit(label);
            if (commit == null || GitRun.In(folder, "rev-parse --verify --quiet " + ProcessArgs.Quote(commit + "^{commit}")).ExitCode != 0) return stale;
            GitTreeViewFiles source;
            try { source = new GitTreeViewFiles(folder, commit, viewRelative); }
            catch (InvalidOperationException) { return stale; }
            using (source)
            {
                var view = baseView;
                foreach (var path in ideFiles.Paths.Union(view.Paths, StringComparer.OrdinalIgnoreCase))
                    if (!SameViewContent(path, ideFiles, view, contentKeys) && SameViewContent(path, ideFiles, source, contentKeys)) stale.Add(path);
                if (stale.Count == 0) return stale;
                var sourcePaths = new HashSet<string>(source.Paths, StringComparer.OrdinalIgnoreCase);
                var taken = new MemoryViewFiles();
                foreach (var path in stale.Where(sourcePaths.Contains)) taken.Write(path, source.Read(path));
                baseView = new OverlayViewFiles(view, taken, stale.Where(path => !sourcePaths.Contains(path)));
            }
            return stale;
        }

        static string StaleNote(string label, int files) => "The open project file is older than the folder: the IDE holds the text of "
            + ProjectInfo.SourceOf(label) + " in " + files + " file(s) the folder changed since, no edit in the IDE; cts import brings the project up to date.";
    }
}
