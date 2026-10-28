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
            new CliCommand
            {
                Name = "trend", Sub = "pull", Summary = "Copy the PLC trend's samples to this PC",
                Description = "Copies the PLC's trend file and merges its samples into this PC's database of the trend, which keeps "
                    + "what earlier pulls brought though the PLC's file drops its oldest rows at its size limit. While the recording runs "
                    + "it pauses for the copy (" + TrendFiles.Gate + " FALSE, then TRUE again), so the file is settled: the pause, "
                    + "the storage interval and the copy's time, shows as paused_s; the PLC keeps the last second before it back until "
                    + "it records again, so the next pull brings that. gaps counts the cycles with no values: while the recording "
                    + "was off (cts trend off, a pull's pause) or the PLC could not store them (too many variables for the task's "
                    + "rate). cts trend query asks the database.",
                Options = Where, Seconds = 330, Execute = Pull, Build = Pulled,
            },
            new CliCommand
            {
                Name = "trend", Sub = "query", Summary = "Ask the pulled trend samples with SQL (offline)",
                Description = "Runs one SQL statement, read-only, on this PC's database of the trend that cts trend pull fills: "
                    + TrendData.Schema + ". Values are as the variable's type reads them (a REAL as a number, a BOOL as 0 or 1). "
                    + "A line per row, its values tab-separated, after a line naming the columns.\n\n"
                    + "  cts trend query \"SELECT name, min(value), max(value), avg(value) FROM samples GROUP BY name\"\n"
                    + "  cts trend query \"SELECT at, value FROM samples_at WHERE name = 'GVL_IO.rLevel' ORDER BY ts DESC LIMIT 20\"",
                Arguments = "SQL ...", ArgumentLimit = 255, ArgumentHelp = "One SQL statement; its words may come quoted together or apart",
                Options = Where.Concat(new[] { CliOption.Int("--limit", "limit", "Show at most N rows (default " + QueryRows + ")") }).ToArray(),
                LocalExecute = Query, Build = Answered,
            },
        };

        const int QueryRows = 200;
        // How long after the pause the PLC surely wrote its last rows: its
        // storage interval and this much more.
        const int SettleMs = 1000;

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
            trend.Root = workspace.Root;
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
            var data = Switched(call, on, on ? "trend-on" : "trend-off");
            data["recording"] = on;
            return data;
        }

        // The gate written *on* and read back.
        static Dictionary<string, object> Switched(CliCall call, bool on, string verb)
        {
            var value = on ? "TRUE" : "FALSE";
            var answer = call.Call("vars.write", new Dictionary<string, object> { { "values", new Dictionary<string, object> { { TrendFiles.Gate, value } } } });
            if (!Equals(Value(answer, "logged_in"), true)) throw new CliFailure(verb, "not connected", WriteCommand.NotConnected, "cts connect", 1);
            var row = (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().FirstOrDefault();
            if (!Equals(Value(row, "ok"), true))
                throw new CliFailure(verb, "no trend", "the PLC has no " + TrendFiles.Gate + ": cts trend set, then " + Next, "cts trend set --help", 1);
            var watch = Stopwatch.StartNew();
            return WriteCommand.Confirm(TrendFiles.Gate, value, value, name => WriteCommand.ReadBack(call, name),
                () => watch.Elapsed.TotalSeconds, seconds => Thread.Sleep(TimeSpan.FromSeconds(seconds)));
        }

        static IDictionary<string, object> Pull(CliCall call)
        {
            var trend = Trend(call.Options, call.Hello.SyncFolder ?? Environment.CurrentDirectory, "trend-pull");
            var settings = trend.Settings() ?? throw new CliFailure("trend-pull", "no trend", "the application " + trend.App
                + " has no trend: cts trend set, then " + Next, "cts trend set --help", 1);
            var gate = WriteCommand.ReadBack(call, TrendFiles.Gate);
            if (gate.TryGetValue("unavailable", out var why))
                throw Equals(why, WriteCommand.NotConnected)
                    ? new CliFailure("trend-pull", "not connected", WriteCommand.NotConnected, "cts connect", 1)
                    : new CliFailure("trend-pull", "no trend", why + " (cts trend set, then " + Next + ")", "cts trend", 1);
            var recording = string.Equals(Convert.ToString(gate["value"], CultureInfo.InvariantCulture), "TRUE", StringComparison.OrdinalIgnoreCase);
            var copy = Path.Combine(Path.GetTempPath(), "cts-trend-" + Guid.NewGuid().ToString("N") + ".sqlite");
            var paused = Stopwatch.StartNew();
            try
            {
                if (recording)
                {
                    Switched(call, false, "trend-pull");
                    Thread.Sleep(settings.StoreMs + SettleMs);
                }
                var file = "PlcLogic/trend/" + trend.App + "." + TrendFiles.Name + ".1.sqlite";
                try { call.Call("plc.fetch", new Dictionary<string, object> { { "file", file }, { "output", copy } }); }
                catch (CliFailure error) when (error.Declined)
                {
                    call.Call("plc.fetch", new Dictionary<string, object> { { "file", file }, { "output", copy } });
                }
            }
            finally
            {
                if (recording) Switched(call, true, "trend-pull");
                paused.Stop();
            }
            var local = TrendData.LocalFile(trend.Root, trend.App);
            Directory.CreateDirectory(Path.GetDirectoryName(local));
            TrendData.Merged merged;
            try { merged = TrendData.Merge(copy, local, TrendFiles.Gate); }
            catch (InvalidOperationException error) { throw new CliFailure("trend-pull", "unreadable", "the PLC's trend file: " + error.Message, "cts trend pull", 1); }
            finally { File.Delete(copy); }
            var data = new Dictionary<string, object>
            {
                ["app"] = trend.App, ["rows"] = merged.Rows, ["gaps"] = merged.Gaps, ["added"] = merged.Added, ["recording"] = recording,
                ["variables"] = merged.Variables.Cast<object>().ToList(), ["database"] = local,
            };
            if (merged.Rows > 0)
            {
                data["gaps_pct"] = Math.Round(100.0 * merged.Gaps / merged.Rows, 1);
                data["from"] = Moment(merged.From.Value);
                data["to"] = Moment(merged.To.Value);
            }
            if (recording) data["paused_s"] = Math.Round(paused.Elapsed.TotalSeconds, 1);
            return data;
        }

        static string Moment(long us) => new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc).AddTicks(us * 10).ToString("yyyy-MM-dd HH:mm:ss.fff", CultureInfo.InvariantCulture);

        static IDictionary<string, object> Query(CliOptions options, IAgentHost host, string work)
        {
            var trend = Trend(options, work, "trend-query");
            if (options.Arguments.Count == 0) throw new CliFailure("trend-query", "usage", "SQL is required", "cts trend query --help", 2);
            var local = TrendData.LocalFile(trend.Root, trend.App);
            if (!File.Exists(local)) throw new CliFailure("trend-query", "nothing pulled", "no samples of " + trend.App + " on this PC yet: cts trend pull copies them", "cts trend pull", 1);
            var limit = options.Number("limit", QueryRows);
            if (limit < 1) throw new CliFailure("trend-query", "usage", "--limit takes 1 or more", "cts trend query --help", 2);
            try
            {
                using (var database = Sqlite.Open(local, false))
                {
                    var rows = database.Rows(string.Join(" ", options.Arguments), limit, out var columns, out var more);
                    return new Dictionary<string, object>
                    {
                        ["columns"] = columns.Cast<object>().ToList(), ["rows"] = rows.Select(row => (object)row.ToList()).ToList(), ["more"] = more,
                    };
                }
            }
            catch (InvalidOperationException error) { throw new CliFailure("trend-query", "refused", error.Message, "cts trend query --help", 1); }
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

        static Answer Pulled(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("app", data["app"]).Add("rows", data["rows"]).Add("gaps", data["gaps"]);
            if (data.ContainsKey("gaps_pct")) answer.Add("gaps_pct", data["gaps_pct"]);
            answer.Add("added", data["added"]);
            if (data.ContainsKey("paused_s")) answer.Add("paused_s", data["paused_s"]);
            if (data.ContainsKey("from")) answer.Detail("from " + data["from"] + " to " + data["to"] + " UTC (the PLC's clock)");
            answer.Detail("variables " + string.Join(" ", (IList<object>)data["variables"]));
            answer.Detail("database " + data["database"]);
            return answer.Detail("Next: cts trend query \"SELECT name, count(*), min(value), max(value) FROM samples GROUP BY name\"");
        }

        static Answer Answered(IDictionary<string, object> data)
        {
            var rows = (IList<object>)data["rows"];
            var answer = new Answer().Add("rows", rows.Count).Add("more", data["more"]);
            answer.Detail(string.Join("\t", (IList<object>)data["columns"]));
            foreach (IList<object> row in rows)
                answer.Detail(string.Join("\t", row.Select(value => value == null ? "NULL" : value is double number ? number.ToString("R", CultureInfo.InvariantCulture) : Convert.ToString(value, CultureInfo.InvariantCulture))));
            return answer.Whole();
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
