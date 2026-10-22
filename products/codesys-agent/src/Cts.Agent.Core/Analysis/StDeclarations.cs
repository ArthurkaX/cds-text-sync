using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis
{
    // Where a declared member stands in its declaration text.
    internal sealed class TextSpan
    {
        internal int Start, End, Line, Column, EndLine, EndColumn;
    }

    internal sealed class VarMember
    {
        internal string Name, Type, Scope, Initial;
        internal int Line;
        internal TextSpan Span;
    }

    internal sealed class VarBlock
    {
        internal string Scope;
        internal List<string> Modifiers = new List<string>();
        internal bool Retain, Persistent, Constant;
        internal List<VarMember> Members = new List<VarMember>();
        internal List<string> Warnings = new List<string>();
    }

    internal sealed class DutField
    {
        internal string Name, Type, Initial, Comment, RawValue;
        internal int? Line;
        internal long? Value;
    }

    // A TYPE declaration: struct, union, enum or alias.
    internal sealed class Dut
    {
        internal string Name, Kind, Base, Extends;
        internal List<DutField> Fields = new List<DutField>();
        internal List<string> Attributes = new List<string>();
        internal Dictionary<string, string> AttributeValues = new Dictionary<string, string>();
        internal bool Strict, QualifiedOnly;
        internal List<string> Warnings = new List<string>();
    }

    // An IEC type: scalar (Base), array (Element, Dimensions) or a reference
    // to another type (Name).
    internal sealed class TypeShape
    {
        internal string Kind, Base, Element, Name;
        internal List<KeyValuePair<string, string>> Dimensions = new List<KeyValuePair<string, string>>();
    }

    internal static class StDeclarations
    {
        // A POU, member or type header in blanked text: its keyword, name and
        // what follows a ':' on its line (a result or property type).
        internal static readonly Regex Header = new Regex(@"^[ \t]*(?<kind>FUNCTION_BLOCK|FUNCTION|PROGRAM|INTERFACE|METHOD|PROPERTY|ACTION|TYPE)\b[ \t]+(?:(?:PUBLIC|PRIVATE|PROTECTED|INTERNAL|FINAL|ABSTRACT)[ \t]+)*(?<name>[A-Za-z_]\w*)(?:[ \t]*:[ \t]*(?<type>[^\n]*))?", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        internal static readonly HashSet<string> ScalarTypes = new HashSet<string>
        {
            "BOOL", "BIT", "BYTE", "WORD", "DWORD", "LWORD",
            "SINT", "USINT", "INT", "UINT", "DINT", "UDINT", "LINT", "ULINT",
            "REAL", "LREAL", "TIME", "LTIME", "TIME_OF_DAY", "TOD", "DATE",
            "DATE_AND_TIME", "DT", "LTIME_OF_DAY", "LTOD", "LDATE",
            "LDATE_AND_TIME", "LDT", "STRING", "WSTRING", "CHAR", "WCHAR",
            "POINTER", "REFERENCE",
        };

        static readonly HashSet<string> VarOpeners = new HashSet<string>
        {
            "VAR_GLOBAL", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT", "VAR_TEMP",
            "VAR_STAT", "VAR_EXTERNAL", "VAR_CONFIG", "VAR_INST", "VAR",
        };

        static readonly Regex AtKeyword = new Regex(@"\bAT\b", RegexOptions.IgnoreCase);
        static readonly Regex Attribute = new Regex(@"\{\s*attribute\s+'([^']+)'(?:\s*:?=\s*([^}]*))?\s*\}", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex TypeHeader = new Regex(@"\bTYPE\s+([A-Za-z_]\w*)\s*(?:\bEXTENDS\s+([A-Za-z_][\w.]*)\s*)?:(.*?)\bEND_TYPE\b", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex LeadingAttributes = new Regex(@"^\s*(?:\{\s*attribute\s+'[^']+'[^}]*\}\s*)+", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex Braced = new Regex(@"\{[^}]*\}");
        static readonly Regex EnumItem = new Regex(@"^([A-Za-z_]\w*)\s*(?::=\s*([^,]+))?$");
        static readonly Regex StringType = new Regex(@"^(W?STRING)\s*(\(.*\)|\[.*\])?\s*$", RegexOptions.IgnoreCase);
        static readonly Regex PointerType = new Regex(@"^(POINTER|REFERENCE)\s+TO\b", RegexOptions.IgnoreCase);
        static readonly Regex ArrayType = new Regex(@"^ARRAY\s*\[(.*?)\]\s*OF\s+(.+)$", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex PouHeaderLine = new Regex(@"^[ \t]*(?:FUNCTION_BLOCK|FUNCTION|PROGRAM|METHOD|INTERFACE|PROPERTY|ACTION)[ \t]+[A-Za-z_]\w*(?:[ \t]*:[ \t]*[A-Za-z_][\w.]*)?[ \t]*(?<tail>[^\n]*)", RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Regex Extends = new Regex(@"\bEXTENDS\s+([A-Za-z_][\w.]*)", RegexOptions.IgnoreCase);
        static readonly Regex Implements = new Regex(@"\bIMPLEMENTS\s+([^\n;]+)", RegexOptions.IgnoreCase);

        // The VAR_* blocks of a declaration with their members, in order.
        internal static List<VarBlock> VarBlocks(string declaration)
        {
            declaration = declaration ?? "";
            var text = StText.Blank(declaration);
            var lines = text.Split('\n');
            var starts = new int[lines.Length];
            for (int i = 0, offset = 0; i < lines.Length; i++) { starts[i] = offset; offset += lines[i].Length + 1; }
            var blocks = new List<VarBlock>();
            var index = 0;
            while (index < lines.Length)
            {
                var tokens = Words(lines[index]);
                var opener = tokens.Length > 0 ? tokens[0].ToUpperInvariant() : "";
                if (!VarOpeners.Contains(opener)) { index++; continue; }
                var block = new VarBlock { Scope = opener, Modifiers = tokens.Skip(1).Select(t => t.ToUpperInvariant()).ToList() };
                block.Retain = block.Modifiers.Contains("RETAIN");
                block.Persistent = block.Modifiers.Contains("PERSISTENT");
                block.Constant = block.Modifiers.Contains("CONSTANT");
                var bodyStart = Math.Min(text.Length, starts[index] + lines[index].Length + 1);
                var end = index + 1;
                while (end < lines.Length && !lines[end].Trim().ToUpperInvariant().StartsWith("END_VAR", StringComparison.Ordinal)) end++;
                var bodyEnd = Math.Max(bodyStart, end < lines.Length ? starts[end] : text.Length);
                foreach (var part in SplitStatements(text.Substring(bodyStart, bodyEnd - bodyStart)))
                {
                    var statement = part.Key;
                    var parsed = ParseMember(statement);
                    if (parsed == null)
                    {
                        if (statement.Trim().Length > 0)
                        {
                            var at = bodyStart + part.Value;
                            block.Warnings.Add("unparsed member near line " + (at - (at > 0 ? text.LastIndexOf('\n', at - 1) : -1)).ToString(CultureInfo.InvariantCulture));
                        }
                        continue;
                    }
                    var memberStart = bodyStart + part.Value + statement.Length - statement.TrimStart().Length;
                    var memberEnd = bodyStart + part.Value + statement.TrimEnd().Length;
                    var span = Span(declaration, memberStart, memberEnd);
                    foreach (var name in parsed.Item1)
                        block.Members.Add(new VarMember { Name = name, Type = parsed.Item2, Scope = opener, Line = span.Line, Initial = parsed.Item3, Span = span });
                }
                blocks.Add(block);
                index = end + 1;
            }
            return blocks;
        }

        static string[] Words(string line) => line.Split(new[] { ' ', '\t', '\n', '\r', '\f', '\v' }, StringSplitOptions.RemoveEmptyEntries);

        static TextSpan Span(string text, int start, int end)
        {
            var from = StText.LineColumn(text, start);
            var to = StText.LineColumn(text, end);
            return new TextSpan { Start = start, End = end, Line = from.Key, Column = from.Value, EndLine = to.Key, EndColumn = to.Value };
        }

        // A separator outside brackets and string literals; a ':' that starts
        // ':=' is not one.
        static int SplitTopLevel(string text, string separator)
        {
            var depth = 0;
            var i = 0;
            while (i < text.Length)
            {
                var c = text[i];
                if (c == '\'' || c == '"') { i = StText.StringEnd(text, i); continue; }
                if (c == '(' || c == '[') depth++;
                else if (c == ')' || c == ']') depth = Math.Max(0, depth - 1);
                else if (depth == 0 && string.CompareOrdinal(text, i, separator, 0, separator.Length) == 0)
                {
                    if (separator != ":" || string.CompareOrdinal(text, i, ":=", 0, 2) != 0) return i;
                }
                i++;
            }
            return -1;
        }

        // The ';'-separated statements of a block body, with their offsets.
        static IEnumerable<KeyValuePair<string, int>> SplitStatements(string body)
        {
            var depth = 0;
            var start = 0;
            var i = 0;
            while (i < body.Length)
            {
                var c = body[i];
                if (c == '\'' || c == '"') { i = StText.StringEnd(body, i); continue; }
                if (c == '(' || c == '[') depth++;
                else if (c == ')' || c == ']') depth = Math.Max(0, depth - 1);
                else if (c == ';' && depth == 0)
                {
                    yield return new KeyValuePair<string, int>(body.Substring(start, i - start), start);
                    start = i + 1;
                }
                i++;
            }
            if (start < body.Length && body.Substring(start).Trim().Length > 0)
                yield return new KeyValuePair<string, int>(body.Substring(start), start);
        }

        // "a, b AT %IX0.0 : TYPE := initial" -> names, type, initial.
        static Tuple<List<string>, string, string> ParseMember(string statement)
        {
            var colon = SplitTopLevel(statement, ":");
            if (colon < 0) return null;
            var left = statement.Substring(0, colon).Trim();
            var right = statement.Substring(colon + 1).Trim();
            if (left.Length == 0 || right.Length == 0) return null;
            var at = AtKeyword.Match(left);
            if (at.Success) left = left.Substring(0, at.Index).Trim();
            var names = left.Split(',').Select(part => part.Trim()).Where(part => part.Length > 0).ToList();
            if (names.Count == 0 || names.Any(name => !StText.IsIdentifier(name))) return null;
            var assign = SplitTopLevel(right, ":=");
            string type, initial;
            if (assign >= 0) { type = right.Substring(0, assign).Trim(); initial = right.Substring(assign + 2).Trim(); }
            else { type = right; initial = ""; }
            return Tuple.Create(names, StText.Squeezed(type), initial);
        }

        // The members of all VAR_* blocks whose scope is one of scopes.
        internal static IEnumerable<VarMember> Members(IEnumerable<VarBlock> blocks, params string[] scopes) =>
            blocks.Where(block => scopes.Length == 0 || scopes.Contains(block.Scope)).SelectMany(block => block.Members);

        // A TYPE declaration, or null when there is none.
        internal static Dut ParseDut(string declaration)
        {
            var original = declaration ?? "";
            var names = new List<string>();
            var values = new Dictionary<string, string>();
            foreach (Match attribute in Attribute.Matches(original))
            {
                var name = StText.Squeezed(attribute.Groups[1].Value).Replace(' ', '_').ToLowerInvariant();
                if (name.Length == 0) continue;
                names.Add(name);
                var value = attribute.Groups[2].Value.Trim();
                if (value.Length > 0) values[name] = value;
            }
            var strict = names.Contains("strict");
            var qualifiedOnly = names.Contains("qualified_only");
            var text = StText.Blank(original);
            var header = TypeHeader.Match(text);
            if (!header.Success) return null;
            var typeName = header.Groups[1].Value;
            var extends = header.Groups[2].Success ? header.Groups[2].Value : null;
            var body = header.Groups[3].Value;
            var upper = body.ToUpperInvariant();
            foreach (var keyword in new[] { "STRUCT", "UNION" })
            {
                var endKeyword = "END_" + keyword;
                if (!upper.Contains(keyword) || !upper.Contains(endKeyword)) continue;
                var inner = Regex.Match(body, keyword + "(.*?)" + endKeyword, RegexOptions.IgnoreCase | RegexOptions.Singleline);
                var dut = new Dut
                {
                    Name = typeName, Kind = keyword == "UNION" ? "union" : "struct", Base = extends, Extends = extends,
                    Attributes = names, AttributeValues = values, QualifiedOnly = qualifiedOnly, Strict = strict,
                };
                foreach (var part in SplitStatements(inner.Success ? inner.Groups[1].Value : ""))
                {
                    var parsed = ParseMember(part.Key);
                    if (parsed != null)
                    {
                        foreach (var field in parsed.Item1)
                            dut.Fields.Add(new DutField { Name = field, Type = parsed.Item2, Initial = parsed.Item3, Comment = MemberComment(original, field), Line = MemberLine(original, field) });
                    }
                    else if (part.Key.Trim().Length > 0) dut.Warnings.Add("unparsed " + keyword.ToLowerInvariant() + " member");
                }
                return dut;
            }
            var stripped = LeadingAttributes.Replace(body, "", 1).Trim();
            if (stripped.StartsWith("(", StringComparison.Ordinal))
            {
                var close = stripped.LastIndexOf(')');
                var inside = close >= 0 ? stripped.Substring(1, close - 1) : "";
                var baseType = close >= 0 ? stripped.Substring(close + 1).Trim().TrimEnd(';').Trim() : "";
                if (baseType.Length == 0) baseType = "INT";
                var dut = new Dut { Name = typeName, Kind = "enum", Base = baseType, Strict = strict, QualifiedOnly = qualifiedOnly, Attributes = names, AttributeValues = values };
                long? last = -1;
                var canInfer = true;
                foreach (var raw in SplitEnumItems(inside))
                {
                    var item = Braced.Replace(raw, " ").Trim().TrimEnd(',').Trim();
                    var match = EnumItem.Match(item);
                    if (!match.Success)
                    {
                        if (item.Length > 0) dut.Warnings.Add("unparsed enum member");
                        continue;
                    }
                    var rawValue = match.Groups[2].Success ? match.Groups[2].Value.Trim() : null;
                    long? value = null;
                    if (rawValue == null && canInfer && last.HasValue) value = last + 1;
                    else if (rawValue != null) value = EnumValue(rawValue);
                    if (value.HasValue) last = value;
                    else if (rawValue != null) canInfer = false;
                    var memberName = match.Groups[1].Value;
                    dut.Fields.Add(new DutField
                    {
                        Name = memberName, Type = baseType, RawValue = rawValue, Value = value,
                        Initial = rawValue ?? (value.HasValue ? value.Value.ToString(CultureInfo.InvariantCulture) : ""),
                        Comment = MemberComment(original, memberName), Line = MemberLine(original, memberName),
                    });
                }
                return dut;
            }
            return new Dut { Name = typeName, Kind = "alias", Base = stripped.TrimEnd(';').Trim() };
        }

        // An enum member's literal value (5, -1, 16#10, 2#0101), else null.
        static long? EnumValue(string text)
        {
            var value = IecTypes.Integer(text);
            return value.HasValue && value.Value >= long.MinValue && value.Value <= long.MaxValue ? (long)value.Value : (long?)null;
        }

        static List<string> SplitEnumItems(string text)
        {
            var items = new List<string>();
            var current = new StringBuilder();
            var depth = 0;
            for (var i = 0; i < text.Length; i++)
            {
                var c = text[i];
                if (c == '\'' || c == '"')
                {
                    var end = StText.StringEnd(text, i);
                    current.Append(text, i, end - i);
                    i = end - 1;
                    continue;
                }
                if (c == '(' || c == '[' || c == '{') depth++;
                else if (c == ')' || c == ']' || c == '}') depth = Math.Max(0, depth - 1);
                if (c == ',' && depth == 0) { items.Add(current.ToString().Trim()); current.Clear(); }
                else current.Append(c);
            }
            if (current.Length > 0) items.Add(current.ToString().Trim());
            return items;
        }

        // The trailing // comment on the first line that names the member.
        internal static string MemberComment(string text, string name)
        {
            var pattern = NamePattern(name);
            foreach (var line in (text ?? "").Split('\n'))
            {
                if (!pattern.IsMatch(line)) continue;
                var marker = line.IndexOf("//", StringComparison.Ordinal);
                if (marker >= 0) return line.Substring(marker + 2).Trim();
            }
            return "";
        }

        static int? MemberLine(string text, string name)
        {
            var pattern = NamePattern(name);
            var lines = (text ?? "").Split('\n');
            for (var i = 0; i < lines.Length; i++) if (pattern.IsMatch(lines[i])) return i + 1;
            return null;
        }

        static Regex NamePattern(string name) => new Regex(@"(?<![A-Za-z0-9_])" + Regex.Escape(name) + @"\b", RegexOptions.IgnoreCase);

        // EXTENDS and IMPLEMENTS of a POU header line ("" and none when absent).
        internal static KeyValuePair<string, List<string>> PouHeader(string declaration)
        {
            var header = PouHeaderLine.Match(StText.Blank(declaration ?? ""));
            var tail = header.Success ? header.Groups["tail"].Value : "";
            var extends = Extends.Match(tail);
            var implements = Implements.Match(tail);
            var names = new List<string>();
            if (implements.Success)
                foreach (var part in implements.Groups[1].Value.Split(','))
                {
                    var name = part.Trim().Length > 0 ? Words(part)[0] : "";
                    if (name.Length > 0) names.Add(name);
                }
            return new KeyValuePair<string, List<string>>(extends.Success ? extends.Groups[1].Value : "", names);
        }

        internal static TypeShape ClassifyType(string typeName)
        {
            var text = (typeName ?? "").Trim();
            var array = ArrayType.Match(text);
            if (array.Success)
            {
                var shape = new TypeShape { Kind = "array", Element = array.Groups[2].Value.Trim() };
                foreach (var part in SplitDims(array.Groups[1].Value))
                {
                    var bounds = part.Split(new[] { ".." }, StringSplitOptions.None);
                    shape.Dimensions.Add(new KeyValuePair<string, string>(bounds[0].Trim(), bounds[bounds.Length - 1].Trim()));
                }
                return shape;
            }
            var baseName = BaseTypeName(text);
            return ScalarTypes.Contains(baseName) ? new TypeShape { Kind = "scalar", Base = baseName } : new TypeShape { Kind = "ref", Name = text };
        }

        static string BaseTypeName(string typeName)
        {
            var text = typeName.Trim();
            var match = StringType.Match(text);
            if (match.Success) return match.Groups[1].Value.ToUpperInvariant();
            match = PointerType.Match(text);
            return match.Success ? match.Groups[1].Value.ToUpperInvariant() : text.ToUpperInvariant();
        }

        static List<string> SplitDims(string text)
        {
            var parts = new List<string>();
            var current = new StringBuilder();
            var depth = 0;
            foreach (var c in text)
            {
                if (c == '(' || c == '[') depth++;
                else if (c == ')' || c == ']') depth = Math.Max(0, depth - 1);
                if (c == ',' && depth == 0) { parts.Add(current.ToString()); current.Clear(); }
                else current.Append(c);
            }
            if (current.Length > 0) parts.Add(current.ToString());
            return parts;
        }
    }
}
