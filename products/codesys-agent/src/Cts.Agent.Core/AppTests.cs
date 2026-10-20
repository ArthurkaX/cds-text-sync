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
// simulation is refused unless `plc` says the tests may go to that PLC.
// `repeat` runs them again that many times in all: a warm reset and a start
// when the deny list allows the reset, else another download.  Like test.run
// it holds no UI thread: each call takes it for itself and the polling sleeps
// on the caller's thread.
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
        const string PassMarker = "CTS|M|TEST_PASS|";
        const string FailMarker = "CTS|M|TEST_FAIL|";
        //: How long a run's records may take to reach the log after
        //: TestResult.Done.
        const long LogWaitMs = 5000;
        const long DefaultWaitMs = 30000;
        const long PollMs = 100;

        // What `test.app` was asked for.
        public sealed class Request
        {
            public string Application = "";
            public long WaitMs;
            public bool Plc;
            public int Repeat = 1;
            public bool ResetAllowed;
        }

        public static Dictionary<string, object> Run(Request request, TestPlans.Call call, Action<long> sleep, Func<long> clockMs)
        {
            var start = clockMs();
            var name = string.IsNullOrEmpty(request.Application) ? DefaultApplication : request.Application;
            var found = Find(call("project.devices", new Dictionary<string, object>()), name, request.Plc);
            var guid = Text(found.Application, "guid");
            var answer = new Dictionary<string, object>
            {
                { "application", name },
                { "device", Text(found.Device, "path") },
                { "status", "FAIL" },
            };
            if (!Equals(Value(found.Device, "simulation"), true)) answer["plc"] = true;
            var previous = found.Previous;
            call("app.activate", new Dictionary<string, object> { { "application", guid } });
            try
            {
                var runs = new List<object>();
                var lastStart = Equals(Value(found.Device, "simulation"), true) ? null : PriorStart(call);
                for (var number = 1; number <= Math.Max(1, request.Repeat); number++)
                {
                    if (number == 1 || !request.ResetAllowed)
                        answer["application_state"] = Value(call("app.download", new Dictionary<string, object> { { "start", true } }), "application_state");
                    else
                    {
                        call("app.reset", new Dictionary<string, object> { { "kind", "warm" } });
                        answer["application_state"] = Value(call("app.start", new Dictionary<string, object>()), "application_state");
                    }
                    var run = Once(call, sleep, clockMs, request.WaitMs > 0 ? request.WaitMs : DefaultWaitMs, ref lastStart);
                    run["run"] = (long)number;
                    runs.Add(run);
                }
                var last = (Dictionary<string, object>)runs[runs.Count - 1];
                foreach (var key in new[] { "done", "passed", "failed", "error", "log", "log_error", "runtime_notices" })
                    if (last.ContainsKey(key)) answer[key] = last[key];
                answer["status"] = runs.All(run => Equals(((IDictionary<string, object>)run)["status"], "PASS")) ? "PASS" : "FAIL";
                if (runs.Count > 1)
                {
                    // The counts of all the runs: each run's are in its own entry.
                    foreach (var key in new[] { "passed", "failed" })
                        answer[key] = runs.Sum(run => Convert.ToInt64(Value((IDictionary<string, object>)run, key) ?? 0L, CultureInfo.InvariantCulture));
                    answer["runs"] = runs;
                    answer["restart"] = request.ResetAllowed ? "reset" : "download";
                }
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

        // One run after the start: TestResult.Done awaited, the counts and the run's log.
        static Dictionary<string, object> Once(TestPlans.Call call, Action<long> sleep, Func<long> clockMs, long waitMs, ref string lastStart)
        {
            var deadline = clockMs() + waitMs;
            var done = false;
            while (true)
            {
                done = Equals(Read(call, new[] { Gvl + ".Done" })[0], true);
                if (done || clockMs() >= deadline) break;
                sleep(PollMs);
            }
            var counts = Read(call, new[] { Gvl + ".Passed", Gvl + ".Failed" });
            var failed = Convert.ToInt64(counts[1], CultureInfo.InvariantCulture);
            var run = new Dictionary<string, object>
            {
                { "done", done },
                { "passed", Convert.ToInt64(counts[0], CultureInfo.InvariantCulture) },
                { "failed", failed },
                { "status", done && failed == 0 ? "PASS" : "FAIL" },
            };
            if (!done) run["error"] = Gvl + ".Done stayed FALSE for " + waitMs + " ms: a test that never ends, or a task that does not call the tests";
            lastStart = RunLog(call, sleep, clockMs, run, lastStart, (long)run["passed"] + failed);
            return run;
        }

        sealed class Found
        {
            public IDictionary<string, object> Device;
            public IDictionary<string, object> Application;
            public string Previous;
        }

        // The application named, on its device, and the active one before the run.
        static Found Find(IDictionary<string, object> devices, string name, bool plc)
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
            if (!plc && !Equals(Value(found.Key, "simulation"), true))
                throw Bad("Device '" + Text(found.Key, "path") + "' of " + name + " is not in simulation, and cts runs tests "
                    + "in simulation unless told otherwise: switch it in CODESYS (Online -> Simulation with " + name + " active), "
                    + "or run cts test --plc to download " + name + " to that PLC and run the tests there.");
            return new Found
            {
                Device = found.Key,
                Application = found.Value,
                Previous = pairs.Where(p => Equals(Value(p.Value, "active"), true)).Select(p => Text(p.Value, "guid")).FirstOrDefault(),
            };
        }

        // The runtime's log from the last TEST_START on, as `log`; what kept
        // it from being read, as `log_error`.  A log the run cannot read does
        // not fail the run: the counts already say whether the tests passed.
        // The records reach the log the logger service reads after
        // TestResult.Done, so the log is read again until it holds a
        // TEST_START other than *previousStart* (the one the run before read)
        // with as many results as the counts, or LogWaitMs ran out.  Only
        // *previousStart* then means the tests did not run and the counts are
        // stale: the run fails.  Returns the TEST_START read, for the next run.
        static string RunLog(TestPlans.Call call, Action<long> sleep, Func<long> clockMs, Dictionary<string, object> answer, string previousStart, long expected)
        {
            var deadline = clockMs() + LogWaitMs;
            List<object> entries;
            int start;
            while (true)
            {
                try { entries = Entries(call); }
                catch (ProtocolException e)
                {
                    answer["log"] = new List<object>();
                    answer["log_error"] = "the runtime's log could not be read: " + e.Message;
                    return previousStart;
                }
                start = entries.FindLastIndex(entry => Info(entry).Contains(StartMarker));
                if (start >= 0 && StartKey(entries[start]) != previousStart && Results(entries, start) >= expected || clockMs() >= deadline) break;
                sleep(PollMs);
            }
            if (start < 0 || StartKey(entries[start]) == previousStart)
            {
                answer["log"] = new List<object>();
                if (start < 0)
                    answer["log_error"] = "the log has no " + StartMarker + " record: the tests log nothing to the runtime's log (cts guide tests)";
                else
                {
                    answer["status"] = "FAIL";
                    answer["error"] = "the tests did not run: " + LogWaitMs / 1000 + " s after " + Gvl + ".Done the log shows no "
                        + StartMarker + " record of this run, only an earlier run's, and the counts are that run's";
                }
                return previousStart;
            }
            // A record with no time (year 1) is the runtime's own notice, a log
            // buffer overflow: not the run's, it is named apart.
            var range = entries.GetRange(start, entries.Count - start);
            answer["log"] = range.Where(entry => !Timeless(entry)).ToList();
            var notices = range.Where(Timeless).Select(Info).ToList();
            if (notices.Count > 0) answer["runtime_notices"] = notices;
            var results = Results(entries, start);
            if (results < expected)
                answer["log_error"] = "the log holds " + results + " of the " + expected + " results the counts name " + LogWaitMs / 1000 + " s after " + Gvl + ".Done";
            return StartKey(entries[start]);
        }

        // The last TEST_START a PLC's log holds before the run: a real
        // runtime keeps the records of earlier runs.
        static string PriorStart(TestPlans.Call call)
        {
            try
            {
                var entries = Entries(call);
                var start = entries.FindLastIndex(entry => Info(entry).Contains(StartMarker));
                return start < 0 ? null : StartKey(entries[start]);
            }
            catch (ProtocolException) { return null; }
        }

        static List<object> Entries(TestPlans.Call call) => (Value(call("plc.log", new Dictionary<string, object>()), "entries") as IList<object> ?? new List<object>()).ToList();

        static string Info(object entry) => Text(entry as IDictionary<string, object>, "info");

        static bool Timeless(object entry) => Text(entry as IDictionary<string, object>, "time").StartsWith("0001-01-01", StringComparison.Ordinal);

        static string StartKey(object entry) => Text(entry as IDictionary<string, object>, "time") + " " + Info(entry);

        static int Results(List<object> entries, int start) => entries.Skip(start).Count(entry => Info(entry).Contains(PassMarker) || Info(entry).Contains(FailMarker));

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
