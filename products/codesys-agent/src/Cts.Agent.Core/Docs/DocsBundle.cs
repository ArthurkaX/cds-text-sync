using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Analysis;

namespace Cts.Docs
{
    // A referenced library and what became of it: its LibDoc tree and
    // symbols, or why there is none.
    internal sealed class LibraryEntry
    {
        internal LibraryReference Reference;
        internal LibDocTree Tree;
        internal List<LibrarySymbol> Symbols = new List<LibrarySymbol>();
        internal string Missing;

        internal string File => Slug(Reference.Name) + "-" + Slug(Tree.Version) + ".md";

        internal static string Slug(string value) => Regex.Replace(value ?? "", @"[^A-Za-z0-9._-]", "_");
    }

    // `cts docs`: the bundle under .cts-docs/ an AI agent reads instead of
    // the sources: one markdown file per project object and per referenced
    // library, index.md, symbols.jsonl and manifest.json. Generated, so git
    // ignores it; the input fingerprint tells a stale bundle.
    internal static class DocsBundle
    {
        internal const string DefaultLibraries = @"C:\ProgramData\CODESYS";
        const string Format = "cts-docs/v4";

        internal static IDictionary<string, object> Generate(string view, string libraries, string output)
        {
            var references = LibraryReferences.Read(view, out var gap);
            var entries = Libraries(references, libraries);
            var candidates = new Dictionary<string, SortedSet<string>>(StringComparer.OrdinalIgnoreCase);
            foreach (var entry in entries.Where(entry => entry.Tree != null))
                foreach (var symbol in entry.Symbols)
                {
                    var label = symbol.Name + " (" + entry.Reference.Name + " " + entry.Tree.Version + ")";
                    // A call names a library symbol bare, by its namespace or
                    // by its library's name.
                    foreach (var key in new[] { symbol.Name, entry.Reference.Namespace + "." + symbol.Name, entry.Reference.Name + "." + symbol.Name }.Where(key => !key.StartsWith(".", StringComparison.Ordinal)))
                    {
                        if (!candidates.TryGetValue(key, out var set)) candidates[key] = set = new SortedSet<string>(StringComparer.Ordinal);
                        set.Add(label);
                    }
                }
            string Library(string name)
            {
                if (!candidates.TryGetValue(name, out var found) && name.Contains(".")) candidates.TryGetValue(Snapshot.LastSegment(name), out found);
                if (found == null) return name;
                return found.Count == 1 ? found.First() : name + " (one of: " + string.Join(", ", found) + ")";
            }
            var project = ProjectDocs.Build(Snapshot.Read(view), Library);
            var unreferenced = LibDoc.Unreferenced(libraries, references);
            var documented = entries.Where(entry => entry.Tree != null).ToList();
            // Several placeholders can resolve to one library version: one page.
            var pages = documented.GroupBy(entry => entry.File, StringComparer.OrdinalIgnoreCase).Select(page => page.ToList()).ToList();
            var missing = entries.Where(entry => entry.Tree == null).ToList();
            var manifest = new Dictionary<string, object>
            {
                ["format"] = Format,
                ["generated_at"] = DateTime.UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ", CultureInfo.InvariantCulture),
                ["project_view"] = view,
                ["libraries"] = libraries,
                ["fingerprint"] = Fingerprint(view, entries),
                ["counts"] = new Dictionary<string, object>
                {
                    ["objects"] = project.Count,
                    ["symbols"] = project.Sum(symbol => 1 + symbol.Members.Count),
                    ["library_symbols"] = pages.Sum(page => page[0].Symbols.Count),
                    ["libraries_referenced"] = entries.Count,
                    ["libraries_documented"] = documented.Count,
                    ["libraries_missing"] = missing.Count,
                    ["libraries_not_referenced"] = unreferenced.Count,
                },
                ["missing"] = missing.Select(entry => (object)new Dictionary<string, object>
                {
                    ["name"] = entry.Reference.Name, ["version"] = entry.Reference.Version, ["vendor"] = entry.Reference.Vendor,
                    ["placeholder"] = entry.Reference.Placeholder, ["kind"] = entry.Reference.Kind, ["reason"] = entry.Missing,
                }).ToList(),
                ["gaps"] = gap == null ? new List<object>() : new List<object> { gap },
            };
            Publish(output, staging =>
            {
                Directory.CreateDirectory(Path.Combine(staging, "project"));
                Directory.CreateDirectory(Path.Combine(staging, "libraries"));
                foreach (var symbol in project) Write(Path.Combine(staging, "project", symbol.Card), Card(symbol, project));
                foreach (var page in pages) Write(Path.Combine(staging, "libraries", page[0].File), LibraryPage(page));
                Write(Path.Combine(staging, "libraries", "not-referenced.md"), NotReferenced(unreferenced));
                Write(Path.Combine(staging, "index.md"), Index(view, libraries, project, pages, missing, unreferenced.Count, gap));
                Write(Path.Combine(staging, "symbols.jsonl"), string.Concat(Rows(project, pages.Select(page => page[0])).Select(row => Json.Serialize(row) + "\n")));
                Write(Path.Combine(staging, "manifest.json"), Json.Pretty(manifest) + "\n");
            });
            return new Dictionary<string, object> { ["output"] = output, ["manifest"] = manifest };
        }

