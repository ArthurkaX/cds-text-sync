using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Cts.Agent
{
    // The cts.exe runs of one IDE session: started off the UI thread, timed, and kept for a failure's report.
    internal sealed class CtsRunner
    {
        readonly FileLog _log;
        readonly Action<int> _comparing;
        //: What the last successful run of each kind (WidgetMenu.Kind) took, this IDE session.
        readonly Dictionary<string, long> _took = new Dictionary<string, long>();
        //: The cts processes running now, counted from any thread.
        int _running;
        //: The last runs, oldest first, for a failure's report; locked.
        readonly List<WidgetRun> _runs = new List<WidgetRun>();

        internal CtsRunner(FileLog log, Action<int> comparing)
        {
            _log = log;
            _comparing = comparing;
        }

        internal IList<WidgetRun> Runs
        {
            get { lock (_runs) return _runs.ToList(); }
        }

        internal bool Running => Volatile.Read(ref _running) > 0;

        // A cts run read for its JSON: whether it succeeded, and all it printed or its verdict line.
        internal Task<Tuple<bool, string>> Whole(string[] args, string folder)
        {
            var done = new TaskCompletionSource<Tuple<bool, string>>();
            Run(args, folder, (ok, output) => done.SetResult(Tuple.Create(ok, output)), true);
            return done.Task;
        }

        // One cts run off the UI thread; *done* gets whether it succeeded and
        // its verdict line, or with *whole* all it printed when it succeeded
        // (a command read for its JSON).  *stderr* gets each line cts writes
        // there as it comes (its stages).  A *timed* run's time is what the
        // next run of its kind (WidgetMenu.Kind) is measured against.
        internal void Run(string[] args, string folder, Action<bool, string> done, bool whole = false,
            Action<string> stderr = null, bool timed = true)
        {
            var info = CtsStart(args, folder);
            var reading = args.Length == 1 && args[0] == "compare";
            if (reading) _comparing(1);
            Interlocked.Increment(ref _running);
            Task.Run(() =>
            {
                string line;
                var ok = false;
                var said = "";
                var told = "";
                var exit = -1;
                var started = DateTime.Now;
                var clock = Stopwatch.StartNew();
                try
                {
                    using (var process = new Process { StartInfo = info })
                    {
                        var errors = new StringBuilder();
                        process.ErrorDataReceived += (s, e) =>
                        {
                            if (e.Data == null) return;
                            lock (errors) errors.AppendLine(e.Data);
                            stderr?.Invoke(e.Data);
                        };
                        process.Start();
                        process.BeginErrorReadLine();
                        said = process.StandardOutput.ReadToEnd();
                        // Without a timeout it also waits for the last stderr line.
                        process.WaitForExit();
                        lock (errors) told = errors.ToString();
                        exit = process.ExitCode;
                        line = WidgetMenu.Outcome(said, told, exit);
                        ok = exit == 0;
                    }
                }
                catch (Exception e) { line = "cts did not start: " + e.Message; }
                Keep(new WidgetRun { Started = started, CommandLine = ProcessArgs.Join(args), ExitCode = exit, Milliseconds = clock.ElapsedMilliseconds, Output = said, Errors = told, Line = line });
                if (ok && timed)
                    lock (_took) _took[WidgetMenu.Kind(args)] = clock.ElapsedMilliseconds;
                _log.Write("widget: cts " + ProcessArgs.Join(args) + ": " + (whole && ok ? "read" : line));
                if (reading) _comparing(-1);
                Interlocked.Decrement(ref _running);
                done(ok, whole && ok ? said : line);
            });
        }

        void Keep(WidgetRun run)
        {
            lock (_runs)
            {
                _runs.Add(run);
                if (_runs.Count > WidgetReport.Kept) _runs.RemoveAt(0);
            }
        }

        internal long? Took(string[] args)
        {
            long last;
            lock (_took) return _took.TryGetValue(WidgetMenu.Kind(args), out last) ? last : (long?)null;
        }

        ProcessStartInfo CtsStart(string[] args, string folder)
        {
            var info = CtsProcess(args, folder);
            info.RedirectStandardOutput = true;
            info.RedirectStandardError = true;
            info.StandardOutputEncoding = Encoding.UTF8;
            info.StandardErrorEncoding = Encoding.UTF8;
            // cts names each stage it reaches on stderr (WidgetMenu.Stage).
            info.EnvironmentVariables["CTS_PROGRESS"] = "1";
            return info;
        }

        ProcessStartInfo CtsProcess(string[] args, string folder)
        {
            // cts.exe is deployed beside the agent.
            var exe = Path.Combine(Path.GetDirectoryName(typeof(CtsRunner).Assembly.Location), "cts.exe");
            var info = new ProcessStartInfo(exe, ProcessArgs.Join(args))
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                WorkingDirectory = folder.Length > 0 ? folder : Environment.CurrentDirectory,
            };
            info.EnvironmentVariables["CTS_IDE_PID"] = Process.GetCurrentProcess().Id.ToString();
            return info;
        }
    }
}
