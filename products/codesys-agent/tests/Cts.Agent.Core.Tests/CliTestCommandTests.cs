using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        static Dictionary<string, object> Entry(string info)
        {
            return new Dictionary<string, object>
            {
                { "time", "2026-10-15T20:00:00.000Z" }, { "cmp_id", 0L }, { "class", 1L }, { "error_id", 0L }, { "info_id", 0L }, { "info", info },
            };
        }

        // An agent whose test application ran once: two tests passed, one failed.
        static FakeHost TestAgent(string syncFolder, List<IDictionary<string, object>> asked)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(@"C:\work\plant\.project\plant.project", syncFolder, (method, p) =>
            {
                Assert.Equal("test.app", method);
                asked.Add(p);
                return new Dictionary<string, object>
                {
                    { "application", "TestApp" }, { "device", "Test" }, { "status", "FAIL" }, { "done", true },
                    { "passed", 2L }, { "failed", 1L }, { "ms", 4350L }, { "logout", "ok" }, { "reactivate", "ok" },
                    { "log", new List<object>
                        {
                            Entry("CTS|M|TEST_START|TestApp|"),
                            Entry("CTS|M|TEST_PASS|F_Clamp keeps a value inside|"),
                            Entry("CTS|M|TEST_PASS|F_Clamp lifts to lo|"),
                            Entry("CTS|M|TEST_FAIL|F_Clamp cuts to hi|got=11;want=10"),
                        } },
                };
            });
            return host;
        }

        [Fact]
        public void Test_names_the_failures_from_the_log_and_keeps_the_log_in_the_sync_folder()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(folder, ".git"));
            try
            {
                var asked = new List<IDictionary<string, object>>();
                var (code, output, _) = Run(TestAgent(folder, asked), "test", "--wait", "5");
                Assert.Equal(1, code);
                Assert.Contains("FAIL F_Clamp cuts to hi got=11 want=10", output);
                Assert.Equal(5000L, asked.Single()["wait_ms"]);
                var log = Path.Combine(folder, ".git", "cts", "test", "TestApp.log");
                Assert.Contains("log=" + log, output.Replace("\"", ""));
                var lines = File.ReadAllLines(log);
                Assert.Equal(4, lines.Length);
                Assert.EndsWith(", CTS|M|TEST_FAIL|F_Clamp cuts to hi|got=11;want=10", lines[3]);

                var json = JsonOf(Run(TestAgent(folder, asked), "test", "--json").output);
                var tests = ((IEnumerable<object>)json["tests"]).Cast<IDictionary<string, object>>().ToList();
                Assert.Equal(new[] { "PASS", "PASS", "FAIL" }, tests.Select(t => (string)t["status"]));
                Assert.Equal("F_Clamp lifts to lo", tests[1]["name"]);
            }
            finally { Directory.Delete(folder, true); }
        }

        // Three runs on a PLC, the second failing one test: the line counts the
        // failed run and names the test with its run.
        [Fact]
        public void Test_repeat_on_a_plc_names_each_failing_test_with_its_run()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(Path.Combine(folder, ".git"));
            try
            {
                IDictionary<string, object> asked = null;
                var host = new FakeHost();
                host.Agents[1] = Agent(@"C:\work\plant\.project\plant.project", folder, (method, p) =>
                {
                    asked = p;
                    Dictionary<string, object> Ran(long run, string status, params string[] infos) => new Dictionary<string, object>
                    {
                        { "run", run }, { "status", status }, { "passed", 1L }, { "failed", status == "PASS" ? 0L : 1L }, { "done", true },
                        { "log", infos.Length == 0 ? new List<object>() : new List<object> { Entry("CTS|M|TEST_START|TestApp|") }.Concat(infos.Select(info => (object)Entry(info))).ToList() },
                        { "log_error", infos.Length == 0 ? "the log took nothing" : null },
                    };
                    return new Dictionary<string, object>
                    {
                        { "application", "TestApp" }, { "device", "PLC" }, { "plc", true }, { "status", "FAIL" }, { "restart", "download" },
                        { "passed", 1L }, { "failed", 0L }, { "logout", "ok" },
                        { "runs", new List<object>
                            {
                                Ran(1, "PASS", "CTS|M|TEST_PASS|timer|"),
                                Ran(2, "FAIL", "CTS|M|TEST_FAIL|timer|got=4999;want=5000"),
                                Ran(3, "PASS"),
                            } },
                    };
                });
                var (code, output, _) = Run(host, "test", "--plc", "--repeat", "3");
                Assert.Equal(1, code);
                Assert.Equal(true, asked["plc"]);
                Assert.Equal(3L, asked["repeat"]);
                Assert.StartsWith("error test passed=1 failed=0 runs=3 failed_runs=1 restart=download application=TestApp device=PLC plc=true", output);
                Assert.Contains("\nrun 2: FAIL timer got=4999 want=5000\n", output);
                Assert.Contains("\nrun 3: the log took nothing\n", output);
                Assert.Equal(4, File.ReadAllLines(Path.Combine(folder, ".git", "cts", "test", "TestApp.log")).Length);
                Assert.StartsWith("error test cause=usage", Run(host, "test", "--repeat", "0").output);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Test_output_puts_the_log_where_it_is_asked()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-test-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var file = Path.Combine(folder, "run.log");
                var json = JsonOf(Run(TestAgent(null, new List<IDictionary<string, object>>()), "test", "--output", file, "--json").output);
                Assert.Equal(file, json["log_file"]);
                Assert.Equal(4L, json["log_lines"]);
                Assert.True(File.Exists(file));
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
