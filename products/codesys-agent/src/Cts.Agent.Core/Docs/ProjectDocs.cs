using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;
using Cts.Agent;
using Cts.Analysis;

namespace Cts.Docs
{
    // One documented object of the project: a POU, GVL, DUT or interface, or
    // a method, property or action of one (Owner set, listed in its Members).
    internal sealed class DocSymbol
    {
        internal string Kind, Name, Path, Description = "", Extends = "", BaseType = "", Card;
        internal int Line;
        // Excluded from the build in the IDE: CODESYS does not compile it.
        internal bool Excluded;
        internal DocSymbol Owner;
        internal readonly List<string> Implements = new List<string>();
        internal readonly List<InterfaceRow> Interface = new List<InterfaceRow>();
        internal readonly List<InterfaceRow> Inherited = new List<InterfaceRow>();
        internal readonly List<DocSymbol> Members = new List<DocSymbol>();
        internal readonly SortedSet<string> Calls = new SortedSet<string>(StringComparer.Ordinal);
        internal readonly SortedSet<string> CalledBy = new SortedSet<string>(StringComparer.Ordinal);
        internal readonly SortedSet<string> Tasks = new SortedSet<string>(StringComparer.Ordinal);
        internal readonly SortedSet<string> Reads = new SortedSet<string>(StringComparer.Ordinal);
        internal readonly SortedSet<string> Writes = new SortedSet<string>(StringComparer.Ordinal);
        // A GVL's: who reads and who writes its variables.
        internal readonly SortedSet<string> ReadBy = new SortedSet<string>(StringComparer.Ordinal);
        internal readonly SortedSet<string> WrittenBy = new SortedSet<string>(StringComparer.Ordinal);
    }

    // The project's objects from the sync folder's .st files: header,
    // doc comment and interface of each, who calls whom, the tasks that
    // reach it, the globals it reads and writes, and what a function block
    // or structure inherits. Implementation text is never copied.
    internal static class ProjectDocs
    {
        static readonly Dictionary<string, string> KindNames = new Dictionary<string, string>
        {
            [Kinds.Program] = "PROGRAM", [Kinds.FunctionBlock] = "FUNCTION_BLOCK", [Kinds.Function] = "FUNCTION", [Kinds.Method] = "METHOD",
            [Kinds.Action] = "ACTION", [Kinds.PropertyGet] = "PROPERTY", [Kinds.PropertySet] = "PROPERTY", [Kinds.Interface] = "INTERFACE",
            [Kinds.Gvl] = "GVL", [Kinds.GvlPersistent] = "GVL", [Kinds.Struct] = "STRUCT", [Kinds.Union] = "UNION", [Kinds.Enum] = "ENUM",
            [Kinds.Alias] = "ALIAS", [Kinds.Unknown] = "UNKNOWN",
        };

