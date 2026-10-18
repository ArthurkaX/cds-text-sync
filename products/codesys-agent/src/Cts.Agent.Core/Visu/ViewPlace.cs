using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;

namespace Cts.Visu
{
    // Where --folder and --screen point in the project view. A folder name
    // matches whatever its case, as it does in the IDE and on Windows.
    internal static class ViewPlace
    {
        const int FoldersNamed = 12;

        internal static string Folder(string view, string folder)
        {
            var path = view;
            foreach (var part in (folder ?? "").Replace('\\', '/').Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries))
            {
                var exact = Path.Combine(path, part);
                path = Directory.Exists(exact) || !Directory.Exists(path) ? exact
                    : Directory.GetDirectories(path).FirstOrDefault(directory => string.Equals(Path.GetFileName(directory), part, StringComparison.OrdinalIgnoreCase)) ?? exact;
            }
            return path;
        }

        // The folder a new screen goes into; missing, the error names the folders that hold objects.
        internal static string ExistingFolder(string view, string folder)
        {
            var path = Folder(view, folder);
            if (Directory.Exists(path)) return path;
            var known = Directory.GetDirectories(view, "*", SearchOption.AllDirectories)
                .Where(directory => Directory.EnumerateFiles(directory).Any(file => file.EndsWith(".xml", StringComparison.OrdinalIgnoreCase) || file.EndsWith(".st", StringComparison.OrdinalIgnoreCase)))
                .Select(directory => Relative(view, directory))
                .OrderBy(name => name, StringComparer.OrdinalIgnoreCase).ToList();
            throw new VisuException("No folder '" + folder + "' in the project view. Folders that hold objects: " + Names(known));
        }

        // A folder of the view as cts project-tree prints it.
        internal static string Relative(string view, string directory) => directory.Substring(view.Length).Replace('\\', '/').Trim('/');

        internal static string Names(IReadOnlyCollection<string> folders) =>
            string.Join(", ", folders.Take(FoldersNamed)) + (folders.Count > FoldersNamed ? ", ... (" + folders.Count + ")" : "");

        // <name>.xml under *folder*, else the one such file anywhere in the view.
        internal static string Screen(string view, string screen, string folder)
        {
            if (File.Exists(screen)) return Path.GetFullPath(screen);
            var name = screen.EndsWith(".xml", StringComparison.Ordinal) ? screen : screen + ".xml";
            var candidate = Path.Combine(Folder(view, folder), name);
            if (File.Exists(candidate)) return candidate;
            var matches = Directory.GetFiles(view, name, SearchOption.AllDirectories).OrderBy(path => path, StringComparer.Ordinal).ToList();
            if (matches.Count == 1) return matches[0];
            if (matches.Count > 1)
                throw new VisuException("Screen name '" + screen + "' is ambiguous (" + matches.Count + " matches); pass --folder:\n  " + string.Join("\n  ", matches));
            return candidate;
        }
    }
}
