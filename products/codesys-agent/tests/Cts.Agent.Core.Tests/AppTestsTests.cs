using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class AppTestsTests
    {
        const string Main = "11111111-1111-1111-1111-111111111111";
        const string Test = "22222222-2222-2222-2222-222222222222";

        readonly List<string> _calls = new List<string>();
        readonly Dictionary<string, object> _plc = new Dictionary<string, object>();
        bool _simulation = true;
        string _testName = "TestApp";
        long _now;
        int _doneAfterReads = 1;
        readonly List<object> _log = new List<object>();
        bool _logFails;

        Dictionary<string, object> Run(string application = "", long waitMs = 0)
        {
            return AppTests.Run(application, waitMs, Fake, ms => _now += ms, () => _now);
        }

        IDictionary<string, object> Fake(string method, Dictionary<string, object> parameters)
        {
            _calls.Add(method + " " + Json.Serialize(parameters));
            switch (method)
            {
                case "project.devices":
                    return new Dictionary<string, object>
                    {
                        { "devices", new List<object>
                            {
                                Device("PLC_Main", false, App(Main, "Application", true)),
                                Device("Test", _simulation, App(Test, _testName, false)),
                            } },
                    };
                case "app.activate":
                case "app.logout":
                    return new Dictionary<string, object>();
                case "app.download":
                    return new Dictionary<string, object> { { "application_state", "run" } };
                case "plc.log":
                    if (_logFails) throw new ProtocolException(ErrorCodes.Unavailable, "no logger service");
                    return new Dictionary<string, object> { { "entries", _log } };
                case "vars.read":
                    var rows = new List<object>();
                    foreach (string name in (IList<object>)parameters["names"])
                    {
                        if (name == "TestResult.Done") rows.Add(Ok(--_doneAfterReads <= 0));
                        else if (_plc.TryGetValue(name, out var value)) rows.Add(Ok(value));
                        else rows.Add(new Dictionary<string, object> { { "ok", false }, { "error", new Dictionary<string, object> { { "message", "not exported" } } } });
                    }
                    return new Dictionary<string, object> { { "logged_in", true }, { "results", rows } };
            }
            throw new ProtocolException(ErrorCodes.UnknownMethod, method);
        }

        static Dictionary<string, object> Ok(object value)
        {
            return new Dictionary<string, object> { { "ok", true }, { "value", value } };
        }

        static Dictionary<string, object> Device(string path, bool simulation, Dictionary<string, object> app)
        {
            return new Dictionary<string, object> { { "path", path }, { "simulation", simulation }, { "applications", new List<object> { app } } };
        }

        static Dictionary<string, object> App(string guid, string name, bool active)
        {
            return new Dictionary<string, object> { { "guid", guid }, { "name", name }, { "active", active } };
        }

        void Counts(long passed, long failed)
        {
            _plc["TestResult.Passed"] = passed;
            _plc["TestResult.Failed"] = failed;
        }

        void Logged(params string[] infos)
        {
            foreach (var info in infos) _log.Add(new Dictionary<string, object> { { "info", info } });
        }

        static List<string> Infos(object log)
        {
            return ((IList<object>)log).Select(e => (string)((IDictionary<string, object>)e)["info"]).ToList();
        }

        [Fact]
        public void Passing_run_switches_to_the_test_application_and_back()
        {
            Counts(3, 0);
            var answer = Run();
            Assert.Equal("PASS", answer["status"]);
            Assert.Equal(3L, answer["passed"]);
            Assert.Equal("Test", answer["device"]);
            var methods = _calls.Select(c => c.Split(' ')[0] + (c.Contains(Main) ? " main" : c.Contains(Test) ? " test" : "")).ToList();
            Assert.Equal(new[] { "project.devices", "app.activate test", "app.download", "vars.read", "vars.read", "plc.log", "app.logout test", "app.activate main" }, methods);
        }

        [Fact]
        public void The_run_log_starts_at_the_last_test_start()
        {
            Counts(2, 1);
            Logged("CTS|M|TEST_START|TestApp|", "CTS|M|TEST_FAIL|old run|", "Application started",
                "CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|F_Clamp lifts to lo|", "CTS|M|TEST_FAIL|F_Clamp cuts to hi|got=11;want=10");
            var answer = Run();
            Assert.Equal("FAIL", answer["status"]);
            Assert.Equal(new[] { "CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|F_Clamp lifts to lo|", "CTS|M|TEST_FAIL|F_Clamp cuts to hi|got=11;want=10" },
                Infos(answer["log"]));
            Assert.False(answer.ContainsKey("log_error"));
        }

        [Fact]
        public void A_log_without_a_test_start_is_named_and_the_counts_still_decide()
        {
            Counts(3, 0);
            Logged("Application started");
            var answer = Run();
            Assert.Equal("PASS", answer["status"]);
            Assert.Empty(Infos(answer["log"]));
            Assert.Contains("no CTS|M|TEST_START| record", (string)answer["log_error"]);
        }

        [Fact]
        public void A_log_that_cannot_be_read_does_not_fail_the_run()
        {
            Counts(3, 0);
            _logFails = true;
            var answer = Run();
            Assert.Equal("PASS", answer["status"]);
            Assert.Contains("no logger service", (string)answer["log_error"]);
            Assert.Contains(_calls, c => c.StartsWith("app.logout"));
        }

        [Fact]
        public void Done_is_polled_until_true()
        {
            Counts(1, 0);
            _doneAfterReads = 4;
            Assert.Equal("PASS", Run()["status"]);
            Assert.Equal(300, _now);
        }

        [Fact]
        public void A_run_that_never_ends_fails_after_the_wait_and_still_switches_back()
        {
            Counts(1, 0);
            _doneAfterReads = int.MaxValue;
            var answer = Run(waitMs: 1000);
            Assert.Equal("FAIL", answer["status"]);
            Assert.Contains("Done stayed FALSE", (string)answer["error"]);
            Assert.Contains(_calls, c => c.StartsWith("app.activate") && c.Contains(Main));
        }

        [Fact]
        public void A_device_not_in_simulation_is_refused_before_anything_changes()
        {
            _simulation = false;
            var e = Assert.Throws<ProtocolException>(() => Run());
            Assert.Contains("not in simulation", e.Message);
            Assert.Equal(new[] { "project.devices {}" }, _calls);
        }

        [Fact]
        public void A_missing_application_names_the_ones_there_are()
        {
            var e = Assert.Throws<ProtocolException>(() => Run("UnitTests"));
            Assert.Contains("No application 'UnitTests'", e.Message);
            Assert.Contains("Test/TestApp", e.Message);
        }

        [Fact]
        public void Two_applications_of_the_name_are_refused()
        {
            _testName = "Application";
            var e = Assert.Throws<ProtocolException>(() => Run("Application"));
            Assert.Contains("Two applications", e.Message);
        }

        [Fact]
        public void A_missing_result_gvl_points_at_the_convention_and_switches_back()
        {
            _plc.Clear();
            var e = Assert.Throws<ProtocolException>(() => Run());
            Assert.Contains("needs a GVL TestResult", e.Message);
            Assert.Contains(_calls, c => c.StartsWith("app.logout"));
            Assert.Contains(_calls, c => c.StartsWith("app.activate") && c.Contains(Main));
        }
    }
}
