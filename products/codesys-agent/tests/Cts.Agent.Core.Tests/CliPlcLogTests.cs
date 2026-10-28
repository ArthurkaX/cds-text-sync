using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        // A runtime log: noise, valid CTS lines and malformed ones. Of its 11
        // CTS lines one has no time stamp, so no logger entry makes it: the
        // entries carry 10, 5 of them valid.
        static readonly string[] RuntimeLog =
        {
            "2026-04-22T18:23:47.110Z, 0x00008005, 1, 1, 0, SAC -> FSC",
            "2026-04-22T18:23:48.001Z, 0x00000001, 1, 1, 0, CTS|M|ALM_RAISE|P1_OVERLOAD|I=12.4;LT1=78",
            "2026-04-22T18:23:48.002Z, 0x00000002, 16, 1, 0, CTS|V|DBG_STEP|P1|state=RUN;step=4",
            "2026-04-22T18:23:48.003Z, 0x00000003, 2, 1, 0, CTS|M|ALM_CLEAR|",
            "2026-04-22T18:23:48.004Z, 0x00000004, 1, 1, 0, CTS|M|ALM_RAISE|P1_OVERLOAD|I=12.4;LT1=78",
            "2026-04-22T18:23:48.005Z, 0x00000005, 1, 1, 0, prefix CTS|M|MSG_WRAPPED|T2|x=1",
            "2026-04-22T18:23:48.006Z, 0x00000006, 1, 1, 0, CTS|X|BAD_LEVEL|T1",
            "2026-04-22T18:23:48.007Z, 0x00000007, 1, 1, 0, CTS|M|bad_code|T1",
            "2026-04-22T18:23:48.008Z, 0x00000008, 1, 1, 0, CTS|M|ALM_RAISE|T1|novalue",
            "2026-04-22T18:23:48.009Z, 0x00000009, 1, 1, 0, CTS|M|ALM_RAISE|T1|K=1|bad",
            "2026-04-22T18:23:48.010Z, 0x00000010, 1, 1, 0, CTS|",
            "2026-04-22T18:23:48.011Z, 0x00008005, 1, 1, 0, {\"trackingReport\":{\"lic\":\"321\"}}",
        };

        static List<object> Entries() => RuntimeLog.Select(line =>
        {
            var f = line.Split(new[] { ", " }, 6, StringSplitOptions.None);
            return (object)new Dictionary<string, object>
            {
                { "time", f[0] }, { "cmp_id", Convert.ToInt64(f[1].Substring(2), 16) }, { "class", long.Parse(f[2]) },
                { "error_id", long.Parse(f[3]) }, { "info_id", long.Parse(f[4]) }, { "info", f[5] },
            };
        }).ToList();

        // An agent with one logger; the methods it was asked, with their parameters.
        static FakeHost LogAgent(List<string> asked, string error = null)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                asked.Add(method + (p.TryGetValue("logger", out var l) ? " " + l : ""));
                if (error != null) throw new ProtocolException("unavailable", error);
                if (method == "plc.loggers") return new Dictionary<string, object> { { "loggers", new List<object> { "/var/log/codesyscontrol.log" } } };
                Assert.Equal("plc.log", method);
                var logger = (string)p["logger"];
                return new Dictionary<string, object> { { "logger", logger.Length > 0 ? logger : "/var/log/codesyscontrol.log" }, { "entries", Entries() } };
            });
            return host;
        }

        static IDictionary<string, object> JsonOf(string output) => (IDictionary<string, object>)Json.Parse(output);

        [Fact]
        public void A_cts_line_parses_into_every_field()
        {
            var record = CtsEvents.Parse(RuntimeLog[1]);

            Assert.Equal("2026-04-22T18:23:48.001Z", record["time"]);
            Assert.Equal("M", record["level"]);
            Assert.Equal("ALM_RAISE", record["code"]);
            Assert.Equal("P1_OVERLOAD", record["tag"]);
            Assert.Equal(new Dictionary<string, object> { { "I", "12.4" }, { "LT1", "78" } }, record["fields"]);
            Assert.Equal(RuntimeLog[1], record["raw"]);
            Assert.False(record.ContainsKey("parse_error"));
        }

        [Fact]
        public void The_marker_may_sit_anywhere_and_the_stamp_may_be_missing()
        {
            Assert.Null(CtsEvents.Parse(RuntimeLog[0]));
            Assert.Equal("MSG_WRAPPED", CtsEvents.Parse(RuntimeLog[5])["code"]);
            var bare = CtsEvents.Parse("CTS|V|DBG_NO_TS|P3|k=v");
            Assert.Equal("", bare["time"]);
            Assert.Equal("V", bare["level"]);
            var empty = CtsEvents.Parse(RuntimeLog[3]);
            Assert.Equal("", empty["tag"]);
            Assert.Empty((IDictionary<string, object>)empty["fields"]);
        }

        [Theory]
        [InlineData("CTS|X|BAD_LEVEL|T1", "level 'X' is not M or V")]
        [InlineData("CTS|M|bad_code|T1", "code 'bad_code' is not [A-Z0-9_]+")]
        [InlineData("CTS|M|ALM_RAISE|T1|novalue", "field 'novalue' has no '='")]
        [InlineData("CTS|M|ALM_RAISE|T1|K=1|bad", "value for 'K' contains '|'")]
        [InlineData("CTS|", "missing level/code")]
        public void A_malformed_line_is_kept_with_its_reason(string line, string reason)
        {
            Assert.Equal(reason, CtsEvents.Parse(line)["parse_error"]);
        }

        [Fact]
        public void An_entry_prints_as_its_runtime_log_file_line()
        {
            Assert.Equal(RuntimeLog, Entries().Cast<IDictionary<string, object>>().Select(PlcLogCommand.Line));
        }

        [Fact]
        public void An_entry_with_line_breaks_in_its_text_prints_as_one_line()
        {
            var entry = (IDictionary<string, object>)Entries()[0];
            entry["info"] = "Dynamic memory allocation started.\n";
            Assert.Equal("2026-04-22T18:23:47.110Z, 0x00008005, 1, 1, 0, Dynamic memory allocation started.", PlcLogCommand.Line(entry));
            entry["info"] = "first\r\nsecond\n";
            Assert.Equal("2026-04-22T18:23:47.110Z, 0x00008005, 1, 1, 0, first second", PlcLogCommand.Line(entry));
        }

        [Fact]
        public void Without_options_plc_log_prints_default_tail_and_lists_the_loggers()
        {
            var asked = new List<string>();

            var (code, output, _) = Run(LogAgent(asked), "plc-log");

            Assert.Equal(0, code);
            Assert.Equal(new[] { "plc.log ", "plc.loggers" }, asked);
            Assert.Contains("ok plc-log logger=/var/log/codesyscontrol.log", output);
            Assert.Contains("loggers /var/log/codesyscontrol.log", output);
            Assert.Contains(RuntimeLog.Last(), output);
        }

        [Fact]
        public void The_tail_is_the_last_lines_of_the_first_logger_or_the_one_named()
        {
            var asked = new List<string>();

            var (_, output, _) = Run(LogAgent(asked), "plc-log", "--tail", "2");
            var json = JsonOf(Run(LogAgent(asked), "plc-log", "--logger", "PlcLog", "--tail", "1", "--json").output);

            Assert.Equal("ok plc-log logger=/var/log/codesyscontrol.log tail_count=2 total_lines=12\n"
                + RuntimeLog[10] + "\n" + RuntimeLog[11] + "\nide-1 · no project\n", output);
            Assert.Equal(new[] { "plc.log ", "plc.log PlcLog" }, asked);
            Assert.Equal("PlcLog", json["logger"]);
            Assert.Equal(new List<object> { RuntimeLog[11] }, json["tail"]);
        }

        // A runtime line whose cause is not in its text comes with a hint.
        [Fact]
        public void Known_runtime_lines_come_with_a_hint_each_once()
        {
            var hints = PlcLogCommand.Hints(new[]
            {
                "2026-10-22T08:00:00.000Z, 0x00000002, 1, 0, 0, #### Exception: *EXCEPTION* [AccessViolation] occurred: App=[TestApp], Task=[TestTask]",
                "2026-10-22T08:00:01.000Z, 0x0000005e, 4, 0, 0, TlsCreateContext2: Failed to save context",
                "2026-10-22T08:00:02.000Z, 0x0000005e, 4, 0, 0, TlsCreateContext2: Failed to save context",
            });

            Assert.Equal(2, hints.Count);
            var details = PlcLogCommand.Build(new Dictionary<string, object> { { "logger", "PlcLog" }, { "hints", hints.Cast<object>().ToList() } }).Details;
            Assert.Contains("hint: the runtime ran out of TLS contexts (Failed to save context)", string.Join("\n", details));
            Assert.Contains("hint: an exception stopped an application", string.Join("\n", details));
            Assert.Empty(PlcLogCommand.Hints(RuntimeLog));
        }

        [Fact]
        public void A_long_tail_is_shown_whole()
        {
            var output = Run(LogAgent(new List<string>()), "plc-log", "--tail", "50").output;

            Assert.Equal(RuntimeLog.Length + 2, output.TrimEnd('\n').Split('\n').Length);
            Assert.Equal(output, Run(LogAgent(new List<string>()), "plc-log", "--tail", "0").output);
        }

        [Fact]
        public void The_agents_refusal_is_the_cause()
        {
            var (code, output, _) = Run(LogAgent(new List<string>(), "Not connected. Run 'cts connect' first."), "plc-log", "--tail", "5");

            Assert.Equal(1, code);
            Assert.StartsWith("error plc-log cause=\"Not connected. Run 'cts connect' first.\"", output);
        }

        [Fact]
        public void Output_after_the_command_is_the_file_a_folder_gets_the_loggers_name()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-plclog-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var json = JsonOf(Run(LogAgent(new List<string>()), "--json", "plc-log", "--out", folder).output);
                var named = JsonOf(Run(LogAgent(new List<string>()), "plc-log", "--logger", "PlcLog", "--out", folder, "--json").output);
                var file = Path.Combine(folder, "new", "copy.log");
                var copy = JsonOf(Run(LogAgent(new List<string>()), "plc-log", "--out", file, "--json").output);

                Assert.Equal(Path.Combine(folder, "codesyscontrol.log"), json["saved_to"]);
                Assert.Equal(12L, json["saved_lines"]);
                Assert.Equal(RuntimeLog, File.ReadAllLines(Path.Combine(folder, "codesyscontrol.log")));
                Assert.Equal(Path.Combine(folder, "PlcLog.log"), named["saved_to"]);
                Assert.Equal(file, copy["saved_to"]);
                Assert.True(File.Exists(file));
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Cts_parses_the_entries_and_keeps_the_malformed_apart()
        {
            var json = JsonOf(Run(LogAgent(new List<string>()), "plc-log", "--cts", "--json").output);
            var tail = JsonOf(Run(LogAgent(new List<string>()), "plc-log", "--cts", "--tail", "200", "--json").output);

            Assert.Equal("log", json["source"]);
            Assert.Equal("tail", tail["source"]);
            Assert.Equal(5L, json["count"]);
            Assert.Equal(5L, json["parse_errors"]);
            Assert.Equal("ALM_RAISE", ((IDictionary<string, object>)((List<object>)json["records"])[0])["code"]);
            Assert.All((List<object>)json["malformed"], m => Assert.Equal(new[] { "parse_error", "raw", "time" }, ((IDictionary<string, object>)m).Keys.OrderBy(k => k)));
            Assert.All((List<object>)json["records"], r => Assert.False(((IDictionary<string, object>)r).ContainsKey("parse_error")));
        }

        [Fact]
        public void An_empty_cts_filter_says_what_writes_cts_entries_unless_some_are_malformed()
        {
            const string hint = "No CTS| entries: only ST code that logs the CTS| marker writes them (cts test's test application does). Next: cts plc-log --tail N shows the raw log";
            IDictionary<string, object> Data(params object[] malformed) => new Dictionary<string, object>
                { { "logger", "/var/log/codesyscontrol.log" }, { "count", 0L }, { "records", new List<object>() }, { "malformed", malformed.ToList() } };

            Assert.Contains(hint, PlcLogCommand.Build(Data()).Details);
            Assert.DoesNotContain(hint, PlcLogCommand.Build(Data(new Dictionary<string, object> { { "parse_error", "missing level/code" }, { "raw", "CTS|" } })).Details);
        }

        [Fact]
        public void Level_and_code_filter_the_records_and_imply_cts()
        {
            var verbose = JsonOf(Run(LogAgent(new List<string>()), "plc-log", "--level", "V", "--json").output);
            var (_, step, _) = Run(LogAgent(new List<string>()), "plc-log", "--code", "DBG_STEP");

            Assert.Equal(1L, verbose["count"]);
            Assert.Equal(5L, verbose["parse_errors"]);
            Assert.StartsWith("ok plc-log logger=/var/log/codesyscontrol.log source=log count=1 parse_errors=5\n" + RuntimeLog[2] + "\n"
                + "malformed (level 'X' is not M or V): " + RuntimeLog[6] + "\n", step);
        }
    }
}
