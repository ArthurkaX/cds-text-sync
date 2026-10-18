using System;
using System.IO;

namespace Cts.Sync
{
    // Where a sync folder keeps the IDE's objects: its project-view.
    internal static class ViewFolder
    {
        internal static string Of(string root) => Path.Combine(root, "project-view");

        // The sync folder a path names: the folder itself, or the one whose
        // project-view it is.
        internal static string Named(string path)
        {
            var folder = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return Path.GetFileName(folder).Equals("project-view", StringComparison.OrdinalIgnoreCase) ? Path.GetDirectoryName(folder) : folder;
        }

        // The nearest folder from work up with a cds-text-sync.json or a
        // project-view; null outside a sync folder.
        internal static string Around(string work)
        {
            for (var dir = new DirectoryInfo(work); dir != null; dir = dir.Parent)
                if (File.Exists(Path.Combine(dir.FullName, "cds-text-sync.json")) || Directory.Exists(Path.Combine(dir.FullName, "project-view"))) return dir.FullName;
            return null;
        }
    }
}
