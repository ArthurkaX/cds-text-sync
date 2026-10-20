using System;
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
        Func<long> _flaky;
        Action _late;
        Action _onStart;

        Dictionary<string, object> Run(string application = "", long waitMs = 0, bool plc = false, int repeat = 1, bool reset = false)
        {
            return AppTests.Run(new AppTests.Request { Application = application, WaitMs = waitMs, Plc = plc, Repeat = repeat, ResetAllowed = reset },
                Fake, ms => _now += ms, () => _now);
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
                case "app.reset":
                    return new Dictionary<string, object>();
                case "app.start":
                    _onStart?.Invoke();
                    _doneAfterReads = 1;
                    return new Dictionary<string, object> { { "application_state", "run" } };
                case "app.download":
                    _onStart?.Invoke();
                    _doneAfterReads = Math.Max(_doneAfterReads, 1);
                    return new Dictionary<string, object> { { "application_state", "run" } };
                case "plc.log":
                    if (_logFails) throw new ProtocolException(ErrorCodes.Unavailable, "no logger service");
                    _late?.Invoke();
                    return new Dictionary<string, object> { { "entries", _log } };
                case "vars.read":
                    var rows = new List<object>();
                    foreach (string name in (IList<object>)parameters["names"])
                    {
                        if (name == "TestResult.Done") rows.Add(Ok(--_doneAfterReads <= 0));
                        else if (name == "TestResult.Failed" && _flaky != null) rows.Add(Ok(_flaky()));
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
            Logged("CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|", "CTS|M|TEST_PASS|c|");
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
            Counts(1, 1);
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
            Logged("CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|a|");
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
            Assert.Contains("cts test --plc", e.Message);
            Assert.Equal(new[] { "project.devices {}" }, _calls);
        }

        [Fact]
        public void Plc_runs_on_a_device_that_is_not_in_simulation()
        {
            _simulation = false;
            Counts(2, 0);
            // A PLC's log keeps an earlier command's records; this run's come late.
            Logged("CTS|M|TEST_START|TestApp|earlier", "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|");
            var readsAfterStart = -1;
            _onStart = () => readsAfterStart = 0;
            _late = () => { if (readsAfterStart >= 0 && ++readsAfterStart == 2) Logged("CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|"); };
            var answer = Run(plc: true);
            Assert.Equal("PASS", answer["status"]);
            Assert.Equal(true, answer["plc"]);
            Assert.Contains(_calls, c => c.StartsWith("app.download"));
            Assert.Equal(new[] { "CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|" }, Infos(answer["log"]));
        }

        // A flaky test fails one run of several: the run fails and says which.
        [Fact]
        public void Repeat_restarts_by_reset_when_allowed_and_any_failing_run_fails()
        {
            Counts(2, 0);
            var reads = 0;
            _flaky = () => ++reads == 2 ? 1L : 0L;
            var answer = Run(repeat: 3, reset: true);
            Assert.Equal("FAIL", answer["status"]);
            Assert.Equal("reset", answer["restart"]);
            var runs = ((IList<object>)answer["runs"]).Cast<IDictionary<string, object>>().ToList();
            Assert.Equal(new[] { "PASS", "FAIL", "PASS" }, runs.Select(run => (string)run["status"]));
            Assert.Equal(1, _calls.Count(c => c.StartsWith("app.download")));
            Assert.Equal(2, _calls.Count(c => c.StartsWith("app.reset")));
        }

        [Fact]
        public void Repeat_downloads_again_when_the_reset_is_denied()
        {
            Counts(2, 0);
            var answer = Run(repeat: 2);
            Assert.Equal("PASS", answer["status"]);
            Assert.Equal("download", answer["restart"]);
            Assert.Equal(2, _calls.Count(c => c.StartsWith("app.download")));
            Assert.DoesNotContain(_calls, c => c.StartsWith("app.reset"));
        }

        // The records reach the log a read or two after Done: each run waits
        // for its own TEST_START and results, and a run whose records never
        // come gets no log rather than the run before's.
        [Fact]
        public void Each_run_waits_for_its_own_records_in_the_log()
        {
            Counts(2, 0);
            var started = 0;
            var reads = 0;
            _late = () =>
            {
                if (++reads % 2 == 0 && _log.Count < started * 3)
                    Logged("CTS|M|TEST_START|TestApp|@" + started, "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|");
            };
            _onStart = () => started++;
            var answer = Run(repeat: 3, reset: true);
            var runs = ((IList<object>)answer["runs"]).Cast<IDictionary<string, object>>().ToList();
            Assert.Equal("CTS|M|TEST_START|TestApp|@1", Infos(runs[0]["log"])[0]);
            Assert.Equal("CTS|M|TEST_START|TestApp|@2", Infos(runs[1]["log"])[0]);
            Assert.False(runs[1].ContainsKey("log_error"));
            Assert.Equal("CTS|M|TEST_START|TestApp|@3", Infos(runs[2]["log"])[0]);

            _log.Clear();
            _late = () => { if (_log.Count == 0) Logged("CTS|M|TEST_START|TestApp|", "CTS|M|TEST_PASS|a|", "CTS|M|TEST_PASS|b|"); };
            runs = ((IList<object>)Run(repeat: 2, reset: true)["runs"]).Cast<IDictionary<string, object>>().ToList();
            Assert.Equal(3, Infos(runs[0]["log"]).Count);
            Assert.Empty(Infos(runs[1]["log"]));
            Assert.Contains("no CTS|M|TEST_START| record of this run 5 s after TestResult.Done", (string)runs[1]["log_error"]);
            Assert.Equal("PASS", runs[1]["status"]);
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
