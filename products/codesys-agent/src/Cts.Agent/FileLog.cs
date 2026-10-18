using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace Cts.Agent
{
    // Append-only log. Never throws: the IDE must not be hurt by a full disk.
    // It also keeps its last lines in memory and tells listeners of each new
    // one, which is what the agent's activity window shows. Every IDE writes
    // the same file, so a line there carries the IDE's process id.
    internal sealed class FileLog
    {
        const long MaxBytes = 2 * 1024 * 1024;
        const int Kept = 1000;
        readonly string _path;
        readonly object _lock = new object();
        readonly Queue<string> _recent = new Queue<string>();
        readonly string _pid = " [" + System.Diagnostics.Process.GetCurrentProcess().Id + "]";

        public FileLog(string path) { _path = path; }

        //: Raised with each line as it is written, on the writer's thread.
        public event Action<string> Written;

        public string[] Recent()
        {
            lock (_lock) return _recent.ToArray();
        }

        public void Write(string text)
        {
            var stamp = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss.fff");
            var line = stamp + " " + text;
            lock (_lock)
            {
                _recent.Enqueue(line);
                while (_recent.Count > Kept) _recent.Dequeue();
                if (!string.IsNullOrEmpty(_path))
                {
                    try
                    {
                        var info = new FileInfo(_path);
                        if (info.Exists && info.Length > MaxBytes)
                            File.Move(_path, _path + ".1" + (File.Exists(_path + ".1") ? DateTime.Now.Ticks.ToString() : ""));
                        File.AppendAllText(_path, stamp + _pid + " " + text + Environment.NewLine, new UTF8Encoding(false));
                    }
                    catch { }
                }
            }
            var written = Written;
            if (written == null) return;
            try { written(line); }
            catch { }
        }
    }
}
