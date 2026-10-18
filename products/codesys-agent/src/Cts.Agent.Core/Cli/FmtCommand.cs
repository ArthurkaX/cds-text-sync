using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    internal static class FmtCommand
    {
        static readonly string[] Parts = { "declaration", "implementation" };

        internal static IDictionary<string, object> Execute(CliCall call)
        {
            var guid = Convert.ToString(call.Options.Params.ContainsKey("guid") ? call.Options.Params["guid"] : null)?.Trim().Trim('{', '}') ?? "";
            var name = call.Options.Arguments.FirstOrDefault() ?? "";
            var hasTimestamp = call.Options.Params.ContainsKey("if_timestamp");
            if (hasTimestamp && guid.Length == 0) throw Failure("--if-timestamp goes with --guid");
            var parameters = new Dictionary<string, object>();
            if (guid.Length > 0) parameters["guids"] = new[] { guid };
            var records = Maps(call.Call("objects.texts", parameters), "objects").ToList();
            var names = records.ToDictionary(r => Text(r, "guid"), r => Text(r, "name"), StringComparer.OrdinalIgnoreCase);
            foreach (var record in records)
            {
                var parent = Text(record, "parent");
                var label = names.TryGetValue(parent, out var parentName) && parentName.Length > 0 ? parentName + "." + Text(record, "name") : Text(record, "name");
                record["label"] = label;
            }
            if (guid.Length > 0) records = records.Where(r => Text(r, "guid").Equals(guid, StringComparison.OrdinalIgnoreCase)).ToList();
            else if (name.Length > 0)
            {
                records = records.Where(r => Text(r, "label").Equals(name, StringComparison.OrdinalIgnoreCase) || Text(r, "name").Equals(name, StringComparison.OrdinalIgnoreCase)).ToList();
                if (records.Count > 1) throw Failure(name + " names " + string.Join(", ", records.Select(r => Text(r, "label"))) + ": give Parent.Name or --guid");
            }
            if (records.Count == 0) throw Failure(guid.Length > 0 ? "no text object has the guid " + guid : "no text object is named " + name);
            var items = records.Select(Item).OrderBy(r => Text(r, "label"), StringComparer.OrdinalIgnoreCase).ToList();
            var data = new Dictionary<string, object>
            {
                ["objects"] = items.Count,
                ["to_fix"] = items.Count(r => Int(r, "lines") > 0),
                ["lines"] = items.Sum(r => Int(r, "lines")),
                ["items"] = items,
            };
            if (call.Options.Params.ContainsKey("write"))
            {
                Write(call, items, hasTimestamp ? Convert.ToInt64(call.Options.Params["if_timestamp"]) : (long?)null, data);
                if (!string.IsNullOrEmpty(call.Hello.SyncFolder)) data["sync_folder"] = call.Hello.SyncFolder;
            }
            else foreach (var item in items) item.Remove("_parts");
            return data;
        }

        // --disk: the sync folder's .st files, each object's declaration and
        // implementation laid out where they stand in the file; --write
        // rewrites the files and leaves the IDE alone.
        internal static IDictionary<string, object> Disk(CliOptions options, IAgentHost host, string work)
        {
            if (options.Params.ContainsKey("guid") || options.Params.ContainsKey("if_timestamp")) throw Failure("--guid and --if-timestamp name IDE objects; with --disk give NAME");
            var folder = FsmCommand.Folder(options, host, work);
            var view = ViewFolder.Of(folder);
            if (!Directory.Exists(view)) throw Failure("the sync folder has no " + view);
            var read = StViewReader.Read(view);
            var records = read.Objects.Select(item =>
            {
                var depth = (Path.GetDirectoryName(item.File) ?? "").Replace('\\', '/').Split('/').Count(part => part.Length > 0);
                return new Dictionary<string, object> { ["item"] = item, ["label"] = string.Join(".", item.Path.Skip(depth)), ["name"] = item.Path.Last() };
            }).ToList();
            var name = options.Arguments.FirstOrDefault() ?? "";
            if (name.Length > 0)
            {
                records = records.Where(r => Text(r, "label").Equals(name, StringComparison.OrdinalIgnoreCase) || Text(r, "name").Equals(name, StringComparison.OrdinalIgnoreCase)).ToList();
                if (records.Count > 1) throw Failure(name + " names " + string.Join(", ", records.Select(r => Text(r, "label"))) + ": give Parent.Name");
                if (records.Count == 0) throw Failure("no text object is named " + name);
            }
            var items = records.Select(record => DiskItem((StViewObject)record["item"], Text(record, "label"))).OrderBy(r => Text(r, "label"), StringComparer.OrdinalIgnoreCase).ToList();
            var data = new Dictionary<string, object>
            {
                ["from"] = "disk", ["sync_folder"] = folder,
                ["objects"] = items.Count,
                ["to_fix"] = items.Count(r => Int(r, "lines") > 0),
                ["lines"] = items.Sum(r => Int(r, "lines")),
                ["items"] = items,
            };
            var failed = read.Errors.Select(error => (object)new Dictionary<string, object> { ["label"] = error.File, ["error"] = error.Reason }).ToList();
            if (options.Params.ContainsKey("write")) data["written"] = WriteFiles(view, items, failed);
            foreach (var item in items) item.Remove("_spans");
            if (failed.Count > 0) data["failed"] = failed;
            return data;
        }

        // One object's parts as the IDE form reports them, with where each
        // part's lines stand in its file (an action's heading is no part).
        static IDictionary<string, object> DiskItem(StViewObject item, string label)
        {
            var entry = new Dictionary<string, object> { ["label"] = label, ["file"] = item.File };
            var spans = new List<Tuple<int, string, string>>();
            var lines = 0;
            foreach (var part in Parts)
            {
                var before = part == "declaration" ? (item.Kind == "ACTION" ? null : item.Declaration) : item.Implementation;
                var line = part == "declaration" ? item.DeclarationLine : item.ImplementationLine;
                if (string.IsNullOrEmpty(before) || !line.HasValue) continue;
                var after = StFormatter.Format(before, part == "declaration");
                if (before == after) continue;
                spans.Add(Tuple.Create(line.Value, before, after));
                lines += ChangedLines(before, after);
                entry[part] = new Dictionary<string, object> { ["before"] = before, ["after"] = after };
            }
            entry["lines"] = lines;
            entry["_spans"] = spans;
            return entry;
        }

        // Each file with a part to lay out, its parts replaced from the last
        // up, so a part's line count changing never moves one above it. A
        // file keeps its byte order mark and its line ends.
        static int WriteFiles(string view, IList<IDictionary<string, object>> items, IList<object> failed)
        {
            var written = 0;
            foreach (var file in items.Where(item => Int(item, "lines") > 0).GroupBy(item => Text(item, "file")))
            {
                var path = Path.Combine(view, file.Key.Replace('/', Path.DirectorySeparatorChar));
                var bytes = File.ReadAllBytes(path);
                var text = new UTF8Encoding(false, true).GetString(bytes);
                var bom = text.StartsWith("\uFEFF", StringComparison.Ordinal);
                var crlf = text.Contains("\r\n");
                var lines = StText.Lf(text.TrimStart('\uFEFF')).Split('\n').ToList();
                var spans = file.SelectMany(item => (List<Tuple<int, string, string>>)item["_spans"]).OrderByDescending(span => span.Item1).ToList();
                var stale = spans.FirstOrDefault(span => string.Join("\n", lines.Skip(span.Item1 - 1).Take(span.Item2.Split('\n').Length)) != span.Item2);
                if (stale != null)
                {
                    failed.Add(new Dictionary<string, object> { ["label"] = file.Key, ["error"] = "changed while it was read; run cts fmt --disk again" });
                    continue;
                }
                foreach (var span in spans)
                {
                    lines.RemoveRange(span.Item1 - 1, span.Item2.Split('\n').Length);
                    lines.InsertRange(span.Item1 - 1, span.Item3.Split('\n'));
                }
                var result = string.Join(crlf ? "\r\n" : "\n", lines);
                File.WriteAllText(path, (bom ? "\uFEFF" : "") + result, new UTF8Encoding(false));
                written += file.Count();
            }
            return written;
        }

        static IDictionary<string, object> Item(IDictionary<string, object> record)
        {
            var entry = new Dictionary<string, object>
            {
                ["guid"] = Text(record, "guid"), ["label"] = Text(record, "label"),
                ["timestamp"] = Value(record, "timestamp") ?? 0L,
            };
            var parts = new Dictionary<string, Tuple<string, string>>();
            var lines = 0;
            foreach (var part in Parts)
            {
                if (!(Value(record, part) is string before)) continue;
                var after = StFormatter.Format(before, part == "declaration");
                parts[part] = Tuple.Create(before, after);
                lines += ChangedLines(before, after);
                if (before != after) entry[part] = new Dictionary<string, object> { ["before"] = before, ["after"] = after };
            }
            entry["lines"] = lines;
            entry["_parts"] = parts;
            return entry;
        }

        // Lines changed between two texts, a replaced run counted once. The
        // lines both share at the start and the end are left out first: the
        // comparison table is the square of what is left, and a formatted
        // object of thousands of lines usually changes a few.
        internal static int ChangedLines(string before, string after)
        {
            if (before == after) return 0;
            var whole = before.Split('\n'); var wholeAfter = after.Split('\n');
            var head = 0;
            while (head < whole.Length && head < wholeAfter.Length && whole[head] == wholeAfter[head]) head++;
            var tail = 0;
            while (tail < whole.Length - head && tail < wholeAfter.Length - head && whole[whole.Length - 1 - tail] == wholeAfter[wholeAfter.Length - 1 - tail]) tail++;
            var a = whole.Skip(head).Take(whole.Length - head - tail).ToArray(); var b = wholeAfter.Skip(head).Take(wholeAfter.Length - head - tail).ToArray();
            var lcs = new int[a.Length + 1, b.Length + 1];
            for (var i = a.Length - 1; i >= 0; i--) for (var j = b.Length - 1; j >= 0; j--)
                lcs[i, j] = a[i] == b[j] ? lcs[i + 1, j + 1] + 1 : Math.Max(lcs[i + 1, j], lcs[i, j + 1]);
            var x = 0; var y = 0; var runA = 0; var runB = 0; var count = 0;
            Action flush = () => { count += Math.Max(runA, runB); runA = 0; runB = 0; };
            while (x < a.Length || y < b.Length)
            {
                if (x < a.Length && y < b.Length && a[x] == b[y]) { flush(); x++; y++; }
                else if (y < b.Length && (x == a.Length || lcs[x, y + 1] >= lcs[x + 1, y])) { runB++; y++; }
                else { runA++; x++; }
            }
            flush(); return count;
        }

        static void Write(CliCall call, IList<IDictionary<string, object>> items, long? timestamp, IDictionary<string, object> data)
        {
            var written = new List<string>(); var failed = new List<object>();
            foreach (var item in items.Where(r => Int(r, "lines") > 0))
            {
                var label = Text(item, "label");
                if (timestamp.HasValue && Convert.ToInt64(item["timestamp"]) != timestamp.Value)
                { failed.Add(new Dictionary<string, object> { ["label"] = label, ["error"] = "changed since the preview; look at it again" }); continue; }
                var parameters = new Dictionary<string, object> { ["guid"] = Text(item, "guid") };
                var parts = (Dictionary<string, Tuple<string, string>>)item["_parts"];
                foreach (var part in Parts) if (parts.TryGetValue(part, out var pair) && pair.Item1 != pair.Item2) parameters[part] = pair.Item2;
                try { call.Call("objects.settext", parameters); }
                catch (CliFailure failure)
                {
                    if (failure.Cause == "unknown_method" || failure.Message.Contains("the project is online")
                        || failure.Message.StartsWith("Forbidden by the deny list", StringComparison.Ordinal)) throw;
                    failed.Add(new Dictionary<string, object> { ["label"] = label, ["error"] = failure.Cause + ": " + failure.Message });
                    continue;
                }
                written.Add(label);
            }
            foreach (var item in items) item.Remove("_parts");
            data["written"] = written.Count;
            if (failed.Count > 0) data["failed"] = failed;
        }

        internal static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer().Add("objects", data["objects"]).Add("to_fix", data["to_fix"]).Add("lines", data["lines"]);
            if (data.ContainsKey("written")) answer.Add("written", data["written"]);
            if (data.ContainsKey("failed")) { answer.Add("failed", ((IList<object>)data["failed"]).Count); answer.Partial(); }
            foreach (var item in Maps(data, "items").Where(r => Int(r, "lines") > 0).Take(20)) answer.Detail(Text(item, "label") + ": " + item["lines"] + " line(s)");
            foreach (var item in Maps(data, "failed")) answer.Detail("[ERROR] " + Text(item, "label") + ": " + Text(item, "error"));
            if (Equals(data.TryGetValue("from", out var from) ? from : null, "disk") && Int(data, "written") > 0)
                answer.Detail("Next: only the files changed; cts import carries the new layout into the IDE");
            else if (data.ContainsKey("sync_folder") && Int(data, "written") > 0)
                answer.Detail("Next: only the IDE changed; cts sync writes the new layout into the sync folder's files");
            return answer;
        }

        static CliFailure Failure(string message) => new CliFailure("fmt", "refused", message, "cts fmt --help", 1);
    }
}