        // The top-level objects, by name, each with its members; library
        // names a call the project does not resolve ("Name (Library
        // Version)", or the name with "not found").
        internal static List<DocSymbol> Build(Snapshot snapshot, Func<string, string> library)
        {
            var byKey = new Dictionary<string, DocSymbol>(StringComparer.OrdinalIgnoreCase);
            var all = new List<DocSymbol>();
            var files = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var unit in snapshot.Units)
            {
                if (IsAccessor(unit))
                {
                    if (!byKey.TryGetValue(unit.OwnerName, out var property))
                    {
                        property = Property(snapshot, unit, files);
                        byKey[unit.OwnerName] = property;
                        all.Add(property);
                    }
                    byKey[unit.QualifiedName] = property;
                    continue;
                }
                var symbol = FromUnit(unit);
                if (!byKey.ContainsKey(unit.QualifiedName)) byKey[unit.QualifiedName] = symbol;
                all.Add(symbol);
            }
            var tops = new List<DocSymbol>();
            foreach (var symbol in all)
            {
                var dot = symbol.Name.LastIndexOf('.');
                var owner = dot > 0 ? all.Where(candidate => candidate != symbol && candidate.Name.Equals(symbol.Name.Substring(0, dot), StringComparison.OrdinalIgnoreCase))
                    .OrderBy(candidate => candidate.Path == symbol.Path ? 0 : 1).FirstOrDefault() : null;
                if (owner == null) tops.Add(symbol);
                else
                {
                    symbol.Owner = owner;
                    owner.Members.Add(symbol);
                }
            }
            Relate(snapshot, byKey, library);
            Inherit(tops);
            var cards = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var symbol in tops.OrderBy(symbol => symbol.Name, StringComparer.OrdinalIgnoreCase).ThenBy(symbol => symbol.Path, StringComparer.Ordinal))
            {
                var slug = Regex.Replace(symbol.Name, @"[^A-Za-z0-9._-]", "_");
                var card = slug + ".md";
                for (var count = 2; !cards.Add(card); count++) card = slug + "-" + count + ".md";
                symbol.Card = card;
            }
            return tops.OrderBy(symbol => symbol.Card, StringComparer.OrdinalIgnoreCase).ToList();
        }

        // A property's GET or SET: the property (its owner name) is the
        // symbol; the accessors only add its relations.
        static bool IsAccessor(Unit unit) => (unit.Kind == Kinds.PropertyGet || unit.Kind == Kinds.PropertySet) && unit.OwnerName != null
            && Regex.IsMatch(unit.QualifiedName, @"\.(?:Get|Set)$", RegexOptions.IgnoreCase);

        static DocSymbol FromUnit(Unit unit)
        {
            var text = unit.Text ?? "";
            var header = StDeclarations.Header.Match(StText.Blank(text));
            var start = header.Success ? header.Index : 0;
            var symbol = new DocSymbol
            {
                Kind = KindNames.TryGetValue(unit.Kind, out var kind) ? kind : unit.Kind.ToUpperInvariant(), Name = unit.QualifiedName, Path = unit.SourcePath,
                Line = unit.LineBase + StText.LineColumn(text, start).Key, Description = Description(text, start), Excluded = unit.ExcludedFromBuild,
            };
            if (Kinds.Type.Contains(unit.Kind) && unit.Dut != null)
            {
                symbol.Extends = unit.Dut.Extends ?? "";
                symbol.BaseType = unit.Dut.Base ?? "";
                foreach (var field in unit.Dut.Fields.Where(field => !string.IsNullOrEmpty(field.Name)))
                    symbol.Interface.Add(new InterfaceRow { Scope = "FIELD", Name = field.Name, Type = field.Type ?? "", Initial = field.Initial ?? "", Comment = field.Comment ?? "" });
                return symbol;
            }
            var returns = header.Success && header.Groups["type"].Success ? header.Groups["type"].Value.Trim().TrimEnd(';').Trim() : "";
            if (returns.Length > 0 && (unit.Kind == Kinds.Function || unit.Kind == Kinds.Method)) symbol.Interface.Add(new InterfaceRow { Scope = "Return", Type = returns });
            foreach (var member in unit.Members().Where(member => member.Name.Length > 0))
                symbol.Interface.Add(new InterfaceRow { Scope = member.Scope, Name = member.Name, Type = member.Type, Initial = member.Initial ?? "", Comment = StDeclarations.MemberComment(unit.Declaration, member.Name) });
            var pou = StDeclarations.PouHeader(unit.Declaration);
            symbol.Extends = pou.Key;
            symbol.Implements.AddRange(pou.Value);
            return symbol;
        }

        // A property from its header in the file ("PROPERTY P_Open : BOOL").
        static DocSymbol Property(Snapshot snapshot, Unit accessor, Dictionary<string, string> files)
        {
            if (!files.TryGetValue(accessor.SourcePath, out var text))
            {
                try
                {
                    text = StText.Lf(File.ReadAllText(System.IO.Path.Combine(snapshot.Root, accessor.SourcePath), Encoding.UTF8));
                }
                catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
                {
                    text = "";
                }
                files[accessor.SourcePath] = text;
            }
            var name = Snapshot.LastSegment(accessor.OwnerName);
            var header = StDeclarations.Header.Matches(StText.Blank(text)).Cast<Match>()
                .FirstOrDefault(match => match.Groups["kind"].Value.Equals("PROPERTY", StringComparison.OrdinalIgnoreCase) && match.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase));
            var symbol = new DocSymbol { Kind = "PROPERTY", Name = accessor.OwnerName, Path = accessor.SourcePath, Line = accessor.LineBase };
            if (header == null) return symbol;
            symbol.Line = StText.LineColumn(text, header.Index).Key;
            symbol.Description = Description(text, header.Index);
            var type = header.Groups["type"].Value.Trim().TrimEnd(';').Trim();
            if (type.Length > 0) symbol.Interface.Add(new InterfaceRow { Scope = "Return", Type = type });
            return symbol;
        }

        // "40 function blocks": *count* objects of *kind* (FUNCTION_BLOCK, PROPERTY...).
        internal static string Many(int count, string kind)
        {
            var noun = kind.ToLowerInvariant().Replace('_', ' ');
            return count + " " + (noun.EndsWith("y") ? noun.Substring(0, noun.Length - 1) + "ies" : noun + "s");
        }

        // The doc comment of the object whose header starts at start: the
        // comment on the header line or right after it, else the run of comments
        // right before the header (a (* *) block and a // note above a
        // method both belong to it). The implementation marker, cts:
        // directives and the cts pragma line are not documentation.
        internal static string Description(string text, int start)
        {
            var comments = Merged(text, StText.Comments(text).Where(comment => !IsMachineComment(comment.Content)).ToList());
            // Pragmas ({attribute ...}) between a comment and the header do not part them.
            var blanked = StText.Blank(text);
            var lineEnd = text.IndexOf('\n', start);
            if (lineEnd < 0) lineEnd = text.Length;
            var after = comments.FirstOrDefault(comment => comment.Start > start && blanked.Substring(lineEnd, Math.Max(0, comment.Start - lineEnd)).Trim().Length == 0);
            if (after != null) return Clean(after.Content);
            var before = new List<string>();
            var boundary = start;
            foreach (var comment in Enumerable.Reverse(comments))
            {
                if (comment.End > boundary) continue;
                if (blanked.Substring(comment.End, boundary - comment.End).Trim().Length > 0) break;
                before.Insert(0, Clean(comment.Content));
                boundary = comment.Start;
            }
            return Clean(string.Join("\n", before));
        }

        static bool IsMachineComment(string content)
        {
            var text = content.Trim();
            return text == "--- implementation ---" || text.StartsWith("cts:", StringComparison.OrdinalIgnoreCase) || text.StartsWith("cds-text-sync:", StringComparison.OrdinalIgnoreCase);
        }

        // Consecutive // lines (one line break apart) are one comment.
        static List<StText.Comment> Merged(string text, List<StText.Comment> comments)
        {
            var merged = new List<StText.Comment>();
            for (var i = 0; i < comments.Count; i++)
            {
                var comment = comments[i];
                if (!Line(text, comment))
                {
                    merged.Add(comment);
                    continue;
                }
                var content = new List<string> { comment.Content };
                var end = comment.End;
                while (i + 1 < comments.Count && Line(text, comments[i + 1]))
                {
                    var gap = text.Substring(end, comments[i + 1].Start - end);
                    if (gap.Trim().Length > 0 || gap.Count(c => c == '\n') != 1) break;
                    content.Add(comments[++i].Content);
                    end = comments[i].End;
                }
                merged.Add(new StText.Comment { Start = comment.Start, End = end, Content = string.Join("\n", content) });
            }
            return merged;
        }

        static bool Line(string text, StText.Comment comment) => string.CompareOrdinal(text, comment.Start, "//", 0, 2) == 0;

        // A comment's lines without the leading "*" or "//" and one space,
        // blank lines around dropped, dedented.
        static string Clean(string content)
        {
            var lines = (content ?? "").Split('\n').Select(raw =>
            {
                var line = raw.Trim();
                if (line.StartsWith("*", StringComparison.Ordinal)) line = line.Substring(1);
                else line = line.TrimStart('/');
                if (line.StartsWith(" ", StringComparison.Ordinal)) line = line.Substring(1);
                return line.TrimEnd();
            }).SkipWhile(line => line.Length == 0).ToList();
            while (lines.Count > 0 && lines[lines.Count - 1].Length == 0) lines.RemoveAt(lines.Count - 1);
            if (lines.Count == 0) return "";
            var cut = lines.Where(line => line.Length > 0).Min(line => line.Length - line.TrimStart().Length);
            return string.Join("\n", lines.Select(line => line.Length > 0 ? line.Substring(cut) : ""));
        }

        // Calls (resolved, library, unresolved), the tasks that reach each
        // object through the calls from their programs, and global access.
        static void Relate(Snapshot snapshot, Dictionary<string, DocSymbol> byKey, Func<string, string> library)
        {
            var graph = new ExecutionGraph(snapshot);
            DocSymbol Symbol(string key) => byKey.TryGetValue(key, out var symbol) ? symbol : null;
            foreach (var calls in graph.Calls)
            {
                var caller = Symbol(calls.Key);
                if (caller == null) continue;
                foreach (var callee in calls.Value.Select(Symbol).Where(callee => callee != null && callee != caller))
                {
                    caller.Calls.Add(callee.Name);
                    callee.CalledBy.Add(caller.Name);
                }
            }
            foreach (var outside in graph.Unresolved.Concat(graph.LibraryCalls))
            {
                var caller = Symbol(outside.Key);
                if (caller != null) caller.Calls.UnionWith(outside.Value.Select(library));
            }
            foreach (var task in TaskRoots(snapshot.Root))
            {
                var queue = new Queue<string>(task.Value.Select(graph.Resolve).Where(root => root != null));
                var seen = new HashSet<string>();
                while (queue.Count > 0)
                {
                    var current = queue.Dequeue();
                    if (!seen.Add(current)) continue;
                    Symbol(current)?.Tasks.Add(task.Key);
                    if (graph.Calls.TryGetValue(current, out var callees)) foreach (var callee in callees) queue.Enqueue(callee);
                }
            }
            var globals = new GlobalAccessIndex(snapshot);
            foreach (var unit in snapshot.Units)
            {
                var symbol = Symbol(unit.QualifiedName);
                if (symbol == null) continue;
                foreach (var access in globals.AccessesFor(unit))
                {
                    (access.Write ? symbol.Writes : symbol.Reads).Add(access.Global.QualifiedName + "." + access.Member.Name);
                    var list = Symbol(access.Global.QualifiedName);
                    if (list != null && list != symbol) (access.Write ? list.WrittenBy : list.ReadBy).Add(symbol.Name);
                }
            }
        }

        // Each task (its file's name) with the programs it calls, from the
        // task configuration's XML (PouList).
        internal static Dictionary<string, List<string>> TaskRoots(string view)
        {
            var tasks = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            foreach (var path in Directory.EnumerateFiles(view, "*.xml", SearchOption.AllDirectories).OrderBy(path => path, StringComparer.Ordinal))
            {
                try
                {
                    if (!File.ReadAllText(path).Contains("\"PouList\"")) continue;
                    var names = XDocument.Load(path).Descendants().Where(element => (string)element.Attribute("Name") == "PouList")
                        .SelectMany(list => list.Descendants().Where(element => (string)element.Attribute("Name") == "Name").Select(element => element.Value.Trim()))
                        .Where(name => name.Length > 0).ToList();
                    if (names.Count > 0) tasks[System.IO.Path.GetFileNameWithoutExtension(path)] = names;
                }
                catch (Exception error) when (error is XmlException || error is IOException || error is UnauthorizedAccessException)
                {
                }
            }
            return tasks;
        }

        // A function block or structure inherits its base's variables and
        // methods (the base's own inheritance included); a base outside the
        // project, or one seen before (a cycle the compiler refuses), ends
        // the chain.
        static void Inherit(List<DocSymbol> tops)
        {
            var byName = new Dictionary<string, DocSymbol>(StringComparer.OrdinalIgnoreCase);
            foreach (var symbol in tops) if (!byName.ContainsKey(symbol.Name)) byName[symbol.Name] = symbol;
            foreach (var symbol in tops)
            {
                var seen = new HashSet<DocSymbol> { symbol };
                for (var current = symbol; byName.TryGetValue(current.Extends, out var parent) && seen.Add(parent); current = parent)
                {
                    symbol.Inherited.AddRange(parent.Interface.Where(row => row.Name.Length > 0).Select(row => new InterfaceRow { Scope = row.Scope, Name = row.Name, Type = row.Type, From = parent.Name }));
                    symbol.Inherited.AddRange(parent.Members.Select(member => new InterfaceRow { Scope = member.Kind, Name = Snapshot.LastSegment(member.Name), From = parent.Name }));
                }
            }
        }
    }
}
