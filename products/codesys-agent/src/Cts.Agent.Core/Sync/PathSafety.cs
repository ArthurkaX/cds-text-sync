using System;
using System.IO;
using System.Linq;

namespace Cts.Sync
{
    public static class PathSafety
    {
        public static string SafePath(string root, string relative)
        {
            var parts = (relative ?? "").Replace('\\', '/').Split('/');
            if (parts.Any(p => p == ".." || p == ".") || (parts.Length > 0 && parts[0].StartsWith("."))) return null;
            var fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var full = Path.GetFullPath(Path.Combine(root, relative.Replace('/', Path.DirectorySeparatorChar)));
            return full.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase) ? full : null;
        }
    }
}