        // Whether the bundle was written from the sources as they are now.
        internal static IDictionary<string, object> Check(string view, string libraries, string output)
        {
            var data = new Dictionary<string, object> { ["output"] = output };
            string recorded;
            try
            {
                var manifest = Json.Parse(File.ReadAllText(Path.Combine(output, "manifest.json"), Encoding.UTF8)) as IDictionary<string, object>;
                recorded = manifest != null && manifest.TryGetValue("fingerprint", out var value) ? value as string : null;
                if (libraries == null && manifest != null && manifest.TryGetValue("libraries", out var root)) libraries = root as string;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is JsonException)
            {
                data["state"] = "unreadable";
                data["error"] = error.Message;
                return data;
            }
            if (recorded == null)
            {
                data["state"] = "unreadable";
                data["error"] = "manifest.json has no fingerprint (written by an older cts docs)";
                return data;
            }
            var actual = Fingerprint(view, Libraries(LibraryReferences.Read(view, out _), libraries ?? DefaultLibraries, false));
            data["state"] = actual == recorded ? "fresh" : "stale";
            data["recorded"] = recorded;
            data["actual"] = actual;
            return data;
        }

        static List<LibraryEntry> Libraries(List<LibraryReference> references, string libraries, bool parse = true)
        {
            return references.Select(reference =>
            {
                var entry = new LibraryEntry { Reference = reference, Tree = LibDoc.Find(libraries, reference) };
                if (entry.Tree == null) entry.Missing = LibDoc.MissingReason(libraries, reference);
                else if (parse) entry.Symbols = LibDoc.Symbols(entry.Tree);
                return entry;
            }).ToList();
        }

        // The project's .st files, each library reference and where it was
        // found (or why not), and the LibDoc pages read.
        static string Fingerprint(string view, List<LibraryEntry> entries)
        {
            var lines = new List<string>();
            foreach (var path in Directory.EnumerateFiles(view, "*.st", SearchOption.AllDirectories))
            {
                var relative = path.Substring(view.Length).TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar).Replace('\\', '/');
                if (relative.Split('/').Reverse().Skip(1).Any(part => part.StartsWith(".", StringComparison.Ordinal))) continue;
                lines.Add("project\t" + relative + "\t" + Hash(path));
            }
            foreach (var entry in entries)
            {
                var reference = entry.Reference;
                var head = "library\t" + reference.Kind + "\t" + reference.Name + "\t" + reference.Version + "\t" + reference.Vendor + "\t" + reference.Namespace + "\t";
                if (entry.Tree == null)
                {
                    lines.Add(head + "missing " + entry.Missing);
                    continue;
                }
                lines.Add(head + entry.Tree.Path + "\t" + Hash(Path.Combine(entry.Tree.Path, "manifest.json")));
                lines.AddRange(entry.Tree.Pages.Select(page => "page\t" + entry.Tree.Path + "\t" + page + "\t" + Hash(Path.Combine(entry.Tree.Path, page))));
            }
            lines.Sort(StringComparer.Ordinal);
            using (var sha = SHA256.Create())
                return string.Concat(sha.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n", lines))).Select(b => b.ToString("x2", CultureInfo.InvariantCulture)));
        }

