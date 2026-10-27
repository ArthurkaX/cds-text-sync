using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Analysis;

namespace Cts.Docs
{
    // The project's function blocks, interfaces, structures and programs as a
    // mermaid classDiagram: what a block extends and implements, the blocks
    // and structures it holds (composition) and the ones it only points to
    // (a POINTER, REFERENCE, VAR_IN_OUT or interface variable: association).
    // A class shows its inputs, outputs, methods and properties, not its
    // internals.  The whole project is too much for one picture: without a
    // name it is the inheritance alone, the classes without members.  Around
    // a name, a line joins classes a step apart, never two neighbours; many
    // classes tied to one class alone and the same way are one list.
    internal static class ClassDiagram
    {
        //: Lines a class lists before "... N more".
        const int MostLines = 12;
        //: Member names a line carries before "+N".
        const int MostLabels = 3;
        //: Classes tied to one class the same way before they become one list.
        const int MostFan = 8;
        //: Names a list shows before "... N more".
        const int MostNames = 20;
        static readonly string[] Kinds = { "FUNCTION_BLOCK", "INTERFACE", "STRUCT", "UNION", "PROGRAM" };
        static readonly string[] Shown = { "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "FIELD" };
        static readonly Regex Array = new Regex(@"^ARRAY\s*\[(?<bounds>[^\]]*)\]\s*OF\s+", RegexOptions.IgnoreCase);
        static readonly Regex Pointer = new Regex(@"^(?:POINTER|REFERENCE)\s+TO\s+", RegexOptions.IgnoreCase);
        static readonly Regex TypeName = new Regex(@"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*");

        internal sealed class Relation
        {
            internal string From, To, Arrow, Label;
        }

        // The diagram of *symbols* (ProjectDocs), *name*'s neighbourhood up to
        // *depth* relations away when a name is given, else every class that
        // extends, implements or is extended; null when no class is named *name*.
        internal static Dictionary<string, object> Render(List<DocSymbol> symbols, string name, int depth)
        {
            var classes = new Dictionary<string, DocSymbol>(StringComparer.OrdinalIgnoreCase);
            foreach (var symbol in symbols.Where(symbol => Kinds.Contains(symbol.Kind) && !symbol.Excluded))
                if (!classes.ContainsKey(symbol.Name)) classes[symbol.Name] = symbol;
            var whole = string.IsNullOrEmpty(name);
            var relations = Relations(classes).Where(relation => !whole || relation.Label.Length == 0).ToList();
            // Each drawn class's steps from *name*; a line joins two a step apart.
            var steps = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            if (!whole)
            {
                if (!classes.TryGetValue(name, out var start)) return null;
                steps[start.Name] = 0;
                var frontier = new List<string> { start.Name };
                for (var step = 1; step <= depth && frontier.Count > 0; step++)
                {
                    var next = relations.SelectMany(relation => frontier.Contains(relation.From, StringComparer.OrdinalIgnoreCase) ? new[] { relation.To }
                        : frontier.Contains(relation.To, StringComparer.OrdinalIgnoreCase) ? new[] { relation.From } : new string[0])
                        .Where(found => !steps.ContainsKey(found)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                    foreach (var found in next) steps[found] = step;
                    frontier = next;
                }
            }
            else foreach (var end in relations.SelectMany(relation => new[] { relation.From, relation.To })) steps[end] = 0;
            // One line per pair and kind: a block holding three buffers draws one
            // line, not three on top of each other.
            var edges = relations.Where(relation => steps.ContainsKey(relation.From) && steps.ContainsKey(relation.To) && (whole || steps[relation.From] != steps[relation.To]))
                .GroupBy(relation => relation.From + " " + relation.Arrow + " " + relation.To, StringComparer.OrdinalIgnoreCase)
                .Select(group => new Relation { From = group.First().From, To = group.First().To, Arrow = group.First().Arrow, Label = Labels(group.Select(relation => relation.Label).ToList()) })
                .ToList();
            // Forty blocks holding one structure: one list of the forty, the
            // member each holds it by after its name.
            var ends = edges.SelectMany(edge => new[] { edge.From, edge.To }).GroupBy(end => end, StringComparer.OrdinalIgnoreCase).ToDictionary(group => group.Key, group => group.Count(), StringComparer.OrdinalIgnoreCase);
            bool Leaf(string end) => ends[end] == 1 && (whole || steps[end] > 0);
            var fans = edges.Where(edge => Leaf(edge.From) != Leaf(edge.To))
                .GroupBy(edge => Leaf(edge.From) ? edge.Arrow + " " + edge.To + " " + classes[edge.From].Kind : edge.From + " " + edge.Arrow + " " + classes[edge.To].Kind, StringComparer.OrdinalIgnoreCase)
                .Where(fan => fan.Count() > MostFan).ToList();
            var listed = new HashSet<Relation>(fans.SelectMany(fan => fan));
            var inLists = new HashSet<string>(listed.Select(edge => Leaf(edge.From) ? edge.From : edge.To), StringComparer.OrdinalIgnoreCase);
            var lines = new List<string> { "classDiagram" };
            foreach (var key in steps.Keys.Where(key => !inLists.Contains(key)).OrderBy(key => key, StringComparer.OrdinalIgnoreCase))
                lines.AddRange(Class(classes[key], !whole));
            var listLines = new List<string>();
            foreach (var fan in fans)
            {
                var first = fan.First();
                var outward = Leaf(first.From);
                // Two underscores: no ST name has them.
                var id = "list__" + (listLines.Count + 1);
                var names = fan.Select(edge => (outward ? edge.From : edge.To) + (edge.Label.Length > 0 ? " : " + edge.Label : "")).ToList();
                lines.Add("    class " + id + "[\"" + ProjectDocs.Many(names.Count, classes[outward ? first.From : first.To].Kind) + "\"] {");
                lines.AddRange(names.Take(MostNames).Select(line => "        " + line));
                if (names.Count > MostNames) lines.Add("        ... " + (names.Count - MostNames) + " more");
                lines.Add("    }");
                listLines.Add("    " + (outward ? id : Id(first.From)) + " " + first.Arrow + " " + (outward ? Id(first.To) : id));
            }
            lines.AddRange(edges.Where(edge => !listed.Contains(edge)).Select(edge => "    " + Id(edge.From) + " " + edge.Arrow + " " + Id(edge.To) + (edge.Label.Length > 0 ? " : " + edge.Label : "")));
            lines.AddRange(listLines);
            return new Dictionary<string, object>
            {
                ["classes"] = steps.Count,
                ["relations"] = edges.Count,
                ["left_out"] = whole ? classes.Count - steps.Count : 0,
                // An empty classDiagram is a mermaid syntax error.
                ["mermaid"] = steps.Count > 0 ? string.Join("\n", lines) : "",
            };
        }

        // Inheritance first, then what each class holds, by member order.
        static List<Relation> Relations(Dictionary<string, DocSymbol> classes)
        {
            var relations = new List<Relation>();
            foreach (var symbol in classes.Values.OrderBy(symbol => symbol.Name, StringComparer.OrdinalIgnoreCase))
            {
                if (Find(classes, symbol.Extends) is DocSymbol parent) relations.Add(new Relation { From = parent.Name, To = symbol.Name, Arrow = "<|--", Label = "" });
                foreach (var face in symbol.Implements.Select(face => Find(classes, face)).Where(face => face != null))
                    relations.Add(new Relation { From = face.Name, To = symbol.Name, Arrow = "<|..", Label = "" });
                foreach (var row in symbol.Interface.Where(row => row.Name.Length > 0 && row.Scope != "VAR_TEMP" && row.Scope != "Return"))
                {
                    var type = row.Type.Trim();
                    var array = Array.Match(type);
                    var label = row.Name + (array.Success ? "[" + array.Groups["bounds"].Value.Trim() + "]" : "");
                    if (array.Success) type = type.Substring(array.Length);
                    var pointer = Pointer.Match(type);
                    if (pointer.Success) type = type.Substring(pointer.Length);
                    var held = Find(classes, TypeName.Match(type).Value);
                    if (held == null || held == symbol) continue;
                    var loose = pointer.Success || row.Scope == "VAR_IN_OUT" || held.Kind == "INTERFACE";
                    relations.Add(new Relation { From = symbol.Name, To = held.Name, Arrow = loose ? "-->" : "*--", Label = label });
                }
            }
            return relations;
        }

        static string Labels(List<string> labels) =>
            string.Join(", ", labels.Take(MostLabels)) + (labels.Count > MostLabels ? " +" + (labels.Count - MostLabels) : "");

        static DocSymbol Find(Dictionary<string, DocSymbol> classes, string name)
        {
            if (string.IsNullOrEmpty(name)) return null;
            return classes.TryGetValue(name, out var found) || classes.TryGetValue(Snapshot.LastSegment(name), out found) ? found : null;
        }

        // A class with its stereotype and, with *members*, its inputs and
        // outputs, methods and properties.
        static IEnumerable<string> Class(DocSymbol symbol, bool members)
        {
            var id = Id(symbol.Name);
            var body = new List<string>();
            if (symbol.Kind != "FUNCTION_BLOCK") body.Add("<<" + symbol.Kind.ToLowerInvariant().Replace('_', ' ') + ">>");
            var rows = !members ? new List<string>() : symbol.Interface.Where(row => row.Name.Length > 0 && Shown.Contains(row.Scope))
                .Select(row => (row.Scope == "VAR_INPUT" ? "+in " : row.Scope == "VAR_OUTPUT" ? "+out " : row.Scope == "VAR_IN_OUT" ? "+inout " : "+") + row.Name + " : " + Plain(row.Type))
                .Concat(symbol.Members.Where(member => member.Kind == "METHOD" || member.Kind == "PROPERTY").Select(member =>
                {
                    var returns = member.Interface.FirstOrDefault(row => row.Scope == "Return")?.Type ?? "";
                    var shortName = Snapshot.LastSegment(member.Name);
                    return member.Kind == "METHOD" ? "+" + shortName + "()" + (returns.Length > 0 ? " " + Plain(returns) : "") : "+prop " + shortName + " : " + Plain(returns);
                })).ToList();
            body.AddRange(rows.Take(MostLines));
            if (rows.Count > MostLines) body.Add("... " + (rows.Count - MostLines) + " more");
            var head = "    class " + id + (id != symbol.Name ? "[\"" + symbol.Name + "\"]" : "");
            if (body.Count == 0) return new[] { head };
            return new[] { head + " {" }.Concat(body.Select(line => "        " + line)).Concat(new[] { "    }" });
        }

        // A mermaid class id: letters, digits and underscores.
        static string Id(string name) => Regex.Replace(name, @"\W", "_");

        // A type as a member line can carry: mermaid reads a line with
        // parentheses as a method, ~ as a generic and a trailing * or $ as a
        // classifier.  STRING[80] is CODESYS's other spelling of STRING(80).
        static string Plain(string type) => StText.Squeezed(type ?? "").Replace('(', '[').Replace(')', ']').Replace("~", "-").TrimEnd('*', '$', ';');
    }
}
