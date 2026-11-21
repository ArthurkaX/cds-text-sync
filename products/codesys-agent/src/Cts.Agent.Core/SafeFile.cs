using System;
using System.IO;
using System.Threading;

namespace Cts.Agent
{
    public static class SafeFile
    {
        const int Attempts = 8;

        // Moves `temporary` over `path`; the old file stays until the new one is in place.
        public static void Replace(string temporary, string path) =>
            Retry(path, () => { if (File.Exists(path)) File.Replace(temporary, path, null); else File.Move(temporary, path); });

        public static void Delete(string path) => Retry(path, () => File.Delete(path));

        // Windows refuses to replace or delete a file another program has open
        // without delete sharing (an antivirus scanning a file just written, a
        // search indexer, a git client watching the folder), usually for a
        // moment: it is tried again for about 3 s, then fails naming the file.
        static void Retry(string path, Action action)
        {
            for (var attempt = 1; ; attempt++)
            {
                try { action(); return; }
                catch (Exception error) when (Busy(error) && attempt < Attempts) { Thread.Sleep(100 * attempt); }
                catch (Exception error) when (Busy(error))
                {
                    throw new IOException(error.Message.TrimEnd() + " " + path + " (tried for 3 s: another program may hold it open, such as an antivirus, a search indexer or a git client)", error);
                }
            }
        }

        static bool Busy(Exception error) =>
            error is UnauthorizedAccessException || error is IOException && !(error is FileNotFoundException) && !(error is DirectoryNotFoundException);
    }
}
