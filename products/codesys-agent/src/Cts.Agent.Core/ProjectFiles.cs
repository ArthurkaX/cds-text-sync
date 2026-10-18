// The rules `project.list`, `project.open` and `project.close` apply to
// project files, apart from the IDE that holds them.
using System;
using System.IO;

namespace Cts.Agent
{
    public static class ProjectFiles
    {
        // A project's name is its file's: the IDE gives a project no other.
        public static string DisplayName(string path)
        {
            return string.IsNullOrEmpty(path) ? "" : Path.GetFileNameWithoutExtension(path);
        }

        // A library project is a `.library` file; it has no application.
        public static bool IsLibrary(string path)
        {
            return !string.IsNullOrEmpty(path) && path.EndsWith(".library", StringComparison.OrdinalIgnoreCase);
        }

        // Windows paths: the same file whatever the case or the separators.
        public static bool SamePath(string a, string b)
        {
            if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b)) return false;
            return string.Equals(Normal(a), Normal(b), StringComparison.OrdinalIgnoreCase);
        }

        static string Normal(string path)
        {
            var full = Path.GetFullPath(path);
            // A drive root keeps its separator: "C:" alone is a working directory.
            if (full.Length <= Path.GetPathRoot(full).Length) return full;
            return full.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        }

        // Refused before the IDE is touched: the agent runs in CODESYS, whose
        // working directory is not the caller's.
        public static void RequireOpenable(string path)
        {
            if (string.IsNullOrEmpty(path))
                throw new ProtocolException(ErrorCodes.BadParams, "project open requires a 'path'");
            if (!Path.IsPathRooted(path))
                throw new ProtocolException(ErrorCodes.BadParams, "path must be absolute: path " + path);
            if (!File.Exists(path))
                throw new ProtocolException(ErrorCodes.BadParams, "No project file at " + path);
        }

        // Closing a project with unsaved changes brings up the IDE's modal save
        // prompt, so it is refused instead.
        public static ProtocolException Unsaved(string what, string then)
        {
            return new ProtocolException(ErrorCodes.BadParams,
                what + " has unsaved changes. Run `cts save`, then " + then + ", or discard the changes in CODESYS.");
        }
    }
}
