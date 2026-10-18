using System;
using System.Diagnostics;
using System.IO;
using System.Threading;

namespace Cts.Sync
{
    // One cts run at a time in a sync folder: an exclusive handle on
    // .git/cts/run.lock. The OS drops it when the process ends, so a run that
    // died leaves nothing to clean up.
    internal sealed class FolderLock : IDisposable
    {
        readonly FileStream _stream;

        FolderLock(FileStream stream) { _stream = stream; }

        internal static FolderLock Acquire(string folder, TextWriter error, TimeSpan timeout)
        {
            var dotGit = Path.Combine(folder, ".git");
            var gitDir = Directory.Exists(dotGit) ? dotGit : Cts.Agent.GitRepository.Run(folder, "rev-parse --absolute-git-dir").Trim();
            var path = Path.Combine(gitDir, "cts", "run.lock");
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var timer = Stopwatch.StartNew();
            var waiting = false;
            while (true)
            {
                try { return new FolderLock(new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None)); }
                catch (IOException)
                {
                    if (!waiting) error.WriteLine("progress: waiting for another cts run in this folder");
                    waiting = true;
                    if (timer.Elapsed >= timeout) throw new InvalidOperationException("another cts run is still working in " + folder);
                    Thread.Sleep(200);
                }
            }
        }

        public void Dispose() { _stream.Dispose(); }
    }
}
