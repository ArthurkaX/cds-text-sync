using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Sync;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    internal static class NewObjectCommand
    {
        internal static readonly IList<CliOption> Options = new[] {
            CliOption.Text("--sync-folder", "sync_folder", "PATH", "Sync folder (default: search upward)"),
            CliOption.Text("--parent", "parent", "PATH", "Folder in the view; . is the project root (the POUs view, shared by every application); default: the Application folder"),
            CliOption.Text("--text", "text", "TEXT", "The body; for a POU or method, VAR...END_VAR blocks at its start go into the declaration"),
            CliOption.Text("--text-file", "text_file", "PATH", "Read declaration or implementation from a file"),
            CliOption.Text("--kind", "kind", "KIND", "POU kind or DUT kind"),
            CliOption.Text("--return-type", "return_type", "TYPE", "Function or method return type"),
            CliOption.Text("--base-type", "base_type", "TYPE", "Target type for an alias"),
            CliOption.Text("--type", "return_type", "TYPE", "Property type"),
            CliOption.Text("--language", "language", "LANGUAGE", "Text language (st)"),
            CliOption.Text("--get-text", "get_text", "TEXT", "Property GET body"),
            CliOption.Text("--set-text", "set_text", "TEXT", "Property SET body"),
        };
        static readonly string[] Kinds = { "gvl", "pou", "dut", "method", "action", "property" };

        internal static IDictionary<string, object> Execute(CliOptions o, string work)
        {
            var kind = o.Arguments.ElementAtOrDefault(0) ?? "";
            var name = o.Arguments.ElementAtOrDefault(1) ?? "";
            var folder = o.Text("sync_folder", "");
            if (string.IsNullOrWhiteSpace(folder)) folder = ViewFolder.Around(work) ?? throw Refuse("no sync folder; pass --sync-folder or run cts set-sync-folder");
            if (!Directory.Exists(folder)) throw Refuse("no such folder: " + Path.GetFullPath(folder));
            folder = ViewFolder.Named(folder);
            var view = ViewFolder.Of(folder);
            var body = o.Text("text", "");
            var textFile = o.Text("text_file", "");
            if (!string.IsNullOrEmpty(textFile)) body = File.ReadAllText(textFile, Encoding.UTF8);
            var parent = o.Text("parent", "");
            if (string.IsNullOrEmpty(parent))
            {
                if (!Directory.Exists(view)) throw Refuse("no view root at " + view + "; export the project once first");
                var application = Directory.GetDirectories(view, "Application", SearchOption.AllDirectories)
                    .OrderBy(p => p.Substring(view.Length).Count(c => c == Path.DirectorySeparatorChar)).ThenBy(p => p, StringComparer.OrdinalIgnoreCase).FirstOrDefault();
                if (application == null) throw Refuse("the view has no Application folder; pass --parent <path>");
                parent = application.Substring(view.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/');
            }
            parent = parent == "." || parent == "/" ? "" : parent.Replace('\\', '/').Trim('/');
            if (parent.Split('/').Any(p => p == "..")) throw Refuse("parent path may not leave the view");
            var member = kind == "method" || kind == "action" || kind == "property";
            string owner = null, objectName = name;
            if (member) { var parts = name.Split('.'); if (parts.Length != 2) throw Refuse("a member name must be <POU>.<Member>"); owner = parts[0]; objectName = parts[1]; }
            if (!Regex.IsMatch(objectName, "^[A-Za-z_][A-Za-z0-9_]*$") || Regex.IsMatch(objectName, "^(PROGRAM|FUNCTION|FUNCTION_BLOCK|TYPE|VAR|VAR_GLOBAL|END_VAR)$", RegexOptions.IgnoreCase))
                throw Refuse("invalid or reserved IEC identifier: " + objectName);
            if (!Kinds.Contains(kind)) throw Refuse("kind must be gvl, pou, dut, method, action or property");
            if (kind == "pou" && !new[] { "program", "function", "function-block" }.Contains(o.Text("kind", ""))) throw Refuse("a POU needs --kind program, function or function-block");
            if (kind == "dut" && !new[] { "struct", "union", "enum", "alias" }.Contains(o.Text("kind", ""))) throw Refuse("a DUT needs --kind struct, union, enum or alias");
            if (member && o.Text("parent", "").Length > 0) throw Refuse("a member goes into its POU's file; --parent is not used");
            if (o.Text("language", "").Length > 0 && o.Text("language", "") != "st") throw Refuse("only Structured Text is supported (--language st)");
            var relative = member ? owner + ".st" : (parent.Length == 0 ? "" : parent + "/") + objectName + ".st";
            var path = member
                ? Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).OrderBy(p => p, StringComparer.OrdinalIgnoreCase).FirstOrDefault(p => string.Equals(Path.GetFileName(p), owner + ".st", StringComparison.OrdinalIgnoreCase))
                : PathSafety.SafePath(view, relative);
            if (path == null) throw Refuse(member ? "no POU file found for " + owner : "object path leaves the view");
            relative = path.Substring(Path.GetFullPath(view).TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/');
            if (member) parent = Path.GetDirectoryName(relative)?.Replace('/', '/') ?? "";
            var destinationDir = Path.GetDirectoryName(path);
            if (!Directory.Exists(destinationDir)) throw Refuse("parent folder does not exist in the view: " + parent);
            if (!member && Directory.GetFileSystemEntries(destinationDir).Any(entry => string.Equals(Path.GetFileNameWithoutExtension(entry), objectName, StringComparison.OrdinalIgnoreCase)))
                throw Refuse("object already exists in " + parent + ": " + objectName);
            string content;
            string reportedBody;
            if (member)
            {
                if (!File.Exists(path)) throw Refuse("owner POU file not found: " + path);
                var old = File.ReadAllText(path, Encoding.UTF8);
                if (Regex.IsMatch(old, @"\b" + Regex.Escape(objectName) + @"\b", RegexOptions.IgnoreCase)) throw Refuse("object already exists: " + name);
                var ret = o.Text("return_type", "");
                var isInterface = Regex.IsMatch(old, @"^\s*INTERFACE\b", RegexOptions.IgnoreCase);
                var methodParts = Split(body);
                content = kind == "method" ? "METHOD " + objectName + " : " + (ret.Length == 0 ? "BOOL" : ret) + (methodParts.Key.Length == 0 ? "" : "\n" + methodParts.Key) + (isInterface ? "\nEND_METHOD" : "\n" + StPragma.ImplementationMarker + (methodParts.Value.Length == 0 ? "" : "\n" + methodParts.Value) + "\nEND_METHOD")
                    : kind == "action" ? "ACTION " + objectName + ":" + (body.Length == 0 ? "" : "\n" + body.Trim('\n')) + "\nEND_ACTION"
                    : "PROPERTY " + objectName + " : " + (ret.Length == 0 ? "BOOL" : ret) + "\nGET\n" + StPragma.ImplementationMarker + (o.Text("get_text", "").Length == 0 ? "" : "\n" + o.Text("get_text", "").Trim('\n')) + "\nEND_GET\nSET\n" + StPragma.ImplementationMarker + (o.Text("set_text", "").Length == 0 ? "" : "\n" + o.Text("set_text", "").Trim('\n')) + "\nEND_SET\nEND_PROPERTY";
                content = Aligned(content);
                reportedBody = content;
                content = old.TrimEnd('\r', '\n') + "\n\n" + content + "\n";
                File.WriteAllText(path, content, new UTF8Encoding(false));
            }
            else
            {
                if (File.Exists(path)) throw Refuse("object already exists: " + path);
                if (kind == "gvl") content = Regex.IsMatch(body, @"^\s*VAR_GLOBAL\b", RegexOptions.IgnoreCase) ? body.TrimEnd('\n') + "\n" : "VAR_GLOBAL\n" + string.Join("\n", body.Split('\n').Where(s => s.Trim().Length > 0).Select(s => "    " + s.Trim())) + "\nEND_VAR\n";
                else if (kind == "pou") { var pk = o.Text("kind", ""); var head = pk == "function" ? "FUNCTION " + objectName + " : " + (o.Text("return_type", "").Length == 0 ? "BOOL" : o.Text("return_type", "")) : pk == "function-block" ? "FUNCTION_BLOCK " + objectName : "PROGRAM " + objectName; var end = pk == "function" ? "END_FUNCTION" : pk == "function-block" ? "END_FUNCTION_BLOCK" : "END_PROGRAM"; var parts = Split(body); content = head + "\n" + (parts.Key.Length == 0 ? "VAR\nEND_VAR" : parts.Key) + "\n" + StPragma.ImplementationMarker + (parts.Value.Length == 0 ? "" : "\n" + parts.Value) + "\n" + end + "\n"; }
                else { var dk = o.Text("kind", ""); if (dk == "alias" && string.IsNullOrWhiteSpace(o.Text("base_type", ""))) throw Refuse("an ALIAS needs --base-type"); content = dk == "alias" ? "TYPE " + objectName + " : " + o.Text("base_type", "") + ";\nEND_TYPE\n" : dk == "enum" && body.Trim().Length == 0 ? "TYPE " + objectName + " :\n(\n    Member1 := 0\n);\nEND_TYPE\n" : "TYPE " + objectName + " :\n" + (dk == "enum" ? "(\n" + body + "\n);" : dk == "union" ? "UNION\n" + body + "\nEND_UNION" : "STRUCT\n" + body + "\nEND_STRUCT") + "\nEND_TYPE\n"; }
                content = Aligned(content);
                reportedBody = content;
                File.WriteAllText(path, content, new UTF8Encoding(false));
            }
            var hint = member
                ? (kind == "property" ? "Read or write " + owner + "." + objectName + " from code the task reaches, or the PLC never runs its accessors." : "Call " + owner + "." + objectName + "() from code the task reaches, or the PLC never runs it.")
                : parent.Length == 0 ? "At the project root it is shared by every application: an application gets it once code its task calls uses it; to test it, call it from the test program and run cts test (cts guide tests)."
                : kind == "dut" ? "Reference it from a variable in code the task calls, or the PLC never gets it."
                : "Reference it from a POU the task calls, or the PLC never gets it (for a GVL, add e.g. " + objectName + ".x; to MAIN).";
            var result = new Dictionary<string, object> {
                { "kind", kind }, { "name", objectName }, { "parent", parent }, { "view_root", Path.GetFullPath(view) },
                { "path", relative }, { "files", new List<string> { path } }, { "type_guid", TypeKinds.All.TypeGuid(kind) },
                { "bytes", Encoding.UTF8.GetByteCount(reportedBody) }, { "next", new List<string> { "cts compare", "cts import", "cts build --all-objects  # checks it while nothing calls it yet; a plain build leaves it out" } }, { "hint", hint },
            };
            if (member) result["owner"] = owner;
            if (!member && kind == "pou" && Split(body).Value.Length == 0) result["note"] = "The POU was created with an empty body; add statements between the implementation marker and its END line before importing.";
            if (!member && kind == "dut" && o.Text("kind", "") == "enum" && body.Trim().Length == 0) result["note"] = "The empty enum was seeded with one member (Member1 := 0) because an enum with no members is not valid IEC; rename or replace it.";
            return result;
        }

        // The declaration's tables aligned as cts fmt aligns them, so a new
        // object starts clean of CTS0008.
        static string Aligned(string content)
        {
            var marker = content.IndexOf(StPragma.ImplementationMarker, StringComparison.Ordinal);
            return marker < 0 ? StFormatter.Format(content, true) : StFormatter.Format(content.Substring(0, marker), true) + content.Substring(marker);
        }

        internal static Answer Build(IDictionary<string, object> data)
        {
            var answer = new Answer();
            if (data.ContainsKey("path")) answer.Detail("Created " + data["path"]);
            if (data.TryGetValue("next", out var next) && next is IList<string> steps)
                foreach (var step in steps) answer.Detail("Next: " + step);
            return answer.Detail(Value(data, "hint")).Detail(Value(data, "note"));
        }
        // A POU's or method's --text as {declaration, implementation}: the
        // VAR...END_VAR blocks it starts with are declaration, the rest is code.
        internal static KeyValuePair<string, string> Split(string body)
        {
            var blocks = Regex.Match(body, @"^\s*(?:VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_STAT|_INST)?\b.*?\bEND_VAR\b[ \t]*\r?\n?\s*)+",
                RegexOptions.Singleline | RegexOptions.IgnoreCase);
            var declaration = blocks.Success ? Layout(blocks.Value.Trim()) : "";
            return new KeyValuePair<string, string>(declaration, body.Substring(blocks.Success ? blocks.Length : 0).Trim('\r', '\n'));
        }

        // VAR blocks typed on one line, one declaration per line as the export
        // writes them; a text with a line break, a comment, a string or a
        // pragma is the caller's layout and stays as it is.
        static string Layout(string declaration)
        {
            if (Regex.IsMatch(declaration, @"[\r\n'""{]|\(\*|//")) return declaration;
            return Regex.Replace(declaration, @"\b(VAR\w*(?:\s+(?:CONSTANT|RETAIN|PERSISTENT))*)\s+(.*?)\s*\bEND_VAR\b\s*", block =>
                block.Groups[1].Value + "\n" + string.Concat(block.Groups[2].Value.Split(';').Select(item => item.Trim()).Where(item => item.Length > 0)
                    .Select(item => "\t" + item + ";\n")) + "END_VAR\n", RegexOptions.IgnoreCase).TrimEnd('\n');
        }

        static CliFailure Refuse(string message) => new CliFailure("new", "refused", message, "cts new --help", 1);
    }
}
