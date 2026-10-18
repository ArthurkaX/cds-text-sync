using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    internal static class ReadObjectCommand
    {
        internal static IDictionary<string, object> Execute(CliCall call)
        {
            var o = call.Options;
            var guid = o.Text("guid", "").Trim().Trim('{', '}');
            var path = o.Text("path", "");
            var name = o.Text("name", "");
            if (string.IsNullOrEmpty(name)) name = o.Arguments.FirstOrDefault() ?? "";
            if (guid.Length == 0 && path.Length == 0 && name.Length == 0) throw Failure("read-object needs a name, --path or --guid");
            IDictionary<string, object> match = null;
            if (guid.Length > 0)
            {
                var text = call.Call("objects.text", new Dictionary<string, object> { { "guid", guid } });
                name = Value(text, "name") as string ?? name;
                var found = call.Call("objects.find", new Dictionary<string, object> { { "name", name } });
                match = Maps(found, "matches").FirstOrDefault(m => Normalize(Value(m, "guid")) == Normalize(guid));
            }
            else
            {
                var parts = Parts(path);
                name = parts.LastOrDefault() ?? name;
                var found = Maps(call.Call("objects.find", new Dictionary<string, object> { { "name", name } }), "matches");
                var wanted = parts.Count == 0 ? null : string.Join("/", parts);
                var candidates = found.Where(m => wanted == null || EndsWithPath(Value(m, "path") as string, wanted)).ToList();
                if (candidates.Count > 1) throw Failure("Object name is ambiguous: " + string.Join(", ", candidates.Select(m => Convert.ToString(Value(m, "path")) + "")) + "; pass --path");
                match = candidates.FirstOrDefault();
                guid = Convert.ToString(Value(match, "guid")) ?? "";
            }
            if (match == null) throw Failure("Object not found");
            var objName = Convert.ToString(Value(match, "name")) ?? name;
            var objPath = Convert.ToString(Value(match, "path")) ?? "";
            var objType = Convert.ToString(Value(match, "type")) ?? "";
            var data = new Dictionary<string, object> { { "name", objName }, { "path", objPath }, { "type", objType }, { "guid", Normalize(guid) } };
            var objectText = call.Call("objects.text", new Dictionary<string, object> { { "guid", guid } });
            foreach (var key in new[] { "declaration", "implementation" }) if (objectText.ContainsKey(key) && objectText[key] != null) data[key] = objectText[key];
            if (!o.Params.ContainsKey("body") && !o.Params.ContainsKey("body_file")) return data;
            var root = call.Hello.SyncFolder;
            if (string.IsNullOrWhiteSpace(root))
            {
                var status = call.Call("project.status", new Dictionary<string, object>());
                root = Convert.ToString(Value(status, "sync_folder"));
            }
            if (string.IsNullOrWhiteSpace(root)) throw Failure("no sync folder: run cts set-sync-folder");
            var temp = Path.Combine(Path.GetTempPath(), "cts-read-object-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(temp);
            try
            {
                var snapshot = Path.Combine(temp, "object.xml");
                var tree = call.Call("project.tree", new Dictionary<string, object>());
                var guids = Subtree(tree, Normalize(guid));
                if (guids.Count == 0) guids.Add(guid);
                call.Call("project.export", new Dictionary<string, object> { { "path", snapshot }, { "guids", guids.ToArray() } });
                var output = new MemoryViewFiles();
                ViewExport.WriteTo(snapshot, root, new Dictionary<string, object>(), output);
                var basis = Parts(objPath).LastOrDefault() ?? objName;
                if (basis.Contains('.')) basis = basis.Split('.').First();
                // A container with no text form (a folder, the Visualization Manager) is its folder's .cds-object.xml.
                var relative = output.Paths.FirstOrDefault(path => Path.GetFileName(path).Equals(basis + ".st", StringComparison.OrdinalIgnoreCase))
                    ?? output.Paths.FirstOrDefault(path => Path.GetFileName(path).Equals(basis + ".xml", StringComparison.OrdinalIgnoreCase))
                    ?? output.Paths.FirstOrDefault(path => Path.GetFileName(path).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase)
                        && Path.GetFileName(Path.GetDirectoryName(path)).Equals(basis, StringComparison.OrdinalIgnoreCase));
                if (relative == null) throw Failure("the export writes no file for " + objName);
                var body = new UTF8Encoding(false).GetString(output.Read(relative));
                if (o.Params.ContainsKey("body_file"))
                {
                    var target = Path.GetFullPath(Convert.ToString(o.Params["body_file"]));
                    File.WriteAllText(target, body, new UTF8Encoding(false));
                    return new Dictionary<string, object> { { "name", objName }, { "path", target }, { "body_format", Path.GetExtension(relative).TrimStart('.') }, { "size", Encoding.UTF8.GetByteCount(body) } };
                }
                return new Dictionary<string, object> { { "raw_body", body } };
            }
            finally { try { Directory.Delete(temp, true); } catch (IOException) { } catch (UnauthorizedAccessException) { } }
        }

        internal static Answer Build(IDictionary<string, object> data)
        {
            if (data.ContainsKey("body_format")) return new Answer().Add("name", data["name"]).Add("path", data["path"]);
            return new Answer().Add("name", data["name"]).Add("path", data["path"])
                .Detail(data.ContainsKey("declaration") ? data["declaration"] : null).Detail(data.ContainsKey("implementation") ? data["implementation"] : null);
        }

        static CliFailure Failure(string message) => new CliFailure("read-object", "refused", message, "cts read-object --help", 1);
        static List<string> Subtree(IDictionary<string, object> node, string wanted)
        {
            var output = new List<string>();
            if (node == null) return output;
            if (Normalize(Value(node, "guid")) == wanted) Visit(node, output);
            else if (Value(node, "children") is IEnumerable<object> children)
                foreach (var child in children.OfType<IDictionary<string, object>>()) output.AddRange(Subtree(child, wanted));
            return output;
        }
        static void Visit(IDictionary<string, object> node, List<string> output)
        {
            var guid = Convert.ToString(Value(node, "guid"));
            if (!string.IsNullOrEmpty(guid)) output.Add(guid);
            if (Value(node, "children") is IEnumerable<object> children)
                foreach (var child in children.OfType<IDictionary<string, object>>()) Visit(child, output);
        }
        static string Normalize(object g) => Convert.ToString(g)?.Trim().Trim('{', '}').ToLowerInvariant() ?? "";
        static List<string> Parts(string p) => (p ?? "").Replace('\\', '/').Trim('/').Split(new[] { '/' }, StringSplitOptions.RemoveEmptyEntries).ToList();
        static bool EndsWithPath(string path, string wanted) => (path ?? "").Replace('\\', '/').Trim('/').EndsWith(wanted, StringComparison.OrdinalIgnoreCase);
    }
}