        static string Hash(string path)
        {
            try
            {
                using (var sha = SHA256.Create())
                using (var stream = File.OpenRead(path))
                    return string.Concat(sha.ComputeHash(stream).Select(b => b.ToString("x2", CultureInfo.InvariantCulture)));
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
            {
                return "unreadable";
            }
        }

        // The bundle is written beside the output folder and then takes its
        // place, so a failed run leaves the previous bundle as it was.
        static void Publish(string output, Action<string> write)
        {
            var parent = Path.GetDirectoryName(Path.GetFullPath(output));
            Directory.CreateDirectory(parent);
            var name = Path.GetFileName(Path.GetFullPath(output));
            var staging = Path.Combine(parent, "." + name + ".staging-" + Path.GetRandomFileName());
            var previous = Path.Combine(parent, "." + name + ".previous-" + Path.GetRandomFileName());
            try
            {
                write(staging);
                if (Directory.Exists(output)) Directory.Move(output, previous);
                try
                {
                    Directory.Move(staging, output);
                }
                catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
                {
                    // Some mounts let a folder be created but not renamed.
                    Copy(staging, output);
                }
            }
            catch
            {
                if (Directory.Exists(previous) && !Directory.Exists(output)) Directory.Move(previous, output);
                throw;
            }
            finally
            {
                if (Directory.Exists(staging)) Directory.Delete(staging, true);
                if (Directory.Exists(previous)) Directory.Delete(previous, true);
            }
        }

        static void Copy(string from, string to)
        {
            Directory.CreateDirectory(to);
            foreach (var file in Directory.GetFiles(from)) File.Copy(file, Path.Combine(to, Path.GetFileName(file)), true);
            foreach (var folder in Directory.GetDirectories(from)) Copy(folder, Path.Combine(to, Path.GetFileName(folder)));
        }

        static void Write(string path, string text) => File.WriteAllText(path, text, new UTF8Encoding(false));

        static string Index(string view, string libraries, List<DocSymbol> project, List<List<LibraryEntry>> pages, List<LibraryEntry> missing, int unreferenced, string gap)
        {
            var text = new StringBuilder();
            text.Append("# Project documentation\n\n");
            text.Append("Written by `cts docs` from `" + view + "`, libraries from `" + libraries + "`; `manifest.json` says when.\n");
            text.Append("One file per project object under `project/`, one per library under `libraries/`; `symbols.jsonl` holds every symbol as one JSON line, to search.\n\n");
            text.Append("## Project objects\n\n");
            if (project.Count == 0) text.Append("_None._\n");
            else
            {
                text.Append("| Kind | Name | File |\n|---|---|---|\n");
                foreach (var symbol in project) text.Append("| " + symbol.Kind + " | [" + Cell(symbol.Name) + "](project/" + symbol.Card + ") | `" + Cell(symbol.Path) + "` |\n");
            }
            text.Append("\n## Libraries\n\n");
            if (pages.Count == 0) text.Append("_None documented._\n");
            else
            {
                text.Append("| Library | Version | Vendor | Namespace | System | Symbols |\n|---|---|---|---|---|---:|\n");
                foreach (var page in pages)
                {
                    var entry = page[0];
                    text.Append("| [" + Cell(entry.Reference.Name) + "](libraries/" + entry.File + ") | " + entry.Tree.Version + " | " + Cell(entry.Reference.Vendor) + " | "
                        + Cell(Joined(page, reference => reference.Namespace)) + " | " + Joined(page, reference => reference.System ? "yes" : "no") + " | " + entry.Symbols.Count + " |\n");
                }
            }
            text.Append("\n## Missing LibDoc\n\n");
            if (missing.Count == 0) text.Append("_None._\n");
            else
            {
                text.Append("Referenced by the project, but no documentation of that version is installed on this machine: install it, or ask the user about the reference. Another version is never documented in its place.\n\n");
                text.Append("| Library | Version | Vendor | Placeholder | Reason |\n|---|---|---|---|---|\n");
                foreach (var entry in missing)
                    text.Append("| " + Cell(entry.Reference.Name) + " | " + Cell(entry.Reference.Version) + " | " + Cell(entry.Reference.Vendor) + " | " + Cell(entry.Reference.Placeholder) + " | " + entry.Missing + " |\n");
            }
            text.Append("\n## Not referenced\n\n" + unreferenced + " installed libraries the project does not reference: [libraries/not-referenced.md](libraries/not-referenced.md).\n");
            if (gap != null) text.Append("\n## Gaps\n\n- " + gap + "\n");
            return text.ToString();
        }

        static string Card(DocSymbol symbol, List<DocSymbol> project)
        {
            var cards = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var top in project) if (!cards.ContainsKey(top.Name)) cards[top.Name] = top.Card;
            string Link(string name) => cards.TryGetValue(name, out var card) ? "[" + name + "](" + card + ")" : "`" + name + "`";
            var text = new StringBuilder();
            text.Append("# " + symbol.Kind + " " + symbol.Name + "\n\n`" + symbol.Path + "` line " + symbol.Line + "\n\n" + Excluded(symbol));
            if (symbol.Description.Length > 0) text.Append(symbol.Description + "\n\n");
            var declared = new List<string>();
            if (symbol.Extends.Length > 0) declared.Add("- EXTENDS " + Link(symbol.Extends));
            if (symbol.Implements.Count > 0) declared.Add("- IMPLEMENTS " + string.Join(", ", symbol.Implements.Select(Link)));
            if (symbol.BaseType.Length > 0) declared.Add("- Base type: `" + symbol.BaseType + "`");
            if (declared.Count > 0) text.Append(string.Join("\n", declared) + "\n\n");
            Table(text, symbol.Interface);
            if (symbol.Inherited.Count > 0)
            {
                text.Append("Inherited:\n\n| Scope | Name | Type | From |\n|---|---|---|---|\n");
                foreach (var row in symbol.Inherited) text.Append("| " + Cell(row.Scope) + " | " + Cell(row.Name) + " | " + Cell(row.Type) + " | " + Link(row.From) + " |\n");
                text.Append("\n");
            }
            Relations(text, symbol);
            foreach (var member in symbol.Members.OrderBy(member => KindOrder(member.Kind)).ThenBy(member => member.Name, StringComparer.OrdinalIgnoreCase))
            {
                text.Append("## " + member.Kind + " " + Snapshot.LastSegment(member.Name) + "\n\nline " + member.Line + "\n\n" + Excluded(member));
                if (member.Description.Length > 0) text.Append(member.Description + "\n\n");
                Table(text, member.Interface);
                Relations(text, member);
            }
            return text.ToString().TrimEnd('\n') + "\n";
        }

