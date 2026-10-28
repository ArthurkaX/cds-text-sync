using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using Cts.Analysis;
using Cts.Trend;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts trace`: a short recording on the PLC, for now. The Trace CtsTrace
    // of the active application records its variables in a task's cycle into
    // the PLC's ring buffer, from cts trace start on (or from a trigger), and
    // cts trace pull reads the buffer while it runs or after it stopped. For a
    // recording to leave overnight there is cts trend.
    internal static class TraceCommand
    {
        const string Name = Agent.TraceRequest.Name;
        // How often pull --wait asks the PLC whether the trace stopped.
        const int WaitPollMs = 500;

        internal static IEnumerable<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "trace", Summary = "Show the PLC trace: its variables, trigger and state",
                Description = "Reads the Trace " + Name + " of the active application: the task whose cycle it records in, every how many "
                    + "cycles, how many samples its buffer holds, its variables and its trigger; and, when the PLC holds it, its state "
                    + "there (Started records, Stopped holds the samples), its trigger's state (WaitForTrigger, TriggerReached) and how "
                    + "many samples it has. cts trace set makes or changes it, cts trace start starts it on the PLC.",
                Execute = Show, Build = Shown,
            },
            new CliCommand
            {
                Name = "trace", Sub = "set", Summary = "Pick what the PLC trace records, and its trigger",
                Description = "Makes the Trace " + Name + " of the active application, or changes it, in the project: it records VAR... "
                    + "(the list replaces the one before; without VAR the list stays and the options change) in the cycle of --task "
                    + "(default: the fastest cyclic task that runs the program), every --every cycles, the last --samples of them "
                    + "(default " + Agent.TraceRequest.DefaultSamples + " for a new trace). With --trigger it records until VAR changes "
                    + "(its --edge, or for a number its crossing of --level) and --post samples after that (default half the buffer), "
                    + "then stops: the samples before and after the moment. --condition records only the cycles the BOOL is TRUE in. "
                    + "A trace is not code: it is made and changed while online, with no download; the PLC keeps the trace it has "
                    + "until cts trace start.",
                Arguments = "[VAR ...]", ArgumentLimit = 255, ArgumentHelp = "Variables as the IEC code names them, e.g. GVL_IO.rLevel PLC_PRG.fbPump.xRun",
                Options = new[]
                {
                    CliOption.Text("--task", "task", "NAME", "The task whose cycle the trace records in"),
                    CliOption.Int("--every", "every", "Record every N cycles of the task (default 1)"),
                    CliOption.Int("--samples", "samples", "How many samples per variable the PLC keeps, the last ones"),
                    CliOption.Text("--trigger", "trigger", "VAR", "Stop the trace --post samples after VAR changes"),
                    CliOption.Choice("--edge", "edge", "The change of the trigger that counts (default rising)", "rising", "falling", "both"),
                    CliOption.Text("--level", "level", "VALUE", "For a number: the trigger is its crossing of VALUE"),
                    CliOption.Int("--post", "post", "Samples recorded after the trigger (default half the buffer)"),
                    CliOption.Switch("--no-trigger", "no_trigger", "Record without a trigger, until cts trace stop"),
                    CliOption.Text("--condition", "condition", "VAR", "Record only the cycles the BOOL VAR is TRUE in"),
                    CliOption.Switch("--no-condition", "no_condition", "Record every cycle again"),
                    CliOption.Text("--workspace", "workspace", "DIR", "The sync folder whose tasks give the default task (default: the one around the current folder)"),
                },
                Execute = Set, Build = Written,
            },
            new CliCommand
            {
                Name = "trace", Sub = "start", Summary = "Start the PLC trace (downloads it, no application download)",
                Description = "Downloads the Trace " + Name + " to the PLC and starts it: the trace the PLC had, and its samples, are "
                    + "replaced. Needs the IDE logged in to the application (cts connect); the application keeps running unchanged. "
                    + "Without a trigger the trace records until cts trace stop, keeping the last samples its buffer holds; with one "
                    + "it waits for it and stops by itself. It keeps recording with the IDE disconnected.",
                Seconds = 60, Execute = Start, Build = Started,
            },
            new CliCommand
            {
                Name = "trace", Sub = "stop", Summary = "Stop the PLC trace; its samples stay",
                Description = "Stops the Trace " + Name + " on the PLC: its samples stay for cts trace pull until the next cts trace start.",
                Execute = Stop, Build = Started,
            },
            new CliCommand
            {
                Name = "trace", Sub = "pull", Summary = "Read the PLC trace's samples into a CSV, with a summary",
                Description = "Reads the samples the PLC's trace holds, while it records or after it stopped, without changing it, "
                    + "into a CSV (a row per sample: its time from the trace's start, in ms, then a column per variable; a BOOL as "
                    + "0 or 1) and answers a line per variable: its first and last value, its range and how often it changed, and "
                    + "when, for one that changed at most " + TraceTable.ListedChanges + " times. --wait waits for the trace to stop "
                    + "first: a trigger reached and its samples after it recorded.",
                Options = new[]
                {
                    CliOption.Text("--csv", "csv", "FILE", "The CSV to write (default: this PC's trace folder, the same file each pull)"),
                    CliOption.Int("--wait", "wait", "Wait at most N seconds for the trace to stop first"),
                },
                Seconds = 60, Execute = Pull, Build = Pulled,
            },
        };

        static IDictionary<string, object> Show(CliCall call) => call.Call("trace.read", null);

        static IDictionary<string, object> Set(CliCall call)
        {
            var options = call.Options;
            var parameters = new Dictionary<string, object>();
            if (options.Arguments.Count > 0) parameters["variables"] = options.Arguments.Select(name => (object)name.Trim()).ToList();
            foreach (var key in new[] { "task", "trigger", "edge", "level" })
                if (options.Text(key) != null) parameters[key] = options.Text(key);
            foreach (var key in new[] { "every", "samples", "post" })
                if (options.Text(key) != null) parameters[key] = (long)options.Number(key, 0);
            if (options.Params.ContainsKey("no_trigger")) parameters["no_trigger"] = true;
            if (options.Text("condition") != null && options.Params.ContainsKey("no_condition")) throw Usage("a condition and no condition: give one of them");
            if (options.Text("condition") != null) parameters["condition"] = options.Text("condition");
            if (options.Params.ContainsKey("no_condition")) parameters["condition"] = "";
            if (!parameters.ContainsKey("task"))
            {
                var trace = call.Call("trace.read", null);
                if (!Equals(Value(trace, "exists"), true) || string.IsNullOrEmpty(Value(trace, "task") as string))
                    parameters["task"] = FastestTask(options, call.Hello.SyncFolder ?? Environment.CurrentDirectory, Value(trace, "application") as string);
            }
            return call.Call("trace.set", parameters);
        }

        // The fastest cyclic task that runs the program, as the sync folder
        // holds the application's tasks.
        static string FastestTask(CliOptions options, string work, string application)
        {
            string problem = null;
            try
            {
                var workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work);
                var files = application == null ? null : TrendFiles.Of(workspace.View, application, out problem);
                if (files == null) problem = problem ?? "no active application";
                else
                {
                    var fastest = files.Tasks.Where(task => task.RunsProgram).OrderBy(task => task.IntervalMs).FirstOrDefault();
                    if (fastest != null) return fastest.Name;
                    problem = "the application " + application + " has no cyclic task that runs the program";
                }
            }
            catch (AnalyzeException error) { problem = error.Message; }
            throw Usage("name the task with --task (" + problem + ")");
        }

        static IDictionary<string, object> Start(CliCall call) => call.Call("trace.start", null);

        static IDictionary<string, object> Stop(CliCall call) => call.Call("trace.stop", null);

        static IDictionary<string, object> Pull(CliCall call)
        {
            var wait = call.Options.Text("wait") == null ? 0 : call.Options.Number("wait", 0);
            if (wait < 0) throw new CliFailure("trace-pull", "usage", "--wait takes 0 or more seconds", "cts trace pull --help", 2);
            var watch = Stopwatch.StartNew();
            var waited = false;
            while (wait > 0)
            {
                var state = call.Call("trace.read", null, 15);
                if (!Equals(Value(state, "state"), "Started")) break;
                if (watch.Elapsed.TotalSeconds >= wait) { waited = true; break; }
                Thread.Sleep(WaitPollMs);
            }
            var answer = call.Call("trace.samples", null);
            var table = TraceTable.Of(answer);
            var output = call.Options.Text("csv") ?? DefaultOutput(call.Hello.SyncFolder, Value(answer, "packet") as string);
            table.Write(output);
            var data = new Dictionary<string, object>
            {
                ["samples"] = (long)table.Times.Count, ["span_" + table.Unit] = table.Span, ["state"] = Value(answer, "state"),
                ["trigger_state"] = Value(answer, "trigger_state"), ["csv"] = Path.GetFullPath(output),
                ["variables"] = table.Summary().Cast<object>().ToList(),
            };
            // The trigger's moment on the samples' clock: from the trace's start.
            if (Value(answer, "trigger_at") is long at && Value(answer, "start") is long start && at >= start)
                data["trigger_" + table.Unit] = at - start;
            if (waited) data["still_recording"] = true;
            return data;
        }

        // This PC's trace folder: the same file each pull of a project's trace.
        static string DefaultOutput(string root, string packet) =>
            Path.Combine(TrendData.LocalFolder(root ?? Environment.CurrentDirectory, "trace"), (packet ?? Name) + ".csv");

        static Answer Shown(IDictionary<string, object> data)
        {
            if (!Equals(data["exists"], true))
                return new Answer().Add("application", Value(data, "application")).Add("trace", "none").Detail("Next: cts trace set VAR ... picks the variables to record");
            var answer = Settings(new Answer().Add("application", data["application"]), data);
            if (data.TryGetValue("plc_error", out var error)) return answer.Detail("PLC: " + error);
            if (!Equals(Value(data, "on_plc"), true)) return answer.Detail("the PLC has no " + Name + ": cts trace start downloads and starts it");
            answer.Add("state", data["state"]).Add("trigger_state", data["trigger_state"]).Add("count", data["count"]);
            return answer;
        }

        static Answer Written(IDictionary<string, object> data)
        {
            var answer = Settings(new Answer().Add("application", data["application"]).Add("created", data["created"]), data);
            return answer.Detail("Next: cts trace start (the PLC keeps its trace until then)");
        }

        static Answer Settings(Answer answer, IDictionary<string, object> data)
        {
            answer.Add("task", data["task"]).Add("every", data["every"]).Add("samples", data["samples"]);
            foreach (var name in (IList<object>)data["variables"]) answer.Detail(name);
            if (data.TryGetValue("trigger", out var trigger))
                answer.Detail("trigger " + trigger + " " + data["edge"] + (data.TryGetValue("level", out var level) ? " level " + level : "") + ", " + data["post"] + " samples after it");
            if (data.TryGetValue("condition", out var condition)) answer.Detail("records while " + condition + " is TRUE");
            return answer;
        }

        static Answer Started(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("state", data["state"]).Add("trigger_state", data["trigger_state"]);
            if (data.ContainsKey("count")) answer.Add("count", data["count"]);
            if (Equals(data["state"], "Started"))
                answer.Detail(Equals(data["trigger_state"], "Disabled")
                    ? "recording: cts trace pull reads the samples while it records"
                    : "waiting for the trigger: cts trace pull --wait N reads the samples once the trace stopped after it");
            return answer;
        }

        static Answer Pulled(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("samples", data["samples"]);
            foreach (var key in new[] { "span_ms", "span_us", "trigger_ms", "trigger_us" })
                if (data.ContainsKey(key)) answer.Add(key, data[key]);
            answer.Add("state", data["state"]).Add("trigger_state", data["trigger_state"]);
            if (data.ContainsKey("still_recording")) answer.Detail("the trace still records after --wait: these are its samples so far");
            foreach (var line in (IList<object>)data["variables"]) answer.Detail(line);
            return answer.Detail("csv " + data["csv"]);
        }

        static CliFailure Usage(string message) => new CliFailure("trace-set", "usage", message, "cts trace set --help", 2);
    }
}
