using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using Cts.Analysis;
using Cts.Trend;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts trend`: a recording on the PLC for commissioning. The variables an
    // agent picks go into the Trend Recording CtsTrend of the sync folder;
    // the PLC writes them to an SQLite file in a task's cycle while
    // GVL_CtsTrend.xRecord is TRUE, which cts trend on and off write.
    internal static class TrendCommand
    {
        const string Next = "cts import, cts build, then cts download --online-change";

        static readonly CliOption[] Where =
        {
            CliOption.Text("--workspace", "workspace", "DIR", "The sync folder (default: the one around the current folder)"),
            CliOption.Text("--app", "app", "NAME", "The application (its folder's name); default: the one with the trend, else the only one besides cts test's TestApp"),
        };

        internal static IEnumerable<CliCommand> Commands => new[]
        {
            new CliCommand
            {
                Name = "trend", Summary = "Show what the PLC trend records (offline)",
                Description = "Reads the Trend Recording " + TrendFiles.Name + " of the sync folder: the task whose cycle it records in, "
                    + "every how many cycles, its slots and the variables in them, and the size its file may grow to. "
                    + "cts trend set makes or changes it; cts trend on and off start and stop the recording on the PLC.",
                Options = Where, LocalExecute = Show, Build = Shown,
            },
            new CliCommand
            {
                Name = "trend", Sub = "set", Summary = "Pick the variables the PLC trend records, on disk",
                Description = "Writes the Trend Recording " + TrendFiles.Name + " to record VAR... (the list replaces the one before; without "
                    + "VAR the list stays and the options change), in the cycle of --task (default: the fastest cyclic task that runs the "
                    + "program), every --every cycles. The first time it also writes the Trend Recording Manager with its task, "
                    + TrendFiles.Gvl + " and the VisuTrendStorageAccess library reference. The recording has a fixed number of --slots "
                    + "(default " + TrendFiles.DefaultSlots + "); a free slot records " + TrendFiles.Gate + ". New variables in the same "
                    + "slots go to the PLC as an online change; a new slot count, a new GVL or the first trend need a full download. "
                    + "The recording is off after a download: cts trend on starts it. A STRING is not recorded.",
                Arguments = "[VAR ...]", ArgumentLimit = 255, ArgumentHelp = "Variables as the IEC code names them, e.g. GVL_IO.rLevel PLC_PRG.fbPump.xRun",
                Options = Where.Concat(new[]
                {
                    CliOption.Text("--task", "task", "NAME", "The task whose cycle the trend records in"),
                    CliOption.Int("--every", "every", "Record every N cycles of the task (default 1)"),
                    CliOption.Int("--slots", "slots", "How many variables the recording holds (default " + TrendFiles.DefaultSlots + ")"),
                    CliOption.Int("--limit-mb", "limit_mb", "The size the PLC's file may grow to (default " + TrendFiles.DefaultLimitMb + ")"),
                }).ToArray(),
                LocalExecute = Set, Build = Written,
            },
            Switch("on", true, "Start the PLC trend recording", "Writes TRUE to " + TrendFiles.Gate + " in the online application: the PLC "
                + "records the trend's variables from the next cycle on, until cts trend off, a download or a restart."),
            Switch("off", false, "Stop the PLC trend recording", "Writes FALSE to " + TrendFiles.Gate + " in the online application: the "
                + "PLC stops adding rows; its file keeps the ones recorded."),
        };

        static CliCommand Switch(string sub, bool on, string summary, string description) => new CliCommand
        {
            Name = "trend", Sub = sub, Summary = summary, Description = description,
            Execute = call => Record(call, on), Build = Recorded,
        };

        static TrendFiles Trend(CliOptions options, string work, string verb)
        {
            AnalyzeWorkspace workspace;
            try { workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work); }
            catch (AnalyzeException error) { throw new CliFailure(verb, "refused", error.Message, "cts " + verb.Replace('-', ' ') + " --help", 2); }
            var trend = TrendFiles.Of(workspace.View, options.Text("app"), out var problem);
            if (trend == null) throw new CliFailure(verb, "no application", problem, "cts " + verb.Replace('-', ' ') + " --help", 1);
            return trend;
        }

        static IDictionary<string, object> Show(CliOptions options, IAgentHost host, string work)
        {
            var trend = Trend(options, work, "trend");
            var settings = trend.Settings();
            var data = new Dictionary<string, object> { ["app"] = trend.App, ["trend"] = settings != null };
            if (settings != null) Describe(data, trend, settings);
            return data;
        }

        static IDictionary<string, object> Set(CliOptions options, IAgentHost host, string work)
        {
            var trend = Trend(options, work, "trend-set");
            var settings = trend.Settings() ?? new TrendSettings();
            var before = settings.Slots;
            if (options.Arguments.Count > 0)
            {
                var names = options.Arguments.Select(name => name.Trim()).ToList();
                var bad = names.FirstOrDefault(name => name.Length == 0 || name.Any(char.IsWhiteSpace) || !name.Contains("."));
                if (bad != null) throw Usage("'" + bad + "' is no variable: name it with its POU or GVL, e.g. GVL_IO.rLevel");
                settings.Variables = names;
            }
            var task = options.Text("task");
            if (task != null)
            {
                var named = trend.Tasks.FirstOrDefault(item => item.Name.Equals(task, StringComparison.OrdinalIgnoreCase));
                if (named == null) throw new CliFailure("trend-set", "no such task", "the application " + trend.App + " has no task " + task
                    + "; its tasks: " + string.Join(", ", trend.Tasks.Select(item => item.Name)), "cts trend set --help", 1);
                settings.Task = named.Name;
            }
            else if (string.IsNullOrEmpty(settings.Task))
            {
                var fastest = trend.Tasks.Where(item => item.RunsProgram).OrderBy(item => item.IntervalMs).FirstOrDefault();
                if (fastest == null) throw new CliFailure("trend-set", "no task", "the application " + trend.App
                    + " has no cyclic task that runs the program: name the task with --task", "cts trend set --help", 1);
                settings.Task = fastest.Name;
            }
            settings.Every = Positive(options, "every", settings.Every, int.MaxValue);
            settings.Slots = Positive(options, "slots", settings.Slots, byte.MaxValue);
            settings.LimitMb = Positive(options, "limit_mb", settings.LimitMb, int.MaxValue);
            if (settings.Variables.Count == 0) throw Usage("name the variables to record: cts trend set VAR ...");
            if (settings.Variables.Count > settings.Slots)
                throw Usage(settings.Variables.Count + " variables need as many slots: --slots " + settings.Variables.Count + " (a new count needs a full download)");
            var fresh = trend.RecordingFile == null;
            List<string> written;
            try { written = trend.Write(settings); }
            catch (Exception error) when (error is InvalidOperationException || error is InvalidDataException)
            {
                throw new CliFailure("trend-set", "refused", error.Message, "cts trend", 1);
            }
            var data = new Dictionary<string, object> { ["app"] = trend.App, ["changed"] = written.Cast<object>().ToList() };
            Describe(data, trend, settings);
            if (written.Count > 0)
                data["next"] = Next + (fresh || settings.Slots != before ? " (it asks a full download: cts download)" : "") + ", then cts trend on";
            return data;
        }

        static void Describe(IDictionary<string, object> data, TrendFiles trend, TrendSettings settings)
        {
            var task = trend.Tasks.FirstOrDefault(item => item.Name.Equals(settings.Task, StringComparison.OrdinalIgnoreCase));
            data["task"] = settings.Task;
            if (task != null && task.IntervalMs > 0) data["interval_ms"] = task.IntervalMs * settings.Every;
            data["every"] = (long)settings.Every;
            data["slots"] = (long)settings.Slots;
            data["limit_mb"] = (long)settings.LimitMb;
            data["variables"] = settings.Variables.Cast<object>().ToList();
            if (trend.RecordingFile != null) data["file"] = trend.Relative(trend.RecordingFile);
        }

        static int Positive(CliOptions options, string key, int value, int most)
        {
            if (options.Text(key) == null) return value;
            var given = options.Number(key, 0);
            if (given < 1 || given > most) throw Usage("--" + key.Replace('_', '-') + " takes 1 to " + most.ToString(CultureInfo.InvariantCulture));
            return given;
        }

        static IDictionary<string, object> Record(CliCall call, bool on)
        {
            var verb = on ? "trend-on" : "trend-off";
            var value = on ? "TRUE" : "FALSE";
            var answer = call.Call("vars.write", new Dictionary<string, object> { { "values", new Dictionary<string, object> { { TrendFiles.Gate, value } } } });
            if (!Equals(Value(answer, "logged_in"), true)) throw new CliFailure(verb, "not connected", WriteCommand.NotConnected, "cts connect", 1);
            var row = (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().FirstOrDefault();
            if (!Equals(Value(row, "ok"), true))
                throw new CliFailure(verb, "no trend", "the PLC has no " + TrendFiles.Gate + ": cts trend set, then " + Next, "cts trend set --help", 1);
            var watch = Stopwatch.StartNew();
            var data = WriteCommand.Confirm(TrendFiles.Gate, value, value, name => WriteCommand.ReadBack(call, name),
                () => watch.Elapsed.TotalSeconds, seconds => Thread.Sleep(TimeSpan.FromSeconds(seconds)));
            data["recording"] = on;
            return data;
        }

        static Answer Shown(IDictionary<string, object> data)
        {
            if (!Equals(data["trend"], true))
                return new Answer().Add("app", data["app"]).Add("trend", "none").Detail("Next: cts trend set VAR ... picks the variables to record");
            return Settings(new Answer().Add("app", data["app"]), data);
        }

        static Answer Written(IDictionary<string, object> data)
        {
            var changed = (IList<object>)data["changed"];
            var answer = Settings(new Answer().Add("app", data["app"]).Add("changed", changed.Count), data);
            foreach (var line in changed) answer.Detail(line);
            answer.Detail(changed.Count == 0 ? "the files already say so; nothing changed" : "Next: " + data["next"]);
            return answer;
        }

        static Answer Settings(Answer answer, IDictionary<string, object> data)
        {
            answer.Add("task", data["task"]).Add("every", data["every"]);
            if (data.ContainsKey("interval_ms")) answer.Add("interval_ms", data["interval_ms"]);
            answer.Add("slots", data["slots"]).Add("limit_mb", data["limit_mb"]);
            var variables = (IList<object>)data["variables"];
            for (var slot = 0; slot < variables.Count; slot++) answer.Detail("Val" + (slot + 1) + "  " + variables[slot]);
            return answer;
        }

        static Answer Recorded(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("recording", data["recording"]).Add("confirmed", data["confirmed"]);
            if (data.TryGetValue("note", out var note)) answer.Detail(note);
            return answer;
        }

        static CliFailure Usage(string message) => new CliFailure("trend-set", "usage", message, "cts trend set --help", 2);
    }
}
