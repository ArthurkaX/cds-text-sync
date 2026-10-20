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
            var wait = options.TryGetValue("wait", out var seconds) ? Convert.ToDouble(seconds, CultureInfo.InvariantCulture) : 30;
            parameters["wait_ms"] = (long)(wait * 1000);
            var watch = ProjectFileWatch.Start(call.Hello.ProjectPath);
            var data = new Dictionary<string, object>(call.Call(AppTests.Method, parameters, Math.Max(call.Seconds, wait + 90)));
            watch.Report(data);

            var lines = Items(data, "log").OfType<IDictionary<string, object>>().Select(PlcLogCommand.Line).ToList();
            data["tests"] = lines.Select(CtsEvents.Parse)
                .Where(r => r != null && !r.ContainsKey("parse_error") && (Equals(r["code"], "TEST_PASS") || Equals(r["code"], "TEST_FAIL")))
                .Select(r => (object)new Dictionary<string, object>
                {
                    { "name", r["tag"] },
                    { "status", Equals(r["code"], "TEST_PASS") ? "PASS" : "FAIL" },
                    { "fields", r["fields"] },
                })
                .ToList();
            var target = Destination(options.TryGetValue("output", out var output) ? Convert.ToString(output, CultureInfo.InvariantCulture) : "",
                call.Hello.SyncFolder, Convert.ToString(data.TryGetValue("application", out var named) ? named : AppTests.DefaultApplication, CultureInfo.InvariantCulture));
            File.WriteAllText(target, string.Concat(lines.Select(l => l + "\n")), new UTF8Encoding(false));
            data["log_file"] = target;
            data["log_lines"] = (long)lines.Count;
            return data;
        }

        public static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer()
                .Add("passed", Value(data, "passed"))
                .Add("failed", Value(data, "failed"))
                .Add("application", Value(data, "application"))
                .Add("device", Value(data, "device"))
                .Add("ms", Value(data, "ms"))
                .Add("log", Value(data, "log_file"));
            if (Equals(Value(data, "saved_by_ide"), true)) answer.Add("saved", "by-ide").Detail(DownloadCommand.SavedByIde);
            foreach (var test in Items(data, "tests").OfType<IDictionary<string, object>>().Where(t => Equals(t["status"], "FAIL")))
            {
                var fields = (test["fields"] as IDictionary<string, object> ?? new Dictionary<string, object>()).Select(f => f.Key + "=" + f.Value);
                answer.Detail(string.Join(" ", new[] { "FAIL " + test["name"] }.Concat(fields)));
            }
            answer.Detail(Value(data, "error"));
            answer.Detail(Value(data, "log_error"));
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
