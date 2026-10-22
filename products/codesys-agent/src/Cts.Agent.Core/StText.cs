using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Agent
{
    // The blind Structured Text lexer: comments, pragmas and string contents
    // become spaces, so a keyword or a ';' inside them never counts. Only
    // characters are replaced and line breaks stay, so an offset in the
    // blanked text is the same character in the source.
    internal static class StText
    {
        static readonly Regex Whitespace = new Regex(@"\s+");
        static readonly Regex Identifier = new Regex(@"^[A-Za-z_]\w*$");
        static readonly Regex IntentionalNoop = new Regex(@"\b(?:wait|waiting|reset|intentionally|reserved|not\s+applicable|no[-\s]?op|nothing\s+to\s+do)\b", RegexOptions.IgnoreCase);

        // text with "\n" for every line break ("\r\n", "\r").
        internal static string Lf(string text) => (text ?? "").Replace("\r\n", "\n").Replace('\r', '\n');

        // Each run of white space as one space, trimmed: "a  :=\n b" -> "a := b".
        internal static string Squeezed(string text) => Whitespace.Replace(text ?? "", " ").Trim();

        // text without white space: "a . b [ i ]" -> "a.b[i]".
        internal static string Unspaced(string text) => Whitespace.Replace(text ?? "", "");

        // The 1-based line and column of offset (clamped to the text).
        internal static KeyValuePair<int, int> LineColumn(string text, int offset)
        {
            offset = System.Math.Max(0, System.Math.Min(offset, text.Length));
            var line = 1;
            var lastBreak = -1;
            for (var i = 0; i < offset; i++) if (text[i] == '\n') { line++; lastBreak = i; }
            return new KeyValuePair<int, int>(line, offset - lastBreak);
        }

        // A bare name: a letter or _, then letters, digits or _.
        internal static bool IsIdentifier(string text) => Identifier.IsMatch(text);

        // Each name in text, not a tail of a longer word or of a number.
        internal static readonly Regex Name = new Regex(@"(?<![A-Za-z0-9_])(?<name>[A-Za-z_]\w*)(?![A-Za-z0-9_])");

        // Comments and pragmas blanked; string literals kept as they are.
        internal static string Blank(string text)
        {
            var chars = text.ToCharArray();
            var i = 0;
            while (i < chars.Length)
            {
                if (chars[i] == '\'' || chars[i] == '"') { i = StringEnd(text, i); continue; }
                if (i + 1 < chars.Length && chars[i] == '/' && chars[i + 1] == '/')
                { while (i < chars.Length && chars[i] != '\n') chars[i++] = ' '; continue; }
                if (i + 1 < chars.Length && chars[i] == '(' && chars[i + 1] == '*')
                {
                    chars[i++] = ' '; chars[i++] = ' ';
                    while (i < chars.Length)
                    {
                        if (i + 1 < chars.Length && chars[i] == '*' && chars[i + 1] == ')') { chars[i++] = ' '; chars[i++] = ' '; break; }
                        if (chars[i] != '\n') chars[i] = ' ';
                        i++;
                    }
                    continue;
                }
                if (chars[i] == '{')
                {
                    var depth = 0;
                    do
                    {
                        if (chars[i] == '{') depth++;
                        else if (chars[i] == '}') depth--;
                        if (chars[i] != '\n') chars[i] = ' ';
                        i++;
                    } while (i < chars.Length && depth > 0);
                    continue;
                }
                i++;
            }
            return new string(chars);
        }

        // String contents blanked, the quotes kept.
        internal static string TrimStrings(string text)
        {
            var chars = text.ToCharArray();
            var i = 0;
            while (i < chars.Length)
            {
                if (chars[i] != '\'' && chars[i] != '"') { i++; continue; }
                var end = StringEnd(text, i);
                var close = end - 1 > i && text[end - 1] == text[i] ? end - 1 : end;
                for (i++; i < close; i++) if (chars[i] != '\n') chars[i] = ' ';
                i = end;
            }
            return new string(chars);
        }

        internal static string Blanked(string text) => TrimStrings(Blank(text));

        // The end of the string literal opening at i, after its closing quote.
        internal static int StringEnd(string text, int i)
        {
            var quote = text[i++];
            while (i < text.Length)
            {
                // "$'" and "$$" are escapes: the quote after '$' does not end the string.
                if (text[i] == '$') { i += 2; continue; }
                if (text[i] == quote)
                {
                    if (i + 1 < text.Length && text[i + 1] == quote) { i += 2; continue; }
                    return i + 1;
                }
                i++;
            }
            return text.Length;
        }

        internal sealed class Comment
        {
            internal int Start, End;
            internal string Content;
        }

        // Line and block comments: where each starts and ends, and the text
        // between its delimiters.
        internal static List<Comment> Comments(string text)
        {
            var found = new List<Comment>();
            text = text ?? "";
            var n = text.Length;
            var i = 0;
            while (i < n)
            {
                var c = text[i];
                var next = i + 1 < n ? text[i + 1] : '\0';
                if (c == '\'' || c == '"') { i = StringEnd(text, i); continue; }
                if (c == '/' && next == '/')
                {
                    var start = i;
                    i += 2;
                    while (i < n && text[i] != '\n') i++;
                    found.Add(new Comment { Start = start, End = i, Content = text.Substring(start + 2, i - start - 2) });
                    continue;
                }
                if (c == '(' && next == '*')
                {
                    var start = i;
                    i += 2;
                    var contentStart = i;
                    while (i < n && !(text[i] == '*' && i + 1 < n && text[i + 1] == ')')) i++;
                    var contentEnd = i;
                    if (i < n) i += 2;
                    found.Add(new Comment { Start = start, End = i, Content = text.Substring(contentStart, contentEnd - contentStart) });
                    continue;
                }
                i++;
            }
            return found;
        }

        // A comment right before position, or after it on its line, that says
        // the empty branch is deliberate ("wait", "nothing to do", ...). Only
        // the nearest comments count, so a stray one elsewhere cannot hide a
        // blank branch.
        internal static bool HasIntentionalNoopComment(string text, int position)
        {
            var comments = Comments(text);
            var before = comments.LastOrDefault(comment => comment.End <= position);
            var after = comments.FirstOrDefault(comment => comment.Start > position);
            return before != null && text.Substring(before.End, position - before.End).Trim().Length == 0 && IntentionalNoop.IsMatch(before.Content)
                || after != null && text.Substring(position, after.Start - position).Trim(' ', '\t', ';').Length == 0 && IntentionalNoop.IsMatch(after.Content);
        }

        // Each ';'-terminated statement of blanked text: its offset (plus
        // offsetBase) past the leading whitespace, and its text without the ';'.
        internal static IEnumerable<KeyValuePair<int, string>> Statements(string blanked, int offsetBase)
        {
            var start = 0;
            for (var i = 0; i < blanked.Length; i++)
            {
                if (blanked[i] != ';') continue;
                var raw = blanked.Substring(start, i + 1 - start);
                var statement = raw.Trim();
                if (statement.Length > 0)
                    yield return new KeyValuePair<int, string>(offsetBase + start + (raw.Length - raw.TrimStart().Length), statement.Substring(0, statement.Length - 1));
                start = i + 1;
            }
        }
    }
}
