// `test.app {application?, wait_ms?}` (`cts test`): the ST tests of a test
// application, run in simulation.  The project keeps a device in simulation
// mode with an application (TestApp unless named) whose task calls tests on
// the POUs every application shares.  The tests count into a GVL and log each
// result to the runtime's log:
//
//   TestResult.Done      BOOL     TRUE once every test has run
//   TestResult.Passed    UDINT
//   TestResult.Failed    UDINT
//
//   CTS|M|TEST_START|<application>|          once, before the first test
//   CTS|M|TEST_PASS|<test>|                  one per test that passed
//   CTS|M|TEST_FAIL|<test>|k=v;k=v           one per test that failed
//
// The run makes that application the active one, downloads it to the
// simulation and starts it (app.download), reads TestResult.Done until it is
// TRUE, reads the counts, then the simulation's log from its last TEST_START
// on (the run's log: what the tests wrote and what the runtime said meanwhile),
// then logs that application out and makes the earlier application active
// again, whatever happened.  An application on a device that is not in
// simulation is refused: the run never downloads to a PLC.  Like test.run it
// holds no UI thread: each call takes it for itself and the polling sleeps on
// the caller's thread.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public static class AppTests
    {
        public const string Method = "test.app";
        public const string DefaultApplication = "TestApp";
        public const string Gvl = "TestResult";
        const string StartMarker = "CTS|M|TEST_START|";
        const long DefaultWaitMs = 30000;
        const long PollMs = 100;

        public static Dictionary<string, object> Run(string application, long waitMs, TestPlans.Call call, Action<long> sleep, Func<long> clockMs)
        {
            var start = clockMs();
            var name = string.IsNullOrEmpty(application) ? DefaultApplication : application;
            var found = Find(call("project.devices", new Dictionary<string, object>()), name);
            var guid = Text(found.Application, "guid");
            var answer = new Dictionary<string, object>
            {
                { "application", name },
                { "device", Text(found.Device, "path") },
                { "status", "FAIL" },
            };
            var previous = found.Previous;
            call("app.activate", new Dictionary<string, object> { { "application", guid } });
            try
            {
                answer["application_state"] = Value(call("app.download", new Dictionary<string, object> { { "start", true } }), "application_state");
                var deadline = clockMs() + (waitMs > 0 ? waitMs : DefaultWaitMs);
                var done = false;
                while (true)
                {
                    done = Equals(Read(call, new[] { Gvl + ".Done" })[0], true);
                    if (done || clockMs() >= deadline) break;
                    sleep(PollMs);
                }
                var counts = Read(call, new[] { Gvl + ".Passed", Gvl + ".Failed" });
                var passed = Convert.ToInt64(counts[0], CultureInfo.InvariantCulture);
                var failed = Convert.ToInt64(counts[1], CultureInfo.InvariantCulture);
                answer["done"] = done;
                answer["passed"] = passed;
                answer["failed"] = failed;
                answer["status"] = done && failed == 0 ? "PASS" : "FAIL";
                if (!done) answer["error"] = Gvl + ".Done stayed FALSE for " + (waitMs > 0 ? waitMs : DefaultWaitMs) + " ms: a test that never ends, or a task that does not call the tests";
                RunLog(call, answer);
            }
            finally
            {
                answer["logout"] = Tidy(() => call("app.logout", new Dictionary<string, object> { { "application", guid } }));
                if (previous != null && previous != guid)
                    answer["reactivate"] = Tidy(() => call("app.activate", new Dictionary<string, object> { { "application", previous } }));
                answer["ms"] = clockMs() - start;
            }
            return answer;
        }

        sealed class Found
        {
            public IDictionary<string, object> Device;
            public IDictionary<string, object> Application;
            public string Previous;
        }

        // The application named, on its device, and the active one before the run.
        static Found Find(IDictionary<string, object> devices, string name)
        {
            var pairs = (Value(devices, "devices") as IList<object> ?? new List<object>()).OfType<IDictionary<string, object>>()
                .SelectMany(device => (Value(device, "applications") as IList<object> ?? new List<object>()).OfType<IDictionary<string, object>>()
                    .Select(app => new KeyValuePair<IDictionary<string, object>, IDictionary<string, object>>(device, app)))
                .ToList();
            var named = pairs.Where(p => string.Equals(Text(p.Value, "name"), name, StringComparison.OrdinalIgnoreCase)).ToList();
            if (named.Count == 0)
                throw Bad("No application '" + name + "' in the project: add a device in simulation with an application " + name
                    + " whose task runs the tests (cts guide tests). Applications: "
                    + (pairs.Count == 0 ? "none" : string.Join(", ", pairs.Select(p => Text(p.Key, "path") + "/" + Text(p.Value, "name")))));
            if (named.Count > 1)
                throw Bad("Two applications are named '" + name + "' (" + string.Join(", ", named.Select(p => Text(p.Key, "path")))
                    + "): rename one, or name the other with --app.");
            var found = named[0];
            if (!Equals(Value(found.Key, "simulation"), true))
                throw Bad("Device '" + Text(found.Key, "path") + "' of " + name + " is not in simulation, and cts runs tests only "
                    + "in simulation, never on a PLC: switch it in CODESYS (Online -> Simulation with " + name + " active).");
            return new Found
            {
                Device = found.Key,
                Application = found.Value,
                Previous = pairs.Where(p => Equals(Value(p.Value, "active"), true)).Select(p => Text(p.Value, "guid")).FirstOrDefault(),
            };
        }

        // The simulation's log from the last TEST_START on, as `log`; what kept
        // it from being read, as `log_error`.  A log the run cannot read does
        // not fail the run: the counts already say whether the tests passed.
        static void RunLog(TestPlans.Call call, Dictionary<string, object> answer)
        {
            List<object> entries;
            try { entries = (Value(call("plc.log", new Dictionary<string, object>()), "entries") as IList<object> ?? new List<object>()).ToList(); }
            catch (ProtocolException e)
            {
                answer["log"] = new List<object>();
                answer["log_error"] = "the simulation's log could not be read: " + e.Message;
                return;
            }
            var start = entries.FindLastIndex(entry => Text(entry as IDictionary<string, object>, "info").Contains(StartMarker));
            answer["log"] = start < 0 ? new List<object>() : entries.GetRange(start, entries.Count - start);
            if (start < 0)
                answer["log_error"] = "the log has no " + StartMarker + " record: the tests log nothing to the runtime's log (cts guide tests)";
        }

        // The values of *names*, each one required: a missing one means the
        // application does not follow the TestResult convention.
        static object[] Read(TestPlans.Call call, string[] names)
        {
            var answer = call(Vars.Read, new Dictionary<string, object> { { "names", names.Cast<object>().ToList() } });
            if (!Equals(Value(answer, "logged_in"), true)) throw Bad("The test application is not logged in after its download.");
            var rows = (Value(answer, "results") as IList<object> ?? new List<object>()).OfType<IDictionary<string, object>>().ToList();
            var values = new object[names.Length];
            for (var i = 0; i < names.Length; i++)
            {
                var row = i < rows.Count ? rows[i] : null;
                if (!Equals(Value(row, "ok"), true))
                    throw Bad("read " + names[i] + ": " + (Value(Value(row, "error") as IDictionary<string, object>, "message") ?? "no answer")
                        + ". The test application needs a GVL " + Gvl + " with Done, Passed and Failed (cts guide tests).");
                values[i] = Value(row, "value");
            }
            return values;
        }

        // A step that puts the IDE back: its error is reported, not thrown, so
        // the next one still runs and the result is not lost.
        static object Tidy(Action step)
        {
            try
            {
                step();
                return "ok";
            }
            catch (ProtocolException e)
            {
                return e.Message;
            }
        }

        static ProtocolException Bad(string message)
        {
            return new ProtocolException(ErrorCodes.BadParams, message);
        }
    }
}
