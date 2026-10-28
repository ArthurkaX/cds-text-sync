using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts plc-log`: the runtime's loggers, one logger's entries as the lines
    // its log file holds, a copy of them, and the `CTS|` events among them.
    public static class PlcLogCommand
    {
        public static IDictionary<string, object> Execute(CliCall call)
        {
            var options = call.Options.Params;
            var logger = Text(options, "logger");
            // --tail 0 shows every entry; no option at all, the last 20.
            int? tail = options.TryGetValue("tail", out var n) ? Convert.ToInt32(n, CultureInfo.InvariantCulture) : options.Count == 0 ? 20 : (int?)null;
            var output = Text(options, "output");
            var level = Text(options, "level");
            var code = Text(options, "code");
            var wantCts = options.ContainsKey("cts") || level.Length > 0 || code.Length > 0;
            var listOnly = options.ContainsKey("loggers");

            if (listOnly || tail == null && output.Length == 0 && !wantCts)
            {
                var names = Items(call.Call("plc.loggers", new Dictionary<string, object>()), "loggers").ToList();
                return new Dictionary<string, object> { { "loggers", names }, { "count", (long)names.Count } };
            }

            var read = call.Call("plc.log", new Dictionary<string, object> { { "logger", logger } });
            logger = read.TryGetValue("logger", out var named) && named is string name ? name : logger;
            var lines = Items(read, "entries").OfType<IDictionary<string, object>>().Select(Line).ToList();
            var shown = tail > 0 ? lines.Skip(Math.Max(0, lines.Count - tail.Value)).ToList() : lines;

            var data = new Dictionary<string, object> { { "logger", logger } };
            var hints = Hints(shown);
            if (hints.Count > 0) data["hints"] = hints.Cast<object>().ToList();
            if (options.Count == 0)
                data["loggers"] = Items(call.Call("plc.loggers", new Dictionary<string, object>()), "loggers").ToList();
            if (output.Length > 0)
            {
                var target = Destination(output, logger);
                File.WriteAllText(target, string.Concat(lines.Select(l => l + "\n")), new UTF8Encoding(false));
                data["saved_to"] = target;
                data["saved_lines"] = (long)lines.Count;
            }
            if (!wantCts)
            {
                if (tail != null)
                {
                    data["tail"] = shown.ToList<object>();
                    data["tail_count"] = (long)shown.Count;
                    data["total_lines"] = (long)lines.Count;
                }
                return data;
            }

            var records = shown.Select(CtsEvents.Parse).Where(r => r != null).ToList();
            var malformed = records.Where(r => r.ContainsKey("parse_error"))
                .Select(r => (object)new Dictionary<string, object> { { "time", r["time"] }, { "raw", r["raw"] }, { "parse_error", r["parse_error"] } })
                .ToList();
            var valid = records.Where(r => !r.ContainsKey("parse_error")
                && (level.Length == 0 || Equals(r["level"], level)) && (code.Length == 0 || Equals(r["code"], code))).ToList<object>();
            data["source"] = tail > 0 ? "tail" : "log";
            data["count"] = (long)valid.Count;
            data["parse_errors"] = (long)malformed.Count;
            data["records"] = valid;
            data["malformed"] = malformed;
            return data;
        }

        public static Answer Build(IDictionary<string, object> data)
        {
            if (data.ContainsKey("loggers") && !data.ContainsKey("logger"))
                return Items(data, "loggers").Aggregate(new Answer().Add("loggers", data["count"]), (a, l) => a.Detail(l));
            var answer = new Answer().Add("logger", data["logger"]);
            foreach (var name in Items(data, "loggers")) answer.Detail("loggers " + name);
            foreach (var key in new[] { "source", "count", "parse_errors", "tail_count", "total_lines", "saved_lines", "saved_to" })
                if (data.TryGetValue(key, out var value)) answer.Add(key, value);
            foreach (var line in Items(data, "tail")) answer.Detail(line);
            foreach (var record in Items(data, "records").OfType<IDictionary<string, object>>()) answer.Detail(record["raw"]);
            foreach (var bad in Items(data, "malformed").OfType<IDictionary<string, object>>())
                answer.Detail("malformed (" + bad["parse_error"] + "): " + bad["raw"]);
            if (data.ContainsKey("records") && !Items(data, "records").Any() && !Items(data, "malformed").Any())
                answer.Detail("No CTS| entries: only ST code that logs the CTS| marker writes them (cts test's test application does). Next: cts plc-log --tail N shows the raw log");
            foreach (var hint in Items(data, "hints")) answer.Detail("hint: " + hint);
            return answer.Whole();
        }

        // Runtime log lines whose cause is not in their text, and what it is.
        static readonly KeyValuePair<string, string>[] Known =
        {
            new KeyValuePair<string, string>("Failed to save context", "the runtime ran out of TLS contexts (Failed to save context): it keeps part of every context "
                + "created and freed, so code that creates one per connection uses them up; a restart of the runtime frees them, one context "
                + "kept per client instance stops it"),
            new KeyValuePair<string, string>("*EXCEPTION*", "an exception stopped an application (the entry names its kind; SOURCEPOSITION is a code "
                + "offset): CODESYS shows the POU and line once logged in to it (Online -> Call Stack); a watchdog exception is a task "
                + "that ran over its time, an endless loop say"),
        };

        // The hints for the known lines among *lines*, each once.
        internal static List<string> Hints(IEnumerable<string> lines) =>
            Known.Where(known => lines.Any(line => line.IndexOf(known.Key, StringComparison.OrdinalIgnoreCase) >= 0)).Select(known => known.Value).ToList();

        // One entry as the runtime's log file writes it:
        // `<time>, <cmpId>, <classId>, <errorId>, <infoId>, <text>`, on one
        // line: a text the runtime ends with a line break ("Dynamic memory
        // allocation started.") or breaks inside keeps its words on that line.
        public static string Line(IDictionary<string, object> entry)
        {
            Func<string, object> get = key => entry.TryGetValue(key, out var v) && v != null ? v : (object)0L;
            var text = entry.TryGetValue("info", out var info) && info != null ? Convert.ToString(info, CultureInfo.InvariantCulture) : "";
            return string.Format(CultureInfo.InvariantCulture, "{0}, 0x{1:x8}, {2}, {3}, {4}, {5}",
                entry.TryGetValue("time", out var time) ? time : "", Convert.ToInt64(get("cmp_id"), CultureInfo.InvariantCulture),
                get("class"), get("error_id"), get("info_id"), Regex.Replace(text.TrimEnd('\r', '\n'), "[\r\n]+", " "));
        }

        // The file --out names: inside it when it is a folder, named after
        // the logger's last path segment.
        static string Destination(string output, string logger)
        {
            var target = Path.GetFullPath(output);
            if (Directory.Exists(target) || output.EndsWith("/", StringComparison.Ordinal) || output.EndsWith("\\", StringComparison.Ordinal))
            {
                var name = logger.Replace('\\', '/').TrimEnd('/').Split('/').Last();
                if (name.Length == 0) name = "plc";
                if (!name.EndsWith(".log", StringComparison.OrdinalIgnoreCase)) name += ".log";
                target = Path.Combine(target, name);
            }
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            return target;
        }

    }

    // The events the generated PLC code logs, one per runtime log entry:
    //
    //     CTS|<level>|<CODE>|<TAG>|k=v;k=v
    //
    // level is M (minimal, always on) or V (verbose), CODE is [A-Z0-9_]+, TAG
    // may be empty and the payload is optional; keys are [A-Za-z0-9_.]+ and
    // values never hold | or ;. The marker may sit anywhere in the line, and
    // the time is the line's leading ISO stamp when it has one.
    public static class CtsEvents
    {
        const string Marker = "CTS|";
        static readonly Regex Stamp = new Regex(@"^\s*(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?\s*Z?)");
        static readonly Regex Code = new Regex("^[A-Z0-9_]+$");
        static readonly Regex Key = new Regex("^[A-Za-z0-9_.]+$");

        // The record of a line that carries the marker, else null. A line that
        // does not parse is a record too, with parse_error naming every problem.
        public static Dictionary<string, object> Parse(string line)
        {
            var text = line.TrimEnd('\r', '\n');
            var at = text.IndexOf(Marker, StringComparison.Ordinal);
            if (at < 0) return null;
            var stamp = Stamp.Match(text);
            var time = stamp.Success ? stamp.Groups[1].Value : "";
            var parts = text.Substring(at + Marker.Length).Split(new[] { '|' }, 4);
            if (parts.Length < 2)
                return Record(time, parts[0].Trim(), "", "", new Dictionary<string, object>(), text, "missing level/code");

            var level = parts[0].Trim();
            var code = parts[1].Trim();
            var problems = new List<string>();
            if (level != "M" && level != "V") problems.Add("level '" + level + "' is not M or V");
            if (!Code.IsMatch(code)) problems.Add("code '" + code + "' is not [A-Z0-9_]+");
            var fields = new Dictionary<string, object>();
            foreach (var chunk in (parts.Length > 3 ? parts[3] : "").Split(';').Where(c => c.Length > 0))
            {
                var eq = chunk.IndexOf('=');
                if (eq < 0) { problems.Add("field '" + chunk + "' has no '='"); continue; }
                var key = chunk.Substring(0, eq);
                var value = chunk.Substring(eq + 1);
                if (!Key.IsMatch(key)) problems.Add("key '" + key + "' is not [A-Za-z0-9_.]+");
                else if (value.Contains("|")) problems.Add("value for '" + key + "' contains '|'");
                else fields[key] = value;
            }
            return Record(time, level, code, parts.Length > 2 ? parts[2] : "", fields, text, problems.Count > 0 ? string.Join("; ", problems) : null);
        }

        static Dictionary<string, object> Record(string time, string level, string code, string tag, Dictionary<string, object> fields, string raw, string error)
        {
            var record = new Dictionary<string, object>
            {
                { "time", time }, { "level", level }, { "code", code }, { "tag", tag }, { "fields", fields }, { "raw", raw },
            };
            if (error != null) record["parse_error"] = error;
            return record;
        }
    }
}
