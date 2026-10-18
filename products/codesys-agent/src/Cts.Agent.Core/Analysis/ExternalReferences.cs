using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Cts.Analysis
{
    // Symbol paths and names the view's XML files (visualizations, text
    // lists, the task configuration) name: a symbol only a screen reads must
    // not look dead, nor a program only a task or a system event calls. A
    // textual match, so it errs toward "referenced", the safe side for a
    // suspicious rule.
    internal sealed class ExternalReferences
    {
        readonly string _root;
        HashSet<string> _index;
        readonly HashSet<string> _words = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        bool _tasks;

        internal ExternalReferences(string root) { _root = root; }

        internal bool IsReferenced(string owner, string member) => Built().Contains(owner.ToLowerInvariant() + "\n" + member.ToLowerInvariant());

        // Whether some XML file has name as a word (a task's program, an event's handler).
        internal bool Names(string name)
        {
            Built();
            return _words.Contains(name);
        }

        // Whether the view holds a task configuration that calls programs.
        internal bool HasTasks
        {
            get
            {
                Built();
                return _tasks;
            }
        }

        HashSet<string> Built()
        {
            if (_index != null) return _index;
            _index = new HashSet<string>(StringComparer.Ordinal);
            if (string.IsNullOrEmpty(_root) || !Directory.Exists(_root)) return _index;
            foreach (var path in Directory.EnumerateFiles(_root, "*.xml", SearchOption.AllDirectories))
            {
                var relative = path.Substring(_root.Length).Replace('\\', '/');
                if (relative.Split('/').Reverse().Skip(1).Any(part => part.StartsWith(".", StringComparison.Ordinal))) continue;
                string text;
                try { text = File.ReadAllText(path, new UTF8Encoding(false, false)); }
                catch (Exception error) when (error is IOException || error is UnauthorizedAccessException) { continue; }
                if (text.Contains("\"PouList\"")) _tasks = true;
                for (var at = 0; at < text.Length;)
                {
                    if (text[at] == '<') { at = Markup(text, at); continue; }
                    if (!IsNameStart(text[at]) || at > 0 && IsWord(text[at - 1])) { at++; continue; }
                    var end = at + 1;
                    while (end < text.Length && IsWord(text[end])) end++;
                    _words.Add(text.Substring(at, end - at));
                    at = end;
                }
                // Every member along the path: Application.PN81.nWord.IN.bit8
                // maps a bit of PN81.nWord.
                foreach (var segments in Paths(text))
                    for (var i = 1; i < segments.Count; i++)
                    {
                        var member = segments[i].ToLowerInvariant();
                        _index.Add(string.Join(".", segments.Take(i)).ToLowerInvariant() + "\n" + member);
                        _index.Add(segments[i - 1].ToLowerInvariant() + "\n" + member);
                    }
            }
            return _index;
        }

        // The dotted paths in *text* (Screen.fbPump[2].xOut), as their names
        // without the indexes: one pass, a path starting at a word's start.
        // Screens run to megabytes; a regular expression took most of a big
        // project's analysis on .NET Framework.
        internal static IEnumerable<List<string>> Paths(string text)
        {
            var at = 0;
            var names = new List<int>();
            // *at* is never inside a word: a word is passed whole.
            while (at < text.Length)
            {
                var c = text[at];
                if (c == '<')
                {
                    at = Markup(text, at);
                    continue;
                }
                if (!IsNameStart(c))
                {
                    at++;
                    if (IsWord(c)) while (at < text.Length && IsWord(text[at])) at++;
                    continue;
                }
                names.Clear();
                var end = Segment(text, at, names);
                while (true)
                {
                    var dot = SkipSpace(text, end);
                    if (dot >= text.Length || text[dot] != '.') break;
                    var next = SkipSpace(text, dot + 1);
                    if (next >= text.Length || !IsNameStart(text[next])) break;
                    end = Segment(text, next, names);
                }
                if (names.Count >= 4)
                {
                    var segments = new List<string>(names.Count / 2);
                    for (var i = 0; i < names.Count; i += 2) segments.Add(text.Substring(names[i], names[i + 1]));
                    yield return segments;
                    at = end;
                }
                else
                {
                    // The rest of the word cannot start a path.
                    at++;
                    while (at < text.Length && IsWord(text[at])) at++;
                }
            }
        }

        // A name at *start* and the index after it ([...] on one line): the
        // name's start and length added to *names*; where it ends.
        static int Segment(string text, int start, List<int> names)
        {
            var end = start + 1;
            while (end < text.Length && IsWord(text[end])) end++;
            names.Add(start);
            names.Add(end - start);
            if (end < text.Length && text[end] == '[')
            {
                var close = end + 1;
                while (close < text.Length && text[close] != ']' && text[close] != '\n') close++;
                if (close < text.Length && text[close] == ']') end = close + 1;
            }
            return end;
        }

        // Where the markup at *at* ends: past the tag, whose element and
        // attribute names (Single, Name, Type) and attribute values (types,
        // GUIDs) name no symbol, or into a CDATA section's text. A name is
        // element text: <Single Name="Name" Type="string">MAIN</Single>.
        static int Markup(string text, int at)
        {
            if (string.CompareOrdinal(text, at, "<![CDATA[", 0, 9) == 0) return at + 9;
            var end = text.IndexOf('>', at);
            return end < 0 ? text.Length : end + 1;
        }

        static int SkipSpace(string text, int at)
        {
            while (at < text.Length && char.IsWhiteSpace(text[at])) at++;
            return at;
        }

        static bool IsNameStart(char c) => c >= 'A' && c <= 'Z' || c >= 'a' && c <= 'z' || c == '_';

        // What \w matches.
        static bool IsWord(char c)
        {
            if (c < 128) return IsNameStart(c) || c >= '0' && c <= '9';
            var category = CharUnicodeInfo.GetUnicodeCategory(c);
            return char.IsLetterOrDigit(c) || category == UnicodeCategory.NonSpacingMark || category == UnicodeCategory.ConnectorPunctuation;
        }
    }
}
