using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        static Dictionary<string, object> Trace(params (string key, object value)[] extra)
        {
            var trace = new Dictionary<string, object>
            {
                { "exists", true }, { "application", "Application" }, { "task", "Task" }, { "every", 1L }, { "samples", 1000L },
                { "variables", new List<object> { "GVL_IO.rLevel", "GVL_IO.xRun" } },
            };
            foreach (var (key, value) in extra) trace[key] = value;
            return trace;
        }

        [Fact]
        public void Trace_set_passes_what_it_was_given_and_keeps_the_traces_task()
        {
            var calls = new List<string>();
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                calls.Add(method + " " + Json.Serialize(p));
                return method == "trace.read" ? Trace() : Trace(("created", false), ("trigger", "GVL_IO.xRun"), ("edge", "rising"), ("post", 500L));
            });

            var (code, output, _) = Run(host, "trace", "set", "GVL_IO.rLevel", "--trigger", "GVL_IO.xRun", "--post", "500", "--no-condition");

            Assert.Equal(0, code);
            Assert.StartsWith("trace.set {\"variables\":[\"GVL_IO.rLevel\"],\"trigger\":\"GVL_IO.xRun\",\"post\":500,\"condition\":\"\",", calls.Last());
            Assert.StartsWith("ok trace-set application=Application created=false task=Task every=1 samples=1000\n", output);
            Assert.Contains("\ntrigger GVL_IO.xRun rising, 500 samples after it\nNext: cts trace start", output);
            Assert.Contains("a condition and no condition", Run(host, "trace", "set", "--condition", "GVL_IO.xRun", "--no-condition").error);
        }

        [Fact]
        public void Trace_set_gives_the_time_the_buffer_and_the_post_samples_take_from_the_tasks_cycle()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-trace-" + Guid.NewGuid().ToString("N"));
            var golden = Directory.GetDirectories(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "expected"), "Application", SearchOption.AllDirectories).Single();
            foreach (var file in Directory.GetFiles(golden, "*", SearchOption.AllDirectories))
            {
                var copy = Path.Combine(root, "project-view", "Dev", "Plc Logic", "Application", file.Substring(golden.Length + 1));
                Directory.CreateDirectory(Path.GetDirectoryName(copy));
                File.Copy(file, copy);
            }
            var host = new FakeHost();
            host.Agents[1] = Agent(Path.Combine(root, "Dev.project"), root, (method, p) => method == "trace.read"
                ? Trace()
                : Trace(("created", false), ("samples", 5000L), ("every", 2L), ("trigger", "GVL_IO.xRun"), ("edge", "rising"), ("post", 4500L)));
            try
            {
                var (code, output, _) = Run(host, "trace", "set", "--samples", "5000", "--every", "2");

                Assert.Equal(0, code);
                Assert.StartsWith("ok trace-set application=Application created=false task=Task every=2 samples=5000 sample_ms=400\n", output);
                Assert.Contains("\nthe buffer holds 2000 s = 33.3 min: 5000 samples, one each 400 ms\ntrigger GVL_IO.xRun rising, 4500 samples (1800 s = 30 min) after it\n", output);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Trace_remove_says_what_it_removed_and_whether_the_plc_was_reached()
        {
            var answers = new Queue<Dictionary<string, object>>(new[]
            {
                new Dictionary<string, object> { { "removed", false } },
                new Dictionary<string, object> { { "removed", true }, { "plc_deleted", true } },
                new Dictionary<string, object> { { "removed", true }, { "plc_error", "no route" } },
            });
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => answers.Dequeue());

            Assert.StartsWith("ok trace-remove removed=false\nthe application has no CtsTrace\n", Run(host, "trace", "remove").output);
            Assert.StartsWith("ok trace-remove removed=true plc_deleted=true\n", Run(host, "trace", "remove").output);
            Assert.Contains("\nthe PLC was not reached, and may still hold the trace: no route\n", Run(host, "trace", "remove").output);
        }

        [Fact]
        public void Trace_shows_the_plcs_state_or_how_to_get_one()
        {
            var answers = new Queue<Dictionary<string, object>>(new[]
            {
                new Dictionary<string, object> { { "exists", false }, { "application", "Application" } },
                Trace(("on_plc", false)),
                Trace(("on_plc", true), ("state", "Started"), ("trigger_state", "Disabled"), ("count", 42L)),
            });
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => answers.Dequeue());

            Assert.Contains("trace=none\nNext: cts trace set VAR", Run(host, "trace").output);
            Assert.Contains("the PLC has no CtsTrace", Run(host, "trace").output);
            Assert.StartsWith("ok trace application=Application task=Task every=1 samples=1000 state=Started trigger_state=Disabled count=42\n", Run(host, "trace").output);
        }

        [Fact]
        public void Trace_pull_writes_the_csv_and_puts_the_trigger_on_the_samples_clock()
        {
            var file = Path.Combine(Path.GetTempPath(), "cts-trace-" + Guid.NewGuid().ToString("N") + ".csv");
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => new Dictionary<string, object>
            {
                { "packet", "Application.CtsTrace" }, { "state", "Stopped" }, { "trigger_state", "TriggerReached" },
                { "start", 1000L }, { "trigger_at", 1020L }, { "microseconds", false },
                { "variables", new List<object>
                    {
                        new Dictionary<string, object> { { "name", "GVL_IO.xRun" }, { "type", "bool" }, { "t", new List<object> { 0L, 10L, 20L, 30L } }, { "v", new List<object> { 0L, 0L, 1L, 1L } } },
                    } },
            });
            try
            {
                var (code, output, _) = Run(host, "trace", "pull", "--csv", file);

                Assert.Equal(0, code);
                Assert.StartsWith("ok trace-pull samples=4 span_ms=30 trigger_ms=20 state=Stopped trigger_state=TriggerReached\n", output);
                Assert.Contains("\nGVL_IO.xRun  BOOL  first 0 last 1 min 0 max 1 changes 1: 20 ms 0->1\ncsv " + file + "\n", output);
                Assert.Equal("t_ms,GVL_IO.xRun\n0,0\n10,0\n20,1\n30,1\n", File.ReadAllText(file));
            }
            finally { File.Delete(file); }
        }
    }
}
