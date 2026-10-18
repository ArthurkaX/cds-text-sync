using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    internal static class FsmDetector
    {
        static readonly Regex Token = new Regex(@"\b(?:IF|CASE|FOR|WHILE|REPEAT|ELSIF|ELSE|END_IF|END_CASE|END_FOR|END_WHILE|END_REPEAT|UNTIL|THEN|DO|TO|BY|OF)\b|[^\s:=\n]+(?:\s*,\s*[^\s:=\n]+)*\s*:(?!=)", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        static readonly Regex Head = new Regex(@"^[A-Za-z_][\w.\[\]]*$", RegexOptions.Compiled);
        static readonly Regex Assignment = new Regex(@"([A-Za-z_][\w.\[\]]*)\s*:=", RegexOptions.Compiled);
        static readonly Regex NumericLabel = new Regex(@"^(\d+|16#[0-9A-Fa-f]+)$", RegexOptions.Compiled);
        static readonly Regex NotSimple = new Regex(@"^NOT\s+([A-Za-z_][\w.\[\]]*)$", RegexOptions.IgnoreCase | RegexOptions.Compiled);
        static readonly Regex Simple = new Regex(@"^[A-Za-z_][\w.\[\]]*$", RegexOptions.Compiled);

        static readonly string[] Opens = { "IF", "CASE", "FOR", "WHILE", "REPEAT" };
        static readonly Dictionary<string, string> Closes = new Dictionary<string, string> { ["END_IF"] = "IF", ["END_CASE"] = "CASE", ["END_FOR"] = "FOR", ["END_WHILE"] = "WHILE", ["END_REPEAT"] = "REPEAT" };

        sealed class Block
        {
            internal string Kind, Header;
            internal int Start, End;
            internal Block Parent;
            internal readonly List<Block> Children = new List<Block>();
            internal readonly List<Tuple<string, int, int>> Branches = new List<Tuple<string, int, int>>();
            internal int Pending = -1;
            internal string PendingLabel;
            internal bool InLabels;
        }
        sealed class State { internal string Label; internal string[] Aliases; internal int Start, End, Order; }
        sealed class Edge { internal string Source, Target, Guard; internal int Offset, BlockStart = -1, BlockEnd = -1; internal bool Deferred, Else; }
        sealed class AssignmentInfo { internal string Lhs; internal int Offset, RhsStart, RhsEnd; }

        internal static List<Dictionary<string, object>> Machines(string source)
        {
            var text = source ?? "";
            var work = Blank(text);
            var root = Scan(work);
            var assignments = CollectAssignments(work);
            var result = new List<Dictionary<string, object>>();
            foreach (var site in Cases(root))
            {
                var local = site.Start;
                var of = Regex.Match(work.Substring(Math.Min(work.Length, local + 4)), @"\bOF\b", RegexOptions.IgnoreCase);
                if (!of.Success) continue;
                var selector = text.Substring(local + 4, of.Index).Trim();
                if (!Head.IsMatch(selector)) continue;
                var caseStart = local + 4 + of.Index + 2;
                var caseEnd = site.End < 0 ? work.Length : site.End - 8;
                var states = new List<State>();
                foreach (var branch in site.Branches)
                {
                    if (branch.Item1.Equals("ELSE", StringComparison.OrdinalIgnoreCase)) continue;
                    var aliases = branch.Item1.Split(',').Select(value => value.Trim()).Where(value => value.Length > 0).ToArray();
                    states.Add(new State { Label = branch.Item1, Aliases = aliases, Start = branch.Item2, End = branch.Item3, Order = states.Count });
                }
                if (states.Count == 0) continue;
                var labelSet = new HashSet<string>(states.SelectMany(state => state.Aliases), StringComparer.OrdinalIgnoreCase);
                var edges = new List<Edge>();
                var warnings = new List<Tuple<int, string>>();
                var commits = new List<int>();
                foreach (var assignment in assignments.Where(item => FsmRules.SameFamily(item.Lhs, selector)))
                {
                    var rhs = work.Substring(assignment.RhsStart, assignment.RhsEnd - assignment.RhsStart).Trim();
                    var rhsRaw = text.Substring(assignment.RhsStart, assignment.RhsEnd - assignment.RhsStart).Trim();
                    if (labelSet.Contains(rhs))
                    {
                        var target = states.First(state => state.Aliases.Any(alias => alias.Equals(rhs, StringComparison.OrdinalIgnoreCase))).Label;
                        var sourceState = states.FirstOrDefault(state => assignment.Offset >= state.Start && assignment.Offset < state.End);
                        var edge = new Edge { Source = sourceState?.Label, Target = target, Offset = assignment.Offset, Deferred = !assignment.Lhs.Equals(selector, StringComparison.OrdinalIgnoreCase) };
                        edge.Else = sourceState == null && site.Branches.Any(branch => branch.Item1.Equals("ELSE", StringComparison.OrdinalIgnoreCase)
                            && assignment.Offset >= branch.Item2 && assignment.Offset < branch.Item3);
                        edge.Guard = GuardFor(root, site, assignment.Offset);
                        var span = ActionSpan(root, site, assignment.Offset);
                        edge.BlockStart = span.Item1; edge.BlockEnd = span.Item2;
                        edges.Add(edge);
                    }
                    else if (FsmRules.Normalize(rhs) == FsmRules.Normalize(selector) && FsmRules.SameFamily(rhs, selector))
                        commits.Add(assignment.Offset);
                    else warnings.Add(Tuple.Create(assignment.Offset, "assigns " + rhsRaw + " to the state variable but no branch handles it"));
                }
                if (!edges.Any(edge => edge.Source != null)) continue;
                // Code outside the CASE runs whatever the state, so its transitions leave every other state.
                foreach (var state in states)
                    if (!edges.Any(edge => edge.Source == state.Label || edge.Source == null && !edge.Else && edge.Target != state.Label)) warnings.Add(Tuple.Create(state.Start, "state " + state.Label + " has no outgoing transition"));
                foreach (var state in states.Where(state => state.Order != 0))
                    if (!edges.Any(edge => edge.Target == state.Label)) warnings.Add(Tuple.Create(state.Start, "state " + state.Label + " is never entered"));
                result.Add(Payload(text, selector, states, edges, warnings));
            }
            return result;
        }

        // The state *machine* starts in: its selector's initial value in
        // *declaration*, else an integer's 0, as a state label; null when the
        // declaration does not say or the value names no state.  *basis* says
        // which of the two it is.
        internal static string Initial(string declaration, Dictionary<string, object> machine, out string basis)
        {
            basis = null;
            var selector = Convert.ToString(machine["selector"]);
            if (!Simple.IsMatch(selector) || selector.Contains('.') || selector.Contains('[')) return null;
            var work = Blank(declaration ?? "");
            var declared = Regex.Match(work, @"(?:^|[;\n(])\s*" + Regex.Escape(selector) + @"\s*:\s*([A-Za-z_][\w.]*)\s*(?::=\s*([^;]+?))?\s*;", RegexOptions.IgnoreCase);
            if (!declared.Success) return null;
            var value = declared.Groups[2].Success ? declared.Groups[2].Value.Trim() : Integers.Contains(declared.Groups[1].Value) ? "0" : null;
            if (value == null) return null;
            basis = declared.Groups[2].Success ? "its declared value" : declared.Groups[1].Value.ToUpperInvariant() + "'s default 0";
            var labels = ((List<Dictionary<string, object>>)machine["states"]).Select(state => Convert.ToString(state["label"])).ToList();
            var named = labels.FirstOrDefault(label => label.Split(',').Any(alias => alias.Trim().Equals(value, StringComparison.OrdinalIgnoreCase)));
            if (named != null || !NumericLabel.IsMatch(value)) return named;
            // A number: the state whose constant in the same declaration holds it.
            return labels.FirstOrDefault(label => label.Split(',').Any(alias => Regex.IsMatch(work,
                @"(?:^|[;\n])\s*" + Regex.Escape(alias.Trim()) + @"\s*:\s*[A-Za-z_]\w*\s*:=\s*" + Regex.Escape(value) + @"\s*;", RegexOptions.IgnoreCase)));
        }
        static readonly HashSet<string> Integers = new HashSet<string>(new[] { "SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT", "BYTE", "WORD", "DWORD", "LWORD" }, StringComparer.OrdinalIgnoreCase);

        static Block Scan(string text)
        {
            var root = new Block { Kind = "ROOT", Start = 0 };
            var stack = new List<Block> { root };
            foreach (Match match in Token.Matches(text))
            {
                var word = match.Value.ToUpperInvariant();
                var top = stack[stack.Count - 1];
                if (Opens.Contains(word))
                {
                    var block = new Block { Kind = word, Start = match.Index, Parent = top };
                    top.Children.Add(block);
                    if (word == "IF" || word == "CASE") block.Pending = match.Index;
                    stack.Add(block); continue;
                }
                if (Closes.TryGetValue(word, out var opener))
                {
                    if (top.Kind == opener) { Finalize(top, match.Index); top.End = match.Index + match.Length; stack.RemoveAt(stack.Count - 1); }
                    continue;
                }
                if (word == "THEN" && top.Kind == "IF" && top.Pending >= 0) { top.Header = text.Substring(top.Pending, match.Index - top.Pending).Trim(); top.PendingLabel = top.Header; continue; }
                if (word == "OF" && top.Kind == "CASE") { top.InLabels = true; top.Pending = -1; continue; }
                if (word == "ELSE" || word == "ELSIF")
                {
                    if (top.Kind == "IF" || (top.Kind == "CASE" && word == "ELSE"))
                    { Finalize(top, match.Index); top.Pending = match.Index; top.PendingLabel = word == "ELSE" ? "ELSE" : null; }
                    continue;
                }
                if (top.Kind == "CASE" && top.InLabels) { Finalize(top, match.Index); top.Pending = match.Index; top.PendingLabel = match.Value.TrimEnd(':').Trim(); }
            }
            while (stack.Count > 1) { var block = stack[stack.Count - 1]; Finalize(block, text.Length); block.End = text.Length; stack.RemoveAt(stack.Count - 1); }
            return root;
        }
        static void Finalize(Block block, int end) { if (block.Pending >= 0) { block.Branches.Add(Tuple.Create(block.PendingLabel ?? "", block.Pending, end)); block.Pending = -1; } }
        static IEnumerable<Block> Cases(Block node) { if (node.Kind == "CASE") yield return node; foreach (var child in node.Children) foreach (var found in Cases(child)) yield return found; }

        static List<AssignmentInfo> CollectAssignments(string text)
        {
            var result = new List<AssignmentInfo>(); var start = 0;
            foreach (Match semi in Regex.Matches(text, @";"))
            {
                var segment = text.Substring(start, semi.Index - start); var leading = segment.Length - segment.TrimStart().Length;
                foreach (Match match in Assignment.Matches(segment))
                {
                    var before = match.Index - 1; while (before >= 0 && " \t\n".IndexOf(segment[before]) >= 0) before--;
                    if (before >= 0 && (segment[before] == '(' || segment[before] == ',')) continue;
                    result.Add(new AssignmentInfo { Lhs = match.Groups[1].Value, Offset = start + match.Groups[1].Index, RhsStart = start + match.Index + match.Length, RhsEnd = semi.Index });
                }
                start = semi.Index + 1;
            }
            return result;
        }

        static Block Innermost(Block node, int offset) { foreach (var child in node.Children) if (offset >= child.Start && offset < (child.End < 0 ? offset + 1 : child.End)) return Innermost(child, offset); return node; }
        static Tuple<int, int> BranchSpan(Block node, int offset) { var branch = node.Branches.FirstOrDefault(item => offset >= item.Item2 && offset < (item.Item3 <= 0 ? offset + 1 : item.Item3)); return branch == null ? null : Tuple.Create(branch.Item2, branch.Item3); }
        static Tuple<int, int> ActionSpan(Block root, Block site, int offset)
        {
            var node = Innermost(root, offset); if (node == site || node == root) return Tuple.Create(-1, -1);
            var branch = BranchSpan(node, offset); return branch ?? Tuple.Create(node.Start, node.End);
        }
        static string GuardFor(Block root, Block site, int offset)
        {
            var labels = new List<string>(); var node = Innermost(root, offset);
            while (node != null && node != root)
            {
                if (node.Kind == "IF") { var arm = ArmGuard(node, offset); if (!String.IsNullOrEmpty(arm)) labels.Add(arm); }
                if (node == site) break; node = node.Parent;
            }
            labels.Reverse(); return AllOf(labels);
        }
        static string ArmGuard(Block node, int offset)
        {
            var earlier = new List<string>();
            foreach (var item in node.Branches)
            {
                var label = Regex.Replace(item.Item1.Trim(), @"\s+", " ");
                string condition = label.StartsWith("IF", StringComparison.OrdinalIgnoreCase) ? Regex.Replace(label, @"^IF\b\s*", "", RegexOptions.IgnoreCase) : label.StartsWith("ELSIF", StringComparison.OrdinalIgnoreCase) ? Regex.Replace(label, @"^ELSIF\b\s*", "", RegexOptions.IgnoreCase) : null;
                if (offset >= item.Item2 && offset < (item.Item3 <= 0 ? offset + 1 : item.Item3)) return AllOf(earlier.Select(Negate).Concat(condition == null ? Enumerable.Empty<string>() : new[] { condition }).ToList());
                if (condition != null) earlier.Add(condition);
            }
            return null;
        }
        static string Negate(string value) { var match = NotSimple.Match(value); if (match.Success) return match.Groups[1].Value; return Simple.IsMatch(value) ? "NOT " + value : "NOT (" + value + ")"; }
        static string AllOf(IList<string> values) { if (values.Count == 0) return ""; if (values.Count == 1) return values[0]; return String.Join(" AND ", values.Select(value => Regex.IsMatch(value, @"\bOR\b", RegexOptions.IgnoreCase) && !value.StartsWith("NOT (") ? "(" + value + ")" : value)); }

        static Dictionary<string, object> Payload(string text, string selector, List<State> states, List<Edge> edges, List<Tuple<int, string>> warnings)
        {
            var stateRows = states.Select(state => { var cut = Cut(text, state.Start, state.End); return new Dictionary<string, object> { ["label"] = state.Label, ["code"] = cut.Item1, ["line"] = cut.Item2 }; }).ToList();
            var transitionRows = edges.Select(edge => { var start = edge.BlockStart < 0 ? edge.Offset : edge.BlockStart; var end = edge.BlockStart < 0 ? text.IndexOf(';', edge.Offset) + 1 : edge.BlockEnd; if (end <= start) end = text.Length; var cut = Cut(text, start, end); var row = new Dictionary<string, object> { ["source"] = edge.Source, ["target"] = edge.Target, ["guard"] = edge.Guard ?? "", ["code"] = cut.Item1, ["line"] = cut.Item2, ["block"] = edge.BlockStart >= 0 }; if (edge.Else) row["else"] = true; return row; }).ToList();
            return new Dictionary<string, object> { ["selector"] = selector, ["numeric"] = states.Count > 0 && states.All(state => NumericLabel.IsMatch(state.Label)), ["deferred"] = edges.Any(edge => edge.Deferred), ["warnings"] = warnings.Select(item => new Dictionary<string, object> { ["line"] = StText.LineColumn(text, item.Item1).Key, ["text"] = item.Item2 }).ToList(), ["states"] = stateRows, ["transitions"] = transitionRows };
        }
        static Tuple<string, int> Cut(string text, int start, int end)
        {
            start = Math.Max(0, start); end = end < 0 ? text.Length : Math.Min(text.Length, end);
            var lines = StText.Lf(text.Substring(start, Math.Max(0, end - start))).Split('\n').ToList();
            while (lines.Count > 0 && String.IsNullOrWhiteSpace(lines[0])) lines.RemoveAt(0); while (lines.Count > 0 && String.IsNullOrWhiteSpace(lines[lines.Count - 1])) lines.RemoveAt(lines.Count - 1);
            if (lines.Count == 0) return Tuple.Create("", StText.LineColumn(text, start).Key);
            var indent = lines.Skip(1).Where(line => !String.IsNullOrWhiteSpace(line)).Select(line => line.Length - line.TrimStart().Length).DefaultIfEmpty(0).Min();
            var result = new List<string> { lines[0].Trim() }; result.AddRange(lines.Skip(1).Select(line => String.IsNullOrWhiteSpace(line) ? "" : line.Substring(Math.Min(indent, line.Length))));
            return Tuple.Create(String.Join("\n", result).TrimEnd(), StText.LineColumn(text, start).Key);
        }
        static string Blank(string text)
        {
            var chars = text.ToCharArray();
            for (var i = 0; i < chars.Length;)
            {
                if (chars[i] == '/' && i + 1 < chars.Length && chars[i + 1] == '/') { while (i < chars.Length && chars[i] != '\n') chars[i++] = ' '; }
                else if (chars[i] == '(' && i + 1 < chars.Length && chars[i + 1] == '*') { chars[i++] = ' '; chars[i++] = ' '; while (i < chars.Length && !(text[i - 1] == '*' && text[i] == ')')) { chars[i] = chars[i] == '\n' ? '\n' : ' '; i++; } if (i < chars.Length) chars[i++] = ' '; }
                else if (chars[i] == '\'' || chars[i] == '"') { var quote = chars[i++]; while (i < chars.Length && chars[i] != quote) { if (chars[i] != '\n') chars[i] = ' '; i++; } if (i < chars.Length) i++; }
                else i++;
            }
            return new string(chars);
        }
    }
}