        static string Excluded(DocSymbol symbol) => symbol.Excluded ? "Excluded from build: CODESYS does not compile it.\n\n" : "";

        static int KindOrder(string kind) => kind == "PROPERTY" ? 0 : kind == "METHOD" ? 1 : 2;

        static void Relations(StringBuilder text, DocSymbol symbol)
        {
            var lines = new List<string>();
            void Add(string label, SortedSet<string> names)
            {
                if (names.Count > 0) lines.Add("- " + label + ": " + string.Join(", ", names.Select(name => "`" + name + "`")));
            }
            Add("Calls", symbol.Calls);
            Add("Called by", symbol.CalledBy);
            Add("Tasks", symbol.Tasks);
            Add("Reads", symbol.Reads);
            Add("Writes", symbol.Writes);
            Add("Read by", symbol.ReadBy);
            Add("Written by", symbol.WrittenBy);
            if (lines.Count > 0) text.Append(string.Join("\n", lines) + "\n\n");
        }

        static void Table(StringBuilder text, List<InterfaceRow> rows)
        {
            if (rows.Count == 0) return;
            text.Append("| Scope | Name | Type | Initial | Comment |\n|---|---|---|---|---|\n");
            foreach (var row in rows) text.Append("| " + Cell(row.Scope) + " | " + Cell(row.Name) + " | " + Cell(row.Type) + " | " + Cell(row.Initial) + " | " + Cell(row.Comment) + " |\n");
            text.Append("\n");
        }

        static string Cell(string value) => (value ?? "").Replace("\r", "").Replace("\n", " ").Replace("|", "\\|");

        // The distinct non-empty values of a page's references, in order.
        static string Joined(List<LibraryEntry> page, Func<LibraryReference, string> value)
            => string.Join(", ", page.Select(entry => value(entry.Reference)).Where(text => text.Length > 0).Distinct());

        static string LibraryPage(List<LibraryEntry> page)
        {
            var entry = page[0];
            var reference = entry.Reference;
            var text = new StringBuilder();
            text.Append("# " + reference.Name + " " + entry.Tree.Version + "\n\n");
            text.Append("- Vendor: `" + (reference.Vendor.Length > 0 ? reference.Vendor : entry.Tree.Vendor) + "`\n");
            var namespaces = Joined(page, item => item.Namespace.Length > 0 ? "`" + item.Namespace + "`" : "");
            if (namespaces.Length > 0) text.Append("- Namespace: " + namespaces + "\n");
            text.Append("- Reference: " + Joined(page, item => item.Kind + (item.Placeholder.Length > 0 ? " `" + item.Placeholder + "`" : "")) + "\n");
            text.Append("- " + Joined(page, item => item.System ? "System library" : "Application library") + "\n");
            text.Append("- LibDoc: `" + entry.Tree.Path + "`\n\n");
            if (entry.Symbols.Count == 0) text.Append("_No documented symbols in this LibDoc tree._\n\n");
            foreach (var symbol in entry.Symbols)
            {
                text.Append("## " + (symbol.Kind.Length > 0 ? symbol.Kind + " " : "") + symbol.Name + "\n\n");
                if (symbol.Signature.Length > 0) text.Append("```st\n" + symbol.Signature + "\n```\n\n");
                if (symbol.Description.Length > 0) text.Append(symbol.Description + "\n\n");
                foreach (var example in symbol.Examples) text.Append("```st\n" + example + "\n```\n\n");
                Table(text, symbol.Interface);
            }
            return text.ToString().TrimEnd('\n') + "\n";
        }

