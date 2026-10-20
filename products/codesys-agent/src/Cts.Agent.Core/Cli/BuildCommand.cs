using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    public static class BuildCommand
    {
        public static readonly CliCommand Command = new CliCommand
        {
            Name = "build", Summary = "Compile the active application, or check a library project",
            Description = "Compiles the active application: the objects its tasks call. An object no task calls is not compiled, so a clean build says nothing about it; --all-objects checks it too. A library project is checked; --install saves and installs it after a clean check.",
            TimeoutKey = "build",
            Options = new[]
            {
                CliOption.Switch("--install", "install", "For a library project, save and install after a clean check"),
                CliOption.Switch("--all-objects", "all_objects", "Also check every application object, including unreferenced objects"),
                CliOption.Text("--app", "application", "NAME", "Make the named application the active one first; download and connect then act on it too"),
            },
            Execute = Execute, Build = Build,
        };

        static IDictionary<string, object> Execute(CliCall call)
        {
            var previous = call.Options.Params.ContainsKey("application") ? Activate(call, Convert.ToString(call.Options.Params["application"], CultureInfo.InvariantCulture)) : null;
            var request = new Dictionary<string, object>();
            foreach (var key in new[] { "install", "all_objects" })
                if (call.Options.Params.ContainsKey(key)) request[key] = true;
            var seconds = call.Options.Params.ContainsKey("all_objects") && call.Options.Timeout == null
                ? call.Seconds * 2 : call.Seconds;
            var result = call.Call("app.build", request, seconds);
            PlaceMessages(call, result);
            var compiledMessages = (Value(result, "messages") as IEnumerable<object> ?? new object[0])
                .OfType<IDictionary<string, object>>().Where(m =>
                    !(Convert.ToString(Value(m, "text"), CultureInfo.InvariantCulture) ?? "").StartsWith("Build started", StringComparison.Ordinal)
                    && !(Convert.ToString(Value(m, "text"), CultureInfo.InvariantCulture) ?? "").StartsWith("Compile complete", StringComparison.Ordinal)).ToList();
            var messages = new List<IDictionary<string, object>>(compiledMessages);
            if (call.Options.Params.ContainsKey("all_objects"))
            {
                var seen = new HashSet<string>(compiledMessages.Select(MessageKey), StringComparer.Ordinal);
                foreach (var message in (Value(result, "checked_messages") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>())
                {
                    if (Severity(Value(message, "severity")) != "error" && Severity(Value(message, "severity")) != "warning") continue;
                    if (seen.Add(MessageKey(message))) messages.Add(new Dictionary<string, object>(message) { ["not_called"] = true });
                }
            }
            var errors = messages.Count(m => Severity(Value(m, "severity")) == "error");
            var warnings = messages.Count(m => Severity(Value(m, "severity")) == "warning");
            var data = new Dictionary<string, object>
            {
                ["application"] = Value(result, "application") ?? "", ["project_path"] = Value(result, "project_path") ?? "",
                ["errors"] = errors, ["warnings"] = warnings, ["messages"] = messages.Cast<object>().ToList(),
                ["ok"] = errors == 0 && !result.ContainsKey("install_error"),
                ["elapsed_seconds"] = Value(result, "elapsed_seconds"),
                ["diagnostics_complete"] = !(Equals(Value(result, "compiled"), false) && errors == 0),
            };
            foreach (var key in new[] { "kind", "installed", "library", "install_error" })
                if (result.ContainsKey(key)) data[key] = result[key];
            var pending = NotImported(call);
            if (pending.Count > 0) data["not_imported"] = pending;
            if (previous != null) data["previous_application"] = previous;
            return data;
        }

        // Makes the application named the active one; the one active before, or null when it already was.
        static string Activate(CliCall call, string name)
        {
            var apps = Items(call.Call("project.devices", new Dictionary<string, object>()), "devices").OfType<IDictionary<string, object>>()
                .SelectMany(device => Items(device, "applications").OfType<IDictionary<string, object>>()
                    .Select(app => new { Device = Convert.ToString(Value(device, "path") ?? Value(device, "name"), CultureInfo.InvariantCulture), App = app }))
                .ToList();
            var named = apps.Where(item => string.Equals(Convert.ToString(Value(item.App, "name"), CultureInfo.InvariantCulture), name, StringComparison.OrdinalIgnoreCase)).ToList();
            if (named.Count != 1)
                throw new CliFailure("build", "refused", (named.Count == 0 ? "No application '" + name + "' in the project" : "Two applications are named '" + name + "'")
                    + "; applications: " + (apps.Count == 0 ? "none" : string.Join(", ", apps.Select(item => item.Device + "/" + Value(item.App, "name")))), "cts project list-devices", 1);
            if (Equals(Value(named[0].App, "active"), true)) return null;
            var reply = call.Call("app.activate", new Dictionary<string, object> { { "application", Value(named[0].App, "guid") } });
            return Convert.ToString(Value(reply, "previous"), CultureInfo.InvariantCulture) ?? "";
        }

        static void PlaceMessages(CliCall call, IDictionary<string, object> result)
        {
            var messages = (Value(result, "messages") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>()
                .Concat(Value(result, "checked_messages") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            if (messages.Count == 0 || !messages.Any(m => Value(m, "part") != null)) return;
            string folder = null;
            try { folder = Convert.ToString(Value(call.Call("project.status", new Dictionary<string, object>(), Math.Min(call.Seconds, 10)), "sync_folder"), CultureInfo.InvariantCulture); }
            catch (Exception e) when (e is CliFailure || e is InvalidOperationException || e is IOException) { }
            var snapshot = Path.Combine(Path.GetTempPath(), "cts-build-" + Guid.NewGuid().ToString("N") + ".xml");
            string diskView = null;
            try
            {
                call.Call("project.export", new Dictionary<string, object> { { "path", snapshot } });
                var model = SnapshotReader.Read(snapshot);
                var rendered = new MemoryViewFiles();
                ViewExport.WriteTo(snapshot, folder ?? Path.GetTempPath(), null, rendered);
                if (!string.IsNullOrWhiteSpace(folder)) diskView = ViewFolder.Of(folder);
                var view = string.IsNullOrWhiteSpace(diskView) ? StViewReader.Read((IViewFiles)rendered) : StViewReader.Read(diskView);
                foreach (var message in messages)
                {
                    var guid = (Convert.ToString(Value(message, "guid"), CultureInfo.InvariantCulture) ?? "").Trim().Trim('{', '}').ToLowerInvariant();
                    if (!string.IsNullOrWhiteSpace(folder) && model.Nodes.TryGetValue(guid, out var node))
                    {
                        // A member lives in the file of the nearest ancestor that has one
                        // (a property accessor in its property's owner).
                        var holder = node;
                        while (!rendered.Paths.Contains(string.Join("/", holder.Parts(model)) + ".st", StringComparer.OrdinalIgnoreCase)
                            && holder.ParentGuid != null && model.Nodes.TryGetValue(holder.ParentGuid, out var up))
                            holder = up;
                        var own = string.Join("/", holder.Parts(model)) + ".st";
                        var relativeView = ExportCommand.Relative(folder, diskView);
                        var relative = relativeView == "." ? own : relativeView + "/" + own;
                        var source = Path.Combine(folder, relative.Replace('/', Path.DirectorySeparatorChar));
                        if (!File.Exists(source)) source = null;
                        var lineText = Convert.ToString(Value(message, "line_text"), CultureInfo.InvariantCulture);
                        var partLine = Int(message, "part_line");
                        var idePath = node.Parts(model);
                        var textObject = view.Objects.FirstOrDefault(o => o.Path.SequenceEqual(idePath, StringComparer.Ordinal));
                        var line = StViewReader.FindLine(textObject, Convert.ToString(Value(message, "part"), CultureInfo.InvariantCulture), lineText, partLine);
                        if (line > 0)
                        {
                            message["file"] = relative; message["line"] = line;
                        }
                    }
                }
            }
            catch (Exception e) when (e is CliFailure || e is InvalidOperationException || e is IOException || e is ArgumentException || e is UnauthorizedAccessException) { }
            finally
            {
                if (File.Exists(snapshot)) File.Delete(snapshot);
                foreach (var message in messages)
                    foreach (var key in new[] { "part", "part_line", "line_text" }) message.Remove(key);
            }
        }

        static Answer Build(IDictionary<string, object> data)
        {
            var messages = (Value(data, "messages") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
            var allErrors = messages.Where(m => Severity(Value(m, "severity")) == "error").ToList();
            var errors = DistinctRows(allErrors);
            var warnings = DistinctRows(messages.Where(m => Severity(Value(m, "severity")) == "warning"));
            var answer = new Answer().Add("cause", errors.Count > 0 ? Normalize(Value(errors[0], "text")) : Value(data, "install_error"))
                .Add("errors", Value(data, "errors")).Add("warnings", Value(data, "warnings"));
            if (data.ContainsKey("installed")) answer.Add("installed", data["installed"]);
            if (data.ContainsKey("library")) answer.Add("library", data["library"]);
            if (data.ContainsKey("previous_application"))
                answer.Detail(Value(data, "application") + " is the active application now" + (Convert.ToString(data["previous_application"], CultureInfo.InvariantCulture) is var was && was.Length > 0 ? ", instead of " + was : ""));
            var pending = Value(data, "not_imported") as IEnumerable<object> ?? new object[0];
            var pendingFiles = pending.Select(x => Convert.ToString(x, CultureInfo.InvariantCulture)).ToList();
            if (pendingFiles.Count > 0)
            {
                answer.Add("not_imported", pendingFiles.Count);
                var shown = string.Join(", ", pendingFiles.Take(5))
                    + (pendingFiles.Count > 5 ? " and " + (pendingFiles.Count - 5) + " more" : "");
                answer.Detail("Built without what changed on disk since the last sync: " + shown + ". Next: cts import, then cts build");
            }
            var codes = allErrors.GroupBy(m => Convert.ToString(Value(m, "code"), CultureInfo.InvariantCulture) is string code && code.Length > 0 ? code : "?")
                .OrderBy(g => g.Key, StringComparer.Ordinal).Select(g => g.Key + ":" + g.Count()).ToList();
            if (codes.Count > 0) answer.Add("error_codes", string.Join(",", codes));
            foreach (var item in Rows(errors, 12, "", "errors")) answer.Detail(item);
            foreach (var item in Rows(warnings, errors.Count > 0 ? 5 : 15, "warning ", "warnings")) answer.Detail(item);
            if (errors.Count > 0 || Equals(Value(data, "diagnostics_complete"), false) || data.ContainsKey("install_error")) answer.Failed();
            return answer;
        }

        static IEnumerable<string> Rows(List<IDictionary<string, object>> rows, int shown, string prefix, string noun)
        {
            foreach (var row in rows.Take(shown))
            {
                var place = Convert.ToString(Value(row, "object"), CultureInfo.InvariantCulture) ?? "";
                var file = Convert.ToString(Value(row, "file"), CultureInfo.InvariantCulture);
                if (!string.IsNullOrEmpty(file) && Value(row, "line") != null)
                    place += (place.Length == 0 ? "" : " at ") + file + ":" + Value(row, "line") + (Value(row, "column") == null ? "" : ":" + Value(row, "column"));
                else if (Value(row, "part") is string part && Value(row, "part_line") != null)
                    place += (place.Length == 0 ? "" : " at ") + part + ":" + Value(row, "part_line") + (Value(row, "column") == null ? "" : ":" + Value(row, "column"));
                if (Equals(Value(row, "not_called"), true)) place += ", not called by any task";
                yield return prefix + "[" + Value(row, "code") + "] " + Normalize(Value(row, "text")) + (place.Length == 0 ? "" : " (in " + place + ")");
            }
            if (rows.Count > shown) yield return "... and " + (rows.Count - shown) + " more " + noun + ": cts build --json lists them all";
        }
        static string Severity(object value)
        {
            var text = (Convert.ToString(value, CultureInfo.InvariantCulture) ?? "").Trim().ToLowerInvariant();
            if (text.Contains("error")) return "error";
            if (text.Contains("warning")) return "warning";
            return text.Contains("info") ? "info" : "";
        }

        static List<object> NotImported(CliCall call)
        {
            try
            {
                var status = call.Call("project.status", new Dictionary<string, object>(), Math.Min(call.Seconds, 10));
                var folder = Convert.ToString(Value(status, "sync_folder"), CultureInfo.InvariantCulture);
                if (string.IsNullOrWhiteSpace(folder)) return new List<object>();
                folder = GitRepository.Repository(folder);
                if (GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}").ExitCode != 0)
                    return new List<object>();
                var view = ExportCommand.Relative(folder, ViewFolder.Of(folder));
                var prefix = view == "." ? "" : view + "/";
                return SyncBase.Changed(folder, view, "refs/cts/base").Keys
                    .Where(path => !path.Split('/').Any(part => part.StartsWith(".", StringComparison.Ordinal)))
                    .Select(path => prefix + path).OrderBy(path => path, StringComparer.Ordinal).Cast<object>().ToList();
            }
            catch (Exception e) when (e is CliFailure || e is InvalidOperationException || e is IOException || e is ArgumentException)
            {
                return new List<object>();
            }
        }

        internal static List<IDictionary<string, object>> DistinctRows(IEnumerable<IDictionary<string, object>> source)
        {
            var result = new List<IDictionary<string, object>>();
            var keys = new HashSet<string>(StringComparer.Ordinal);
            IDictionary<string, object> last = null;
            foreach (var row in source)
            {
                var text = Normalize(Value(row, "text"));
                if (text.StartsWith("related position", StringComparison.OrdinalIgnoreCase) && last != null)
                {
                    last["text"] = Convert.ToString(Value(last, "text"), CultureInfo.InvariantCulture) + " (" + text + ")";
                    continue;
                }
                var key = string.Join("\u001f", new[] { Value(row, "code"), text, Value(row, "object"), Value(row, "file"), Value(row, "line"), Value(row, "column") }
                    .Select(v => Convert.ToString(v, CultureInfo.InvariantCulture) ?? ""));
                var normalized = new Dictionary<string, object>(row) { ["text"] = text };
                if (keys.Add(key)) result.Add(normalized);
                last = normalized;
            }
            return result;
        }
        static string Normalize(object value) => string.Join(" ", (Convert.ToString(value, CultureInfo.InvariantCulture) ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
        static string MessageKey(IDictionary<string, object> message) => string.Join("\u001f", new[] { "severity", "code", "text", "guid", "part", "part_line", "column" }.Select(k => Convert.ToString(Value(message, k), CultureInfo.InvariantCulture) ?? ""));
    }
}
