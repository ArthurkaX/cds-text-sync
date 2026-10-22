using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    internal static class StFormatter
    {
        static readonly Regex SectionStart = new Regex(@"^VAR(?:_INPUT|_OUTPUT|_IN_OUT|_TEMP|_GLOBAL)?\b", RegexOptions.IgnoreCase);
        static readonly Regex SectionEnd = new Regex(@"^END_VAR\b", RegexOptions.IgnoreCase);
        internal static readonly Regex Declaration = new Regex(@"^(?<indent>[ \t]*)(?<names>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:\s*(?<type>.+?);\s*$");
        static readonly Regex Closer = new Regex(@"^END_(IF|FOR|WHILE|REPEAT|CASE)\b", RegexOptions.IgnoreCase);
        static readonly Regex Branch = new Regex(@"^(ELSE|ELSIF)\b", RegexOptions.IgnoreCase);
        static readonly Regex Opener = new Regex(@"\b(IF|FOR|WHILE|REPEAT|CASE)\b", RegexOptions.IgnoreCase);
        static readonly Regex CaseLabel = new Regex(@"^[^;:]+:(?!=)");
        static readonly Regex ContinuationStart = new Regex(@"^(?:[,.)\]}]|(?:AND|OR|XOR)\b|[+\-*/])", RegexOptions.IgnoreCase);
        static readonly Regex ConditionHeader = new Regex(@"^(?<indent>[ \t]*)(?<keyword>IF|ELSIF)\b", RegexOptions.IgnoreCase);
        static readonly Regex HeaderEnd = new Regex(@"^(THEN|DO|OF)\b", RegexOptions.IgnoreCase);
        static readonly Regex InlineElse = new Regex(@"^(?<indent>[ \t]*)ELSE\b", RegexOptions.IgnoreCase);

        internal static string Format(string text, bool declaration)
        {
            return declaration ? FormatDeclarations(text) : FormatImplementation(text);
        }

        static string FormatDeclarations(string text)
        {
            var raw = text.Split('\n');
            var clean = StText.Blank(text).Split('\n');
            var groups = DeclarationGroups(clean);
            foreach (var group in groups)
            {
                if (group.Count < 2) continue;
                var matches = group.Select(index => Declaration.Match(clean[index].TrimEnd('\r'))).ToList();
                var colons = group.Select(index => clean[index].IndexOf(':')).ToList();
                // Columns as the editor shows them: a table aligned with tabs
                // is aligned, and a line already in place keeps its own tabs.
                var indent = matches[0].Groups["indent"].Value;
                var columns = group.Select((index, at) => Width(clean[index].Substring(0, colons[at]))).ToList();
                var indented = matches.Select(match => Width(match.Groups["indent"].Value) == Width(indent)).ToList();
                var column = TableColumn(columns, matches.Max(match => Width(indent + match.Groups["names"].Value)));
                var formatted = new List<Tuple<int, string, int>>();
                for (var at = 0; at < group.Count; at++)
                {
                    var line = raw[group[at]];
                    var match = matches[at];
                    var value = line;
                    var colon = colons[at];
                    if (!indented[at] || columns[at] != column)
                    {
                        var prefix = indent + line.Substring(match.Groups["indent"].Length, match.Groups["names"].Index + match.Groups["names"].Length - match.Groups["indent"].Length);
                        value = prefix + new string(' ', Math.Max(1, column - Width(prefix))) + line.Substring(colon);
                        colon = value.Length - (line.Length - colon);
                    }
                    formatted.Add(Tuple.Create(group[at], value, TrailingCommentStart(value, colon)));
                }
                var comments = formatted.Where(row => row.Item3 >= 0).ToList();
                var starts = comments.Select(row => Width(row.Item2.Substring(0, row.Item3))).ToList();
                var commentColumn = Shared(starts, 0) ?? comments.Select(row => Width(row.Item2.Substring(0, row.Item3).TrimEnd()) + 2).DefaultIfEmpty(-1).Max();
                foreach (var row in formatted)
                {
                    var value = row.Item2;
                    if (row.Item3 >= 0 && Width(value.Substring(0, row.Item3)) != commentColumn)
                    {
                        var left = value.Substring(0, row.Item3).TrimEnd();
                        // A row too long for the column keeps the gap it has.
                        if (Width(left) + 2 <= commentColumn || left.Length == row.Item3)
                            value = left + new string(' ', Math.Max(2, commentColumn - Width(left))) + value.Substring(row.Item3);
                    }
                    raw[row.Item1] = value;
                }
            }
            return string.Join("\n", raw);
        }

        // The column most rows of a group share, from least on: one row more
        // than half the group keeps its table, and a row that cannot reach it
        // (a long initial value) stays apart instead of pushing every other
        // row out.
        static int? Shared(IList<int> columns, int least)
        {
            var top = columns.GroupBy(column => column).OrderByDescending(same => same.Count()).ThenBy(same => same.Key).FirstOrDefault();
            return top != null && top.Count() * 2 > columns.Count && top.Key >= least ? top.Key : (int?)null;
        }

        // The ':' column of a declaration table: the one most rows share, else
        // one past the longest name.
        internal static int TableColumn(IList<int> colons, int longestName) => Shared(colons, longestName + 1) ?? longestName + 1;

        internal static List<List<int>> DeclarationGroups(string[] clean)
        {
            var groups = new List<List<int>>();
            var section = false;
            var group = new List<int>();
            for (var i = 0; i < clean.Length; i++)
            {
                var line = clean[i].TrimEnd('\r');
                var stripped = line.Trim();
                if (!section)
                {
                    if (SectionStart.IsMatch(stripped)) section = true;
                    continue;
                }
                if (SectionEnd.IsMatch(stripped) || stripped.Length == 0)
                {
                    if (group.Count > 0) groups.Add(group);
                    group = new List<int>();
                    if (SectionEnd.IsMatch(stripped)) section = false;
                    continue;
                }
                if (Declaration.IsMatch(line)) group.Add(i);
                else if (!stripped.StartsWith("//", StringComparison.Ordinal) && !stripped.StartsWith("(*", StringComparison.Ordinal)
                    && !stripped.StartsWith("{", StringComparison.Ordinal) && !stripped.StartsWith("(", StringComparison.Ordinal))
                {
                    if (group.Count > 0) groups.Add(group);
                    group = new List<int>();
                }
            }
            if (group.Count > 0) groups.Add(group);
            return groups;
        }

        static int TrailingCommentStart(string line, int after)
        {
            for (var i = Math.Max(0, after); i < line.Length; i++)
            {
                if (line[i] == '\'' || line[i] == '"')
                {
                    i = StText.StringEnd(line, i) - 1;
                    continue;
                }
                if (i + 1 < line.Length && (line.Substring(i, 2) == "//" || line.Substring(i, 2) == "(*")) return i;
            }
            return -1;
        }

        static string FormatImplementation(string text)
        {
            var original = text.Split('\n');
            var lines = ExpandConditions(original);
            var clean = StText.Blanked(string.Join("\n", lines)).Split('\n');
            var records = ScanIndentation(lines, clean);
            var observed = records.Where(row => row.Prefix.Length > 0).Select(row => row.Prefix).ToList();
            var tabs = observed.Sum(prefix => prefix.Count(c => c == '\t')) > observed.Sum(prefix => prefix.Count(c => c == ' '));
            foreach (var row in records)
            {
                if (row.Actual == row.Expected) continue;
                lines[row.Index] = PrefixFor(row.Expected, observed, tabs) + lines[row.Index].Substring(row.Prefix.Length);
            }
            return string.Join("\n", lines);
        }

        sealed class IndentFrame
        {
            internal int OpenerIndent;
            internal bool Case;
            internal int? LabelIndent;
        }

        internal sealed class IndentRow
        {
            internal int Index;
            internal int Actual;
            internal int Expected;
            internal int Level;
            internal string Prefix;
        }

        // Indentation is measured in columns, a tab to the next multiple of
        // TabWidth as the CODESYS editor shows it: a line indented with four
        // spaces and one indented with a tab stand level.
        internal const int TabWidth = 4;

        internal static int Width(string prefix) => prefix.Aggregate(0, (column, c) => c == '\t' ? (column / TabWidth + 1) * TabWidth : column + 1);

        internal static List<IndentRow> ScanIndentation(string[] raw, string[] clean)
        {
            var records = new List<IndentRow>();
            var stack = new List<IndentFrame>();
            int? baseIndent = null;
            int? step = null;
            var previousCode = "";
            for (var index = 0; index < raw.Length && index < clean.Length; index++)
            {
                var code = clean[index].Trim();
                var line = raw[index];
                var prefix = line.Substring(0, line.Length - line.TrimStart(' ', '\t').Length);
                if (code.Length == 0) continue;
                var upper = code.ToUpperInvariant();
                var actual = Width(prefix);
                var level = stack.Count;
                var continuation = IsContinuation(previousCode, code);
                var close = Closer.IsMatch(upper);
                var branch = Branch.IsMatch(upper);
                var headerEnd = HeaderEnd.IsMatch(upper);
                var caseLabel = CaseLabel.IsMatch(upper) && stack.Count > 0 && stack[stack.Count - 1].Case;
                int? expected = null;
                if (!continuation)
                {
                    if (close || branch || headerEnd) expected = stack.Count > 0 ? stack[stack.Count - 1].OpenerIndent : baseIndent;
                    else if (caseLabel)
                    {
                        if (!stack[stack.Count - 1].LabelIndent.HasValue) stack[stack.Count - 1].LabelIndent = actual;
                        expected = stack[stack.Count - 1].LabelIndent;
                    }
                    else if (stack.Count > 0)
                    {
                        var frame = stack[stack.Count - 1];
                        var reference = frame.Case && frame.LabelIndent.HasValue ? frame.LabelIndent.Value : frame.OpenerIndent;
                        if (!step.HasValue && actual > reference) { step = actual - reference; expected = actual; }
                        else expected = reference + (step ?? TabWidth);
                    }
                    else
                    {
                        if (!baseIndent.HasValue) baseIndent = actual;
                        expected = baseIndent;
                    }
                    records.Add(new IndentRow { Index = index, Actual = actual, Expected = expected ?? 0, Level = level, Prefix = prefix });
                }
                if (close)
                {
                    if (stack.Count > 0) stack.RemoveAt(stack.Count - 1);
                }
                else if (!branch && !caseLabel)
                {
                    var openers = Opener.Matches(upper).Cast<Match>().Select(match => match.Groups[1].Value).ToList();
                    if (openers.Count > 0 && !Regex.IsMatch(upper, @"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b"))
                    {
                        var openerIndent = continuation ? actual : expected ?? actual;
                        foreach (var opener in openers) stack.Add(new IndentFrame { OpenerIndent = openerIndent, Case = opener.Equals("CASE", StringComparison.OrdinalIgnoreCase) });
                    }
                }
                previousCode = code;
            }
            return records;
        }

        static bool IsContinuation(string previous, string current)
        {
            return Regex.IsMatch(previous ?? "", @"(?:\b(?:AND|OR|XOR)|:=|,|\(|\.)\s*$", RegexOptions.IgnoreCase)
                || ContinuationStart.IsMatch(current ?? "");
        }

        static string PrefixFor(int expected, IList<string> observed, bool tabs)
        {
            if (expected <= 0) return "";
            var existing = observed.FirstOrDefault(prefix => Width(prefix) == expected);
            return existing ?? (tabs ? new string('\t', expected / TabWidth) + new string(' ', expected % TabWidth) : new string(' ', expected));
        }

        static string[] ExpandConditions(string[] source)
        {
            // A new line's step: a tab in a text indented with tabs.
            var step = source.Any(line => line.StartsWith("\t", StringComparison.Ordinal)) ? "\t" : "    ";
            var expanded = new List<string>();
            foreach (var line in source)
            {
                var eol = line.EndsWith("\r", StringComparison.Ordinal) ? "\r" : "";
                var clean = StText.Blanked(line);
                var header = ConditionHeader.Match(clean);
                var then = Regex.Match(clean, @"\bTHEN\b", RegexOptions.IgnoreCase);
                if (!header.Success || !then.Success || clean.Substring(then.Index + then.Length).Trim().Length > 0)
                { expanded.Add(line); continue; }
                var start = header.Index + header.Length;
                var condition = clean.Substring(start, then.Index - start);
                var operators = TopLevelLogicalOperators(condition);
                if (operators.Count == 0) { expanded.Add(line); continue; }
                var pieces = new List<string>();
                var partStart = start;
                foreach (var op in operators)
                {
                    pieces.Add(line.Substring(partStart, start + op.Item1 - partStart).Trim());
                    partStart = start + op.Item1;
                }
                pieces.Add(line.Substring(partStart, start + condition.Length - partStart).Trim());
                if (pieces.Any(part => part.Length == 0)) { expanded.Add(line); continue; }
                var indent = line.Substring(0, line.Length - line.TrimStart(' ', '\t').Length);
                expanded.Add(indent + header.Groups["keyword"].Value.ToUpperInvariant() + " " + pieces[0] + eol);
                expanded.AddRange(pieces.Skip(1).Select(part => indent + step + part + eol));
                var trailing = line.Substring(then.Index + then.Length).TrimEnd();
                expanded.Add(indent + "THEN" + trailing + eol);
            }
            var result = new List<string>();
            foreach (var line in expanded)
            {
                var clean = StText.Blanked(line);
                var branch = InlineElse.Match(clean);
                if (!branch.Success || clean.Substring(branch.Length).Trim().Length == 0) { result.Add(line); continue; }
                var eol = line.EndsWith("\r", StringComparison.Ordinal) ? "\r" : "";
                var indent = line.Substring(0, line.Length - line.TrimStart(' ', '\t').Length);
                result.Add(indent + "ELSE" + eol);
                result.Add(indent + step + line.Substring(branch.Length).Trim() + eol);
            }
            return result.SelectMany(SplitStatements).ToArray();
        }

        // One statement per line: `a := 1;   b := 2;` becomes two lines. A
        // line that opens, branches or closes a block stays as it is.
        static IEnumerable<string> SplitStatements(string line)
        {
            var clean = StText.Blanked(line);
            var upper = clean.Trim().ToUpperInvariant();
            if (Opener.IsMatch(upper) || Branch.IsMatch(upper) || HeaderEnd.IsMatch(upper) || Regex.IsMatch(upper, @"\bEND_(?:IF|FOR|WHILE|REPEAT|CASE)\b"))
                return new[] { line };
            var ends = new List<int>();
            var depth = 0;
            for (var i = 0; i < clean.Length; i++)
            {
                if (clean[i] == '(' || clean[i] == '[') depth++;
                else if (clean[i] == ')' || clean[i] == ']') depth = Math.Max(0, depth - 1);
                else if (clean[i] == ';' && depth == 0 && clean.Substring(i + 1).Trim().Length > 0) ends.Add(i);
            }
            if (ends.Count == 0) return new[] { line };
            var eol = line.EndsWith("\r", StringComparison.Ordinal) ? "\r" : "";
            var indent = line.Substring(0, line.Length - line.TrimStart(' ', '\t').Length);
            var pieces = new List<string>();
            var start = 0;
            foreach (var end in ends)
            {
                pieces.Add(indent + line.Substring(start, end + 1 - start).Trim() + eol);
                start = end + 1;
            }
            pieces.Add(indent + line.Substring(start).Trim());
            return pieces;
        }

        static List<Tuple<int, int>> TopLevelLogicalOperators(string text)
        {
            var operators = new List<Tuple<int, int>>();
            var depth = 0;
            for (var i = 0; i < text.Length;)
            {
                if (text[i] == '(') { depth++; i++; continue; }
                if (text[i] == ')') { depth = Math.Max(0, depth - 1); i++; continue; }
                if (char.IsLetter(text[i]) || text[i] == '_')
                {
                    var end = i + 1;
                    while (end < text.Length && (char.IsLetterOrDigit(text[end]) || text[end] == '_')) end++;
                    if (depth == 0 && (text.Substring(i, end - i).Equals("AND", StringComparison.OrdinalIgnoreCase)
                        || text.Substring(i, end - i).Equals("OR", StringComparison.OrdinalIgnoreCase)
                        || text.Substring(i, end - i).Equals("XOR", StringComparison.OrdinalIgnoreCase))) operators.Add(Tuple.Create(i, end));
                    i = end;
                    continue;
                }
                i++;
            }
            return operators;
        }
    }
}
