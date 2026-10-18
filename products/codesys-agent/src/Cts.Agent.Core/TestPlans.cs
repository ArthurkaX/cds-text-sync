// `test.run {folder, file?}` (`cts verify --with-test`): the JSON test plans of
// <folder>/.test -- one file, or every *.json there in name order -- run against
// the PLC through the agent's own methods, one call per step:
//
//   app.login {ip?, gateway?}   the plan's PLC, logged in without changing it
//   app.reset {kind: "cold"}    once per run, for the first plan with "reset": "cold"
//   app.start                   unless the plan says "start": false
//   vars.write / vars.read      the write, read and assert steps
//
// The runner holds no UI thread: each call takes the UI thread for itself, and
// a `wait` step sleeps on the caller's thread, so the IDE stays usable while a
// plan waits.  A plan runs against the active application; one naming another
// is refused, not switched to.  Plan and test `timeout` are milliseconds.
//
// The answer keeps the shape `cts verify` reads: `status` SUCCESS or FAIL, a
// `summary` of tests ok / not ok, one `files` row per plan and the per-step
// `results`.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Agent
{
    public static class TestPlans
    {
        public const string Method = "test.run";
        public const string Folder = ".test";
        const long DefaultPlanTimeoutMs = 60000;
        const long DefaultWaitMs = 100;
        const string NotConnected = "Not connected: the PLC session is not logged in.";

        public delegate IDictionary<string, object> Call(string method, Dictionary<string, object> parameters);

        public static Dictionary<string, object> Run(string folder, string file, Call call, Action<long> sleep, Func<long> clockMs)
        {
            if (string.IsNullOrEmpty(folder)) throw new ProtocolException(ErrorCodes.BadParams, "test.run needs folder=<sync folder>");
            var run = new PlanRun(call, sleep, clockMs);
            return Summary(PlanFiles(folder, file).Select(path => run.File(path)).ToList());
        }

        static List<string> PlanFiles(string folder, string file)
        {
            var dir = Path.Combine(folder, Folder);
            if (!Path.IsPathRooted(file ?? "") && !Directory.Exists(dir))
                throw new ProtocolException(ErrorCodes.BadParams, "No " + Folder + " folder in " + folder
                    + ": put the JSON test plans there (cts guide tests).");
            if (!string.IsNullOrEmpty(file))
            {
                var path = Path.IsPathRooted(file) ? file : Path.Combine(dir, file);
                if (!File.Exists(path)) throw new ProtocolException(ErrorCodes.BadParams, "Test plan not found: " + path);
                return new List<string> { path };
            }
            var all = Directory.GetFiles(dir, "*.json").OrderBy(p => Path.GetFileName(p), StringComparer.Ordinal).ToList();
            if (all.Count == 0) throw new ProtocolException(ErrorCodes.BadParams, "No JSON test plans in " + dir);
            return all;
        }

        sealed class PlanRun
        {
            readonly Call _call;
            readonly Action<long> _sleep;
            readonly Func<long> _clock;
            bool _reset;

            public PlanRun(Call call, Action<long> sleep, Func<long> clock)
            {
                _call = call;
                _sleep = sleep;
                _clock = clock;
            }

            public Dictionary<string, object> File(string path)
            {
                var start = _clock();
                var result = new Dictionary<string, object> { { "file", Path.GetFileName(path) }, { "plan", "" }, { "status", "FAIL" } };
                try
                {
                    var plan = Json.Parse(System.IO.File.ReadAllText(path)) as IDictionary<string, object>
                        ?? throw new ProtocolException(ErrorCodes.BadParams, "the plan is not a JSON object");
                    Plan(plan, result, start);
                }
                catch (Exception e) when (e is ProtocolException || e is JsonException || e is IOException)
                {
                    result["status"] = "FAIL";
                    result["error"] = e.Message;
                }
                result["total_ms"] = _clock() - start;
                return result;
            }

            void Plan(IDictionary<string, object> plan, Dictionary<string, object> result, long start)
            {
                result["plan"] = Text(plan, "name", "unnamed");
                var application = Text(plan, "application", "").Trim();
                result["application"] = application;
                var tests = (Value(plan, "tests") as IList<object> ?? new List<object>()).OfType<IDictionary<string, object>>().ToList();
                if (tests.Count == 0) throw new ProtocolException(ErrorCodes.BadParams, "Test plan contains no tests");
                if (application.Length == 0)
                    throw new ProtocolException(ErrorCodes.BadParams, "Test plan must name its application: {\"application\": \"Application\"}");
                result["prepare"] = Prepare(plan, application);

                var deadline = start + (long)Number(plan, "timeout", DefaultPlanTimeoutMs);
                var keepGoing = Value(plan, "continue_on_fail") as bool? ?? false;
                var reports = new List<object>();
                result["tests"] = reports;
                foreach (var test in tests)
                {
                    var report = Test(test, deadline);
                    reports.Add(report);
                    if (Equals(report["status"], "FAIL") && (!keepGoing || _clock() >= deadline)) break;
                }
                result["status"] = reports.Any(r => Equals(((IDictionary<string, object>)r)["status"], "FAIL")) ? "FAIL" : "PASS";
            }

            Dictionary<string, object> Prepare(IDictionary<string, object> plan, string application)
            {
                var login = new Dictionary<string, object>();
                var ip = Text(plan, "ip", "").Trim();
                var gateway = Text(plan, "gateway", "").Trim();
                if (ip.Length > 0) login["ip"] = ip;
                if (gateway.Length > 0) login["gateway"] = gateway;
                var session = _call("app.login", login);
                var active = Convert.ToString(Value(session, "application"), CultureInfo.InvariantCulture) ?? "";
                if (active != application)
                    throw new ProtocolException(ErrorCodes.BadParams, "The plan tests application '" + application + "', but the active application is '"
                        + active + "': make '" + application + "' the active application in the IDE.");
                var state = Value(session, "state");
                var reset = Text(plan, "reset", "");
                if (reset.Length > 0 && reset != "cold") throw new ProtocolException(ErrorCodes.BadParams, "\"reset\" takes \"cold\" only, not \"" + reset + "\"");
                if (reset == "cold" && !_reset)
                {
                    state = Value(_call("app.reset", new Dictionary<string, object> { { "kind", "cold" } }), "application_state");
                    _reset = true;
                }
                if (Value(plan, "start") as bool? ?? true) state = Value(_call("app.start", new Dictionary<string, object>()), "application_state");
                return new Dictionary<string, object> { { "application", application }, { "state", state } };
            }

            Dictionary<string, object> Test(IDictionary<string, object> test, long planDeadline)
            {
                var start = _clock();
                var deadline = test.ContainsKey("timeout") ? Math.Min(planDeadline, start + (long)Number(test, "timeout", 0)) : planDeadline;
                var keepGoing = Value(test, "continue_on_fail") as bool? ?? false;
                var steps = new List<object>();
                var report = new Dictionary<string, object> { { "name", Text(test, "name", "unnamed") }, { "status", "PASS" }, { "steps", steps } };
                foreach (var step in (Value(test, "steps") as IList<object> ?? new List<object>()))
                {
                    var stepStart = _clock();
                    var action = Text(step as IDictionary<string, object>, "action", "");
                    var row = new Dictionary<string, object> { { "action", action }, { "status", "PASS" } };
                    try
                    {
                        if (stepStart >= deadline)
                            throw new ProtocolException(ErrorCodes.Timeout, (deadline == planDeadline ? "plan" : "test") + " timeout exceeded");
                        Step(step as IDictionary<string, object> ?? new Dictionary<string, object>(), action, row, deadline);
                    }
                    catch (ProtocolException e)
                    {
                        row["status"] = "FAIL";
                        row["error"] = e.Message;
                        report["status"] = "FAIL";
                        if (!report.ContainsKey("error")) report["error"] = e.Message;
                    }
                    row["ms"] = _clock() - stepStart;
                    steps.Add(row);
                    if (Equals(row["status"], "FAIL") && (!keepGoing || _clock() >= deadline)) break;
                }
                report["ms"] = _clock() - start;
                return report;
            }

            void Step(IDictionary<string, object> step, string action, Dictionary<string, object> row, long deadline)
            {
                switch (action)
                {
                    case "wait":
                        _sleep(Math.Max(0, Math.Min((long)Number(step, "ms", DefaultWaitMs), deadline - _clock())));
                        return;
                    case "write":
                        Write(Variable(step, action), Value(step, "value") ?? throw Bad("write: a value is required"));
                        return;
                    case "read":
                    case "assert":
                        var name = Variable(step, action);
                        var read = Read(name);
                        row["value"] = read.Value;
                        if (read.Text != null) row["text"] = read.Text;
                        Expect(step, action + " " + name, read);
                        return;
                }
                throw Bad("Unknown action: '" + action + "' (write, wait, read, assert)");
            }

            void Write(string name, object value)
            {
                var answer = _call(Vars.Write, new Dictionary<string, object> { { "values", new Dictionary<string, object> { { name, Literal(value) } } } });
                if (!Equals(Value(answer, "logged_in"), true)) throw Bad(NotConnected);
                var row = (Value(answer, "results") as IList<object>)?.FirstOrDefault() as IDictionary<string, object>;
                if (!Equals(Value(row, "ok"), true)) throw Bad("write " + name + ": " + ErrorOf(row));
            }

            Reading Read(string name)
            {
                var answer = _call(Vars.Read, new Dictionary<string, object> { { "names", new List<object> { name } } });
                if (!Equals(Value(answer, "logged_in"), true)) throw Bad(NotConnected);
                var row = (Value(answer, "results") as IList<object>)?.FirstOrDefault() as IDictionary<string, object>;
                if (!Equals(Value(row, "ok"), true)) throw Bad("read " + name + ": " + ErrorOf(row));
                return new Reading(Value(row, "value"), Value(row, "text") as string);
            }
        }

        sealed class Reading
        {
            public readonly object Value;
            public readonly string Text;

            public Reading(object value, string text)
            {
                Value = value;
                Text = text;
            }
        }

        // `expected` (numbers within `tolerance`), `expected_min`, `expected_max`.
        static void Expect(IDictionary<string, object> step, string what, Reading read)
        {
            var got = read.Text ?? Convert.ToString(read.Value, CultureInfo.InvariantCulture);
            var expected = Value(step, "expected");
            double actual;
            var numeric = AsNumber(read.Value, out actual);
            if (expected != null)
            {
                double wanted;
                if (AsNumber(expected, out wanted) && numeric)
                {
                    var tolerance = Number(step, "tolerance", 0);
                    if (Math.Abs(actual - wanted) > tolerance)
                        throw Bad(what + ": expected " + Show(expected) + (tolerance > 0 ? " +-" + Show(Value(step, "tolerance")) : "") + ", got " + got);
                }
                else if (!Same(expected, read)) throw Bad(what + ": expected " + Show(expected) + ", got " + got);
            }
            foreach (var bound in new[] { "expected_min", "expected_max" })
            {
                var limit = Value(step, bound);
                if (limit == null) continue;
                double edge;
                if (!AsNumber(limit, out edge)) throw Bad(what + ": " + bound + " must be a number");
                if (!numeric) throw Bad(what + ": " + got + " is not a number to compare with " + bound);
                if (bound == "expected_min" ? actual < edge : actual > edge)
                    throw Bad(what + ": " + (bound == "expected_min" ? "min " : "max ") + Show(limit) + ", got " + got);
            }
        }

        // A bool against a bool; anything else as text, ignoring case, against
        // the value or the IDE's spelling of it ("E_Mode.Run", "'text'").
        static bool Same(object expected, Reading read)
        {
            if (expected is bool || read.Value is bool) return Equals(expected, read.Value);
            var text = Convert.ToString(expected, CultureInfo.InvariantCulture);
            return string.Equals(text, Convert.ToString(read.Value, CultureInfo.InvariantCulture), StringComparison.OrdinalIgnoreCase)
                || string.Equals(text, read.Text, StringComparison.OrdinalIgnoreCase);
        }

        // What vars.write gets: the IDE's literal parser reads text for the
        // variable's type, so a JSON value goes as its IEC spelling.
        static string Literal(object value)
        {
            if (value is bool) return (bool)value ? "TRUE" : "FALSE";
            return Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        static string Show(object value)
        {
            return value is bool ? ((bool)value ? "true" : "false") : Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        static string Variable(IDictionary<string, object> step, string action)
        {
            var name = Text(step, "variable", "");
            if (name.Length == 0) throw Bad(action + ": variable name is required");
            return name;
        }

        static string ErrorOf(IDictionary<string, object> row)
        {
            return Convert.ToString(Value(Value(row, "error") as IDictionary<string, object>, "message"), CultureInfo.InvariantCulture) ?? "no answer";
        }

        static bool AsNumber(object value, out double number)
        {
            number = 0;
            if (!(value is long || value is double || value is int || value is float)) return false;
            number = Convert.ToDouble(value, CultureInfo.InvariantCulture);
            return true;
        }

        static double Number(IDictionary<string, object> map, string key, double fallback)
        {
            double number;
            return AsNumber(Value(map, key), out number) ? number : fallback;
        }

        static string Text(IDictionary<string, object> map, string key, string fallback)
        {
            return Value(map, key) as string ?? fallback;
        }

        static ProtocolException Bad(string message)
        {
            return new ProtocolException(ErrorCodes.BadParams, message);
        }

        static Dictionary<string, object> Summary(List<Dictionary<string, object>> results)
        {
            long ok = 0, failed = 0;
            var files = new List<object>();
            foreach (var result in results)
            {
                var tests = (Value(result, "tests") as IList<object> ?? new List<object>()).Cast<IDictionary<string, object>>().ToList();
                var passed = tests.Count(t => Equals(t["status"], "PASS"));
                var bad = tests.Count - passed;
                var pass = Equals(result["status"], "PASS");
                if (tests.Count > 0) { ok += passed; failed += bad; }
                else if (pass) ok++;
                else failed++;
                var row = new Dictionary<string, object>
                {
                    { "file", result["file"] }, { "plan", result["plan"] }, { "status", pass ? "SUCCESS" : "FAIL" }, { "ok", pass },
                    { "tests_ok", (long)passed }, { "tests_failed", (long)bad }, { "total_ms", result["total_ms"] },
                };
                if (result.ContainsKey("error")) row["error"] = result["error"];
                files.Add(row);
            }
            return new Dictionary<string, object>
            {
                { "status", failed == 0 ? "SUCCESS" : "FAIL" },
                { "ok", failed == 0 },
                { "summary", new Dictionary<string, object> { { "ok", ok }, { "not_ok", failed }, { "total", ok + failed }, { "files", (long)results.Count } } },
                { "files", files },
                { "results", results.Cast<object>().ToList() },
            };
        }
    }
}
