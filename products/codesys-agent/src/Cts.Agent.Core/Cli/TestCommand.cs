using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts test`: runs the test application in simulation (agent `test.app`),
    // names each test from the run's log, and always keeps that log as a file:
    // --output, else <sync folder>/.git/cts/test/<application>.log.
    public static class TestCommand
    {
        public static IDictionary<string, object> Execute(CliCall call)
        {
            var options = call.Options.Params;
            var parameters = new Dictionary<string, object>();
            if (options.TryGetValue("application", out var application)) parameters["application"] = application;
            if (options.ContainsKey("plc")) parameters["plc"] = true;
            var repeat = options.TryGetValue("repeat", out var times) ? Convert.ToInt64(times, CultureInfo.InvariantCulture) : 1;
            if (repeat < 1) throw new CliFailure("test", "usage", "--repeat is 1 or more", "cts test --help", 2);
            parameters["repeat"] = repeat;
            var wait = options.TryGetValue("wait", out var seconds) ? Convert.ToDouble(seconds, CultureInfo.InvariantCulture) : 30;
            parameters["wait_ms"] = (long)(wait * 1000);
            var watch = ProjectFileWatch.Start(call.Hello.ProjectPath);
            var data = new Dictionary<string, object>(call.Call(AppTests.Method, parameters, Math.Max(call.Seconds, repeat * (wait + 90))));
            watch.Report(data);

            var runs = Items(data, "runs").OfType<IDictionary<string, object>>().ToList();
            List<string> lines;
            if (runs.Count == 0)
            {
                lines = Items(data, "log").OfType<IDictionary<string, object>>().Select(PlcLogCommand.Line).ToList();
                data["tests"] = Tests(lines, null);
            }
            else
            {
                lines = new List<string>();
                var tests = new List<object>();
                foreach (var run in runs)
                {
                    var runLines = Items(run, "log").OfType<IDictionary<string, object>>().Select(PlcLogCommand.Line).ToList();
                    lines.AddRange(runLines);
                    tests.AddRange(Tests(runLines, Value(run, "run")));
                    run.Remove("log");
                }
                data["tests"] = tests;
            }
            var target = Destination(options.TryGetValue("output", out var output) ? Convert.ToString(output, CultureInfo.InvariantCulture) : "",
                call.Hello.SyncFolder, Convert.ToString(data.TryGetValue("application", out var named) ? named : AppTests.DefaultApplication, CultureInfo.InvariantCulture));
            File.WriteAllText(target, string.Concat(lines.Select(l => l + "\n")), new UTF8Encoding(false));
            data["log_file"] = target;
            data["log_lines"] = (long)lines.Count;
            return data;
        }

        // The tests a run's log names; *run* numbers them when there were several.
        static List<object> Tests(IEnumerable<string> lines, object run) => lines.Select(CtsEvents.Parse)
            .Where(r => r != null && !r.ContainsKey("parse_error") && (Equals(r["code"], "TEST_PASS") || Equals(r["code"], "TEST_FAIL")))
            .Select(r =>
            {
                var test = new Dictionary<string, object>
                {
                    { "name", r["tag"] },
                    { "status", Equals(r["code"], "TEST_PASS") ? "PASS" : "FAIL" },
                    { "fields", r["fields"] },
                };
                if (run != null) test["run"] = run;
                return (object)test;
            })
            .ToList();

        // The tests one run counted: with several runs, passed= and failed= are their sums.
        static long PerRun(IDictionary<string, object> run) =>
            Convert.ToInt64(Value(run, "passed") ?? 0L, CultureInfo.InvariantCulture) + Convert.ToInt64(Value(run, "failed") ?? 0L, CultureInfo.InvariantCulture);

        public static Answer Build(IDictionary<string, object> data)
        {
            var runs = Items(data, "runs").OfType<IDictionary<string, object>>().ToList();
            var answer = new Answer()
                .Add("passed", Value(data, "passed"))
                .Add("failed", Value(data, "failed"))
                .Add("runs", runs.Count > 0 ? (object)runs.Count : null)
                .Add("per_run", runs.Count > 0 ? (object)PerRun(runs[0]) : null)
                .Add("failed_runs", runs.Count > 0 ? (object)runs.Count(run => !Equals(Value(run, "status"), "PASS")) : null)
                .Add("restart", Value(data, "restart"))
                .Add("application", Value(data, "application"))
                .Add("device", Value(data, "device"))
                .Add("plc", Equals(Value(data, "plc"), true) ? (object)true : null)
                .Add("ms", Value(data, "ms"))
                .Add("log", Value(data, "log_file"));
            if (Equals(Value(data, "saved_by_ide"), true)) answer.Add("saved", "by-ide").Detail(DownloadCommand.SavedByIde);
            foreach (var test in Items(data, "tests").OfType<IDictionary<string, object>>().Where(t => Equals(t["status"], "FAIL")))
            {
                var fields = (test["fields"] as IDictionary<string, object> ?? new Dictionary<string, object>()).Select(f => f.Key + "=" + f.Value);
                answer.Detail(string.Join(" ", new[] { (test.ContainsKey("run") ? "run " + test["run"] + ": " : "") + "FAIL " + test["name"] }.Concat(fields)));
            }
            if (runs.Count == 0)
            {
                answer.Detail(Value(data, "error"));
                answer.Detail(Value(data, "log_error"));
            }
            foreach (var run in runs)
                foreach (var key in new[] { "error", "log_error" })
                    if (Value(run, key) != null) answer.Detail("run " + Value(run, "run") + ": " + Value(run, key));
            foreach (var notice in Items(data, "runtime_notices").Concat(runs.SelectMany(run => Items(run, "runtime_notices"))).Distinct())
                answer.Detail("runtime notice, not in the log file: " + notice);
            foreach (var tidy in new[] { "logout", "reactivate" })
                if (Value(data, tidy) is string said && said != "ok") answer.Detail(tidy + ": " + said);
            return Equals(Value(data, "status"), "PASS") ? answer : answer.Failed();
        }

        // --output (a file, or a folder to put <application>.log in), else the
        // sync folder's .git/cts/test, else the temp folder.
        static string Destination(string output, string syncFolder, string application)
        {
            var name = application + ".log";
            string target;
            if (output.Length > 0)
            {
                target = Path.GetFullPath(output);
                if (Directory.Exists(target) || output.EndsWith("/", StringComparison.Ordinal) || output.EndsWith("\\", StringComparison.Ordinal))
                    target = Path.Combine(target, name);
            }
            else if (!string.IsNullOrEmpty(syncFolder) && Directory.Exists(Path.Combine(syncFolder, ".git")))
                target = Path.Combine(syncFolder, ".git", "cts", "test", name);
            else
                target = Path.Combine(Path.GetTempPath(), "cts-test", name);
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            return target;
        }

    }
}
