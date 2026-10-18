using System.IO;

namespace Cts.Agent
{
    public static class SafeFile
    {
        // Moves `temporary` over `path`; the old file stays until the new one is in place.
        public static void Replace(string temporary, string path)
        {
            if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path);
        }
    }
}
