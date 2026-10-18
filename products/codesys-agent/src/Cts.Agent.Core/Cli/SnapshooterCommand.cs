using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static class SnapshooterCommand
    {
        public static IList<CliCommand> Commands => new[] { Make("tree"), Make("take"), Make("diff"), Make("restore") };
        static CliCommand Make(string action)
        {
            var command = new CliCommand { Name = "snapshooter", Sub = action, Summary = Summary(action),
                Description = "PLC value presets. tree reads IDE declarations without a PLC session; take, diff and restore read live values.",
                TimeoutKey = "read_variables", Seconds = 300, Execute = Execute, Build = Build };
            if (action == "tree") command.Options = new[] { CliOption.Text("--path", "path", "PREFIX", "Only leaf paths starting with this prefix") };
            if (action == "take")
            {
                command.Options = new[] { CliOption.Many("--path", "path", "PATH", "Exact variable path (repeatable)"), CliOption.Many("--prefix", "prefix", "PREFIX", "Take paths starting with this prefix"), CliOption.Text("--paths-file", "paths_file", "FILE", "Paths to take, one per line (# comments ignored)"), CliOption.Text("--label", "label", "LABEL", "Preset label"), CliOption.Text("--out", "out", "FILE", "Save preset JSON to this path") };
            }
            if (action == "diff" || action == "restore") command.Options = action == "diff"
                ? new[] { CliOption.Needed("--input", "input", "FILE", "Preset JSON") }
                : new[] { CliOption.Needed("--input", "input", "FILE", "Preset JSON"), CliOption.Switch("--apply", "apply", "Write eligible values (default: dry run)") };
            return command;
        }
        static string Summary(string action) => action == "tree" ? "List declared PLC variable leaves and types" : action == "take" ? "Save live PLC values as a JSON preset" : action == "diff" ? "Compare preset values with the PLC" : "Validate a preset and optionally restore it";
        static IDictionary<string, object> Execute(CliCall call)
        {
            var action = call.Command.Sub;
            if (action == "tree")
            {
                var leaves = ReadTree(call).ToList(); var prefix = call.Options.Text("path", "");
                if (prefix.Length > 0) leaves = leaves.Where(x => Text(x, "path", "").StartsWith(prefix, StringComparison.Ordinal)).ToList();
                return new Dictionary<string, object> { { "action", action }, { "path", prefix.Length == 0 ? null : prefix }, { "count", leaves.Count }, { "leaves", leaves.Cast<object>().ToList() } };
            }
            if (action == "take") return Take(call);
            var saved = PresetVariables(Load(call));
            var paths = saved.Select(x => Text(x, "path", "")).ToList();
            var current = ReadValues(call, paths, Types(ReadTree(call)));
            if (action == "diff") return new Dictionary<string, object> { { "action", action }, { "count", saved.Count }, { "report", Compare(saved, current) } };
            return Restore(call, saved, current);
        }
        static IDictionary<string, object> Take(CliCall call)
        {
            var rows = ReadTree(call).ToList(); var types = Types(rows); var paths = new List<string>();
            paths.AddRange(Many(call, "path"));
            var file = call.Options.Text("paths_file", "");
            if (file.Length > 0) { if (!File.Exists(file)) throw Failure("File not found: " + file); paths.AddRange(File.ReadAllLines(file).Select(x => x.Trim()).Where(x => x.Length > 0 && !x.StartsWith("#", StringComparison.Ordinal))); }
            var prefixes = Many(call, "prefix");
            if (prefixes.Count > 0)
            {
                var matched = rows.Select(x => Text(x, "path", "")).Where(p => prefixes.Any(prefix => p.StartsWith(prefix, StringComparison.Ordinal))).ToList();
                if (matched.Count == 0) throw Failure("No variable matches the prefix: " + string.Join(", ", prefixes));
                foreach (var path in matched) if (!paths.Contains(path)) paths.Add(path);
            }
            if (paths.Count == 0) paths = rows.Select(x => Text(x, "path", "")).ToList();
            var values = ReadValues(call, paths, types); var label = call.Options.Text("label", "");
            var document = new Dictionary<string, object> { { "meta", new Dictionary<string, object> { { "format_version", 1 }, { "created", DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture) }, { "project", ProjectName(call) }, { "label", label } } }, { "variables", values.Cast<object>().ToList() } };
            var answer = new Dictionary<string, object> { { "action", "take" }, { "label", label }, { "count", values.Count }, { "document", document } };
            var output = call.Options.Text("out", ""); if (output.Length > 0) { var full = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(full)); File.WriteAllText(full, Cts.Agent.Json.Pretty(document) + "\n"); answer["saved_to"] = full; }
            return answer;
        }
        static List<IDictionary<string, object>> ReadTree(CliCall call)
        {
            var answer = call.Call("objects.texts", new Dictionary<string, object>());
            var objects = (Value(answer, "objects") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            return ReadCommand.VariableLeaves(objects).ToList();
        }
        static List<IDictionary<string, object>> ReadValues(CliCall call, IList<string> paths, IDictionary<string, string> types)
        {
            var answer = paths.Count == 0 ? new Dictionary<string, object> { { "logged_in", true } } : call.Call("vars.read", new Dictionary<string, object> { { "names", paths.Cast<object>().ToList() } });
            if (!Equals(Value(answer, "logged_in"), true)) throw new CliFailure("snapshooter", WriteCommand.NotConnected, WriteCommand.NotConnected, "cts connect", 1);
            var results = (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            var rows = new List<IDictionary<string, object>>();
            for (var i = 0; i < paths.Count; i++)
            {
                var result = i < results.Count ? results[i] : new Dictionary<string, object>(); var ok = Equals(Value(result, "ok"), true); var error = Value(result, "error") as IDictionary<string, object>;
                var row = new Dictionary<string, object> { { "path", paths[i] }, { "type", types.ContainsKey(paths[i]) ? types[paths[i]] : "" }, { "value", ok ? Convert.ToString(Value(result, "text") ?? Value(result, "value") ?? "", CultureInfo.InvariantCulture) : "" }, { "read_ok", ok } };
                if (!ok) row["read_error"] = Convert.ToString(Value(error, "message") ?? "read failed", CultureInfo.InvariantCulture);
                rows.Add(row);
            }
            return rows;
        }
        static IDictionary<string, object> Compare(IList<IDictionary<string, object>> saved, IList<IDictionary<string, object>> current)
        {
            var byPath = current.Where(x => Text(x, "path", "").Length > 0).GroupBy(x => Text(x, "path", ""), StringComparer.Ordinal).ToDictionary(g => g.Key, g => g.Last(), StringComparer.Ordinal);
            var same = new List<object>(); var missing = new List<object>(); var changedType = new List<object>(); var changedValue = new List<object>();
            foreach (var old in saved)
            {
                var path = Text(old, "path", ""); IDictionary<string, object> now;
                if (!byPath.TryGetValue(path, out now) || !Bool(now, "read_ok", false)) { missing.Add(path); continue; }
                var changed = false; var a = Text(old, "type", ""); var b = Text(now, "type", "");
                if (a.Length > 0 && b.Length > 0 && a != b) { changedType.Add(new Dictionary<string, object> { { "path", path }, { "was", a }, { "now", b } }); changed = true; }
                if (Bool(old, "read_ok", true) && Text(old, "value", "") != Text(now, "value", "")) { changedValue.Add(new Dictionary<string, object> { { "path", path }, { "was", Text(old, "value", "") }, { "now", Text(now, "value", "") } }); changed = true; }
                if (!changed) same.Add(path);
            }
            return new Dictionary<string, object> { { "identical", missing.Count == 0 && changedType.Count == 0 && changedValue.Count == 0 }, { "same", same }, { "missing", missing }, { "type_changed", changedType }, { "value_changed", changedValue } };
        }
        static IDictionary<string, object> Restore(CliCall call, IList<IDictionary<string, object>> saved, IList<IDictionary<string, object>> current)
        {
            var currentByPath = current.ToDictionary(x => Text(x, "path", ""), StringComparer.Ordinal); var eligible = new List<IDictionary<string, object>>(); var skipped = new List<object>(); var warnings = new List<object>();
            foreach (var item in saved)
            {
                var path = Text(item, "path", ""); IDictionary<string, object> now;
                if (path.Length == 0) { skipped.Add(new Dictionary<string, object> { { "path", path }, { "reason", "empty path" } }); continue; }
                if (!Bool(item, "read_ok", true)) { skipped.Add(new Dictionary<string, object> { { "path", path }, { "reason", "source read_ok=false" } }); continue; }
                if (!currentByPath.TryGetValue(path, out now) || !Bool(now, "read_ok", false)) { skipped.Add(new Dictionary<string, object> { { "path", path }, { "reason", "path missing or not readable" } }); continue; }
                var oldType = Text(item, "type", ""); var nowType = Text(now, "type", ""); if (oldType.Length > 0 && nowType.Length > 0 && oldType != nowType) warnings.Add(new Dictionary<string, object> { { "path", path }, { "warning", "type mismatch: " + oldType + " -> " + nowType } });
                eligible.Add(new Dictionary<string, object> { { "name", path }, { "value", Value(item, "value") ?? "" } });
            }
            var apply = call.Options.Params.ContainsKey("apply"); var written = 0; var confirmed = 0;
            if (apply && eligible.Count > 0)
            {
                var values = eligible.ToDictionary(x => Text(x, "name", ""), x => Value(x, "value")); var answer = call.Call("vars.write", new Dictionary<string, object> { { "values", values } });
                if (!Equals(Value(answer, "logged_in"), true)) throw new CliFailure("snapshooter", WriteCommand.NotConnected, WriteCommand.NotConnected, "cts connect", 1);
                var results = (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToDictionary(x => Text(x, "name", ""), StringComparer.Ordinal);
                foreach (var item in eligible) { IDictionary<string, object> result; if (results.TryGetValue(Text(item, "name", ""), out result) && Bool(result, "ok", false)) written++; else { var error = results.TryGetValue(Text(item, "name", ""), out result) ? Value(Value(result, "error") as IDictionary<string, object>, "message") : null; skipped.Add(new Dictionary<string, object> { { "path", Text(item, "name", "") }, { "reason", Convert.ToString(error ?? "no result", CultureInfo.InvariantCulture) } }); } }
                // As cts write: the PLC shows a written value a moment later,
                // and a diff run right after the restore must see it.
                var watch = Stopwatch.StartNew(); var deadline = WriteCommand.ReadBackS;
                foreach (var item in eligible.Where(x => results.TryGetValue(Text(x, "name", ""), out var r) && Bool(r, "ok", false)))
                {
                    var name = Text(item, "name", ""); var typed = Convert.ToString(Value(item, "value"), CultureInfo.InvariantCulture);
                    var shown = WriteCommand.Confirm(name, typed, Value(results[name], "text") as string ?? typed, n => WriteCommand.ReadBack(call, n), () => watch.Elapsed.TotalSeconds, s => Thread.Sleep(TimeSpan.FromSeconds(s)), deadline);
                    if (Equals(shown["confirmed"], true)) confirmed++;
                    else warnings.Add(new Dictionary<string, object> { { "path", name }, { "warning", Convert.ToString(Value(shown, "note") ?? "the value could not be read back", CultureInfo.InvariantCulture) } });
                }
            }
            return new Dictionary<string, object> { { "action", "restore" }, { "applied", apply }, { "result", new Dictionary<string, object> { { "written", written }, { "confirmed", confirmed }, { "skipped", skipped.Count }, { "warnings", warnings }, { "would_write", apply ? 0 : eligible.Count }, { "details", new Dictionary<string, object> { { "eligible", eligible.Count }, { "skipped", skipped }, { "apply", apply } } } } } };
        }
        static IList<IDictionary<string, object>> PresetVariables(object data) { var doc = data as IDictionary<string, object>; return (doc == null ? data as IEnumerable<object> : Value(doc, "variables") as IEnumerable<object> ?? Value(doc, "vars") as IEnumerable<object>)?.OfType<IDictionary<string, object>>().ToList() ?? new List<IDictionary<string, object>>(); }
        static object Load(CliCall call) { var path = call.Options.Text("input", ""); if (!File.Exists(path)) throw Failure("File not found: " + path); try { return Cts.Agent.Json.Parse(File.ReadAllText(path)); } catch (Exception e) { throw Failure("Invalid preset JSON: " + e.Message); } }
        static string ProjectName(CliCall call) { var data = call.Call("project.status", new Dictionary<string, object>(), 10); var path = Text(data, "path", "").Replace('\\', '/'); return Path.GetFileNameWithoutExtension(path); }
        static IDictionary<string, string> Types(IEnumerable<IDictionary<string, object>> rows) => rows.GroupBy(x => Text(x, "path", ""), StringComparer.Ordinal).ToDictionary(g => g.Key, g => Text(g.First(), "type", ""), StringComparer.Ordinal);
        static List<string> Many(CliCall call, string key) => call.Options.Params.TryGetValue(key, out var value) ? (value as IEnumerable<object> ?? new object[0]).Select(x => Convert.ToString(x, CultureInfo.InvariantCulture)).ToList() : new List<string>();
        static bool Bool(IDictionary<string, object> data, string key, bool fallback) { var value = Value(data, key); return value == null ? fallback : Equals(value, true); }
        static CliFailure Failure(string message) => new CliFailure("snapshooter", message, message, null, 1);
        // The line says what an agent decides on: how many, and for diff and
        // restore whether the PLC matches the preset and what was written.
        static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("action", Value(data, "action")).Add("count", Value(data, "count")).Add("path", Value(data, "path"))
                .Add("label", Value(data, "label")).Add("saved_to", Value(data, "saved_to"));
            if (Value(data, "report") is IDictionary<string, object> report)
                answer.Add("identical", Value(report, "identical")).Add("value_changed", Count(report, "value_changed"))
                    .Add("type_changed", Count(report, "type_changed")).Add("missing", Count(report, "missing"));
            if (Value(data, "result") is IDictionary<string, object> result)
                answer.Add("applied", Value(data, "applied")).Add("written", Value(result, "written"))
                    .Add("would_write", Value(result, "would_write")).Add("skipped", Value(result, "skipped"));
            return answer;
        }
        static int? Count(IDictionary<string, object> data, string key) => (Value(data, key) as IEnumerable<object>)?.Count();
    }
}