        static string NotReferenced(SortedDictionary<string, SortedSet<string>> libraries)
        {
            var text = new StringBuilder("# Installed libraries the project does not reference\n\n");
            if (libraries.Count == 0) return text.Append("_None._\n").ToString();
            text.Append("| Library | Versions |\n|---|---|\n");
            foreach (var library in libraries) text.Append("| " + Cell(library.Key) + " | " + string.Join(", ", library.Value) + " |\n");
            return text.ToString();
        }

        // One JSON object per symbol: the project's objects with their
        // members, then the libraries'. Empty fields are left out.
        static IEnumerable<IDictionary<string, object>> Rows(List<DocSymbol> project, IEnumerable<LibraryEntry> documented)
        {
            foreach (var top in project)
                foreach (var symbol in new[] { top }.Concat(top.Members.OrderBy(member => member.Name, StringComparer.OrdinalIgnoreCase)))
                {
                    var row = new Dictionary<string, object>
                    {
                        ["source"] = "project", ["kind"] = symbol.Kind, ["name"] = symbol.Name, ["file"] = symbol.Path, ["line"] = symbol.Line,
                        ["card"] = "project/" + top.Card,
                    };
                    if (symbol.Owner != null) row["owner"] = symbol.Owner.Name;
                    if (symbol.Excluded) row["excluded_from_build"] = true;
                    Optional(row, "description", symbol.Description);
                    Optional(row, "extends", symbol.Extends);
                    if (symbol.Implements.Count > 0) row["implements"] = symbol.Implements.Cast<object>().ToList();
                    Optional(row, "base_type", symbol.BaseType);
                    if (symbol.Interface.Count > 0) row["interface"] = symbol.Interface.Select(Interface).ToList();
                    if (symbol.Inherited.Count > 0) row["inherited"] = symbol.Inherited.Select(member => (object)new Dictionary<string, object> { ["scope"] = member.Scope, ["name"] = member.Name, ["type"] = member.Type, ["from"] = member.From }).ToList();
                    Names(row, "calls", symbol.Calls);
                    Names(row, "called_by", symbol.CalledBy);
                    Names(row, "tasks", symbol.Tasks);
                    Names(row, "reads", symbol.Reads);
                    Names(row, "writes", symbol.Writes);
                    Names(row, "read_by", symbol.ReadBy);
                    Names(row, "written_by", symbol.WrittenBy);
                    yield return row;
                }
            foreach (var entry in documented)
                foreach (var symbol in entry.Symbols)
                {
                    var row = new Dictionary<string, object>
                    {
                        ["source"] = "library", ["library"] = entry.Reference.Name, ["version"] = entry.Tree.Version, ["kind"] = symbol.Kind, ["name"] = symbol.Name,
                        ["card"] = "libraries/" + entry.File,
                    };
                    Optional(row, "signature", symbol.Signature);
                    Optional(row, "description", symbol.Description);
                    if (symbol.Interface.Count > 0) row["interface"] = symbol.Interface.Select(Interface).ToList();
                    yield return row;
                }
        }

        static object Interface(InterfaceRow row)
        {
            var item = new Dictionary<string, object> { ["scope"] = row.Scope };
            Optional(item, "name", row.Name);
            Optional(item, "type", row.Type);
            Optional(item, "initial", row.Initial);
            Optional(item, "comment", row.Comment);
            return item;
        }

        static void Optional(Dictionary<string, object> row, string key, string value)
        {
            if (!string.IsNullOrEmpty(value)) row[key] = value;
        }

        static void Names(Dictionary<string, object> row, string key, SortedSet<string> names)
        {
            if (names.Count > 0) row[key] = names.Cast<object>().ToList();
        }
    }
}
