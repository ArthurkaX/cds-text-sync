// Minimal JSON for the agent wire protocol. The agent is loaded into the IDE
// process, so it carries no third-party assembly that could clash with one the
// IDE already ships.
//
// Parsed values are: null, bool, long, double, string,
// List<object> and Dictionary<string, object>.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Cts.Agent
{
    public sealed class JsonException : Exception
    {
        public JsonException(string message) : base(message) { }
    }

    public static class Json
    {
        const int MaxDepth = 64;

        // ---- parse

        public static object Parse(string text)
        {
            if (text == null) throw new ArgumentNullException("text");
            var p = new Parser(text);
            p.SkipWs();
            var v = p.ReadValue(0);
            p.SkipWs();
            if (!p.AtEnd) throw p.Fail("unexpected trailing characters");
            return v;
        }

        sealed class Parser
        {
            readonly string _s;
            int _i;

            public Parser(string s) { _s = s; }

            public bool AtEnd { get { return _i >= _s.Length; } }

            public JsonException Fail(string what)
            {
                return new JsonException(what + " at position " + _i);
            }

            public void SkipWs()
            {
                while (_i < _s.Length)
                {
                    var c = _s[_i];
                    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') _i++;
                    else break;
                }
            }

            public object ReadValue(int depth)
            {
                if (depth > MaxDepth) throw Fail("nesting deeper than " + MaxDepth);
                if (AtEnd) throw Fail("unexpected end of input");
                var c = _s[_i];
                switch (c)
                {
                    case '{': return ReadObject(depth);
                    case '[': return ReadArray(depth);
                    case '"': return ReadString();
                    case 't': Expect("true"); return true;
                    case 'f': Expect("false"); return false;
                    case 'n': Expect("null"); return null;
                    default:
                        if (c == '-' || (c >= '0' && c <= '9')) return ReadNumber();
                        throw Fail("unexpected character '" + c + "'");
                }
            }

            void Expect(string word)
            {
                if (string.CompareOrdinal(_s, _i, word, 0, word.Length) != 0) throw Fail("expected " + word);
                _i += word.Length;
            }

            object ReadObject(int depth)
            {
                var map = new Dictionary<string, object>();
                _i++;
                SkipWs();
                if (!AtEnd && _s[_i] == '}') { _i++; return map; }
                while (true)
                {
                    SkipWs();
                    if (AtEnd || _s[_i] != '"') throw Fail("expected a string key");
                    var key = ReadString();
                    SkipWs();
                    if (AtEnd || _s[_i] != ':') throw Fail("expected ':'");
                    _i++;
                    SkipWs();
                    map[key] = ReadValue(depth + 1);
                    SkipWs();
                    if (AtEnd) throw Fail("unterminated object");
                    if (_s[_i] == ',') { _i++; continue; }
                    if (_s[_i] == '}') { _i++; return map; }
                    throw Fail("expected ',' or '}'");
                }
            }

            object ReadArray(int depth)
            {
                var list = new List<object>();
                _i++;
                SkipWs();
                if (!AtEnd && _s[_i] == ']') { _i++; return list; }
                while (true)
                {
                    SkipWs();
                    list.Add(ReadValue(depth + 1));
                    SkipWs();
                    if (AtEnd) throw Fail("unterminated array");
                    if (_s[_i] == ',') { _i++; continue; }
                    if (_s[_i] == ']') { _i++; return list; }
                    throw Fail("expected ',' or ']'");
                }
            }

            string ReadString()
            {
                _i++;
                var sb = new StringBuilder();
                while (true)
                {
                    if (AtEnd) throw Fail("unterminated string");
                    var c = _s[_i++];
                    if (c == '"') return sb.ToString();
                    if (c < ' ') throw Fail("control character in string");
                    if (c != '\\') { sb.Append(c); continue; }
                    if (AtEnd) throw Fail("unterminated escape");
                    var e = _s[_i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (_i + 4 > _s.Length) throw Fail("short \\u escape");
                            int code;
                            if (!int.TryParse(_s.Substring(_i, 4), NumberStyles.AllowHexSpecifier,
                                    CultureInfo.InvariantCulture, out code))
                                throw Fail("bad \\u escape");
                            sb.Append((char)code);
                            _i += 4;
                            break;
                        default: throw Fail("bad escape '\\" + e + "'");
                    }
                }
            }

            object ReadNumber()
            {
                var start = _i;
                if (_s[_i] == '-') _i++;
                var digits = _i;
                while (_i < _s.Length && _s[_i] >= '0' && _s[_i] <= '9') _i++;
                if (_i == digits) throw Fail("digit expected");
                if (_s[digits] == '0' && _i - digits > 1) throw Fail("leading zero");
                var isInt = true;
                if (_i < _s.Length && _s[_i] == '.')
                {
                    isInt = false;
                    _i++;
                    var f = _i;
                    while (_i < _s.Length && _s[_i] >= '0' && _s[_i] <= '9') _i++;
                    if (_i == f) throw Fail("digit expected after '.'");
                }
                if (_i < _s.Length && (_s[_i] == 'e' || _s[_i] == 'E'))
                {
                    isInt = false;
                    _i++;
                    if (_i < _s.Length && (_s[_i] == '+' || _s[_i] == '-')) _i++;
                    var x = _i;
                    while (_i < _s.Length && _s[_i] >= '0' && _s[_i] <= '9') _i++;
                    if (_i == x) throw Fail("digit expected in exponent");
                }
                var token = _s.Substring(start, _i - start);
                long l;
                if (isInt && long.TryParse(token, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out l))
                    return l;
                return double.Parse(token, NumberStyles.Float, CultureInfo.InvariantCulture);
            }
        }

        // ---- write

        public static string Serialize(object value)
        {
            var sb = new StringBuilder();
            Write(sb, value, 0);
            return sb.ToString();
        }

        // *value* indented by two with sorted keys, so a file cts writes
        // again (cds-text-sync.json) changes only where its content does.
        public static string Pretty(object value)
        {
            var sb = new StringBuilder();
            WritePretty(sb, value, 0);
            return sb.ToString();
        }

        static void WritePretty(StringBuilder sb, object v, int depth)
        {
            if (depth > MaxDepth) throw new JsonException("nesting deeper than " + MaxDepth);
            var map = v as IDictionary;
            var seq = v is string || map != null ? null : v as IEnumerable;
            if (map == null && seq == null)
            {
                var s = v as string;
                if (s != null) WriteString(sb, s, Ascii);
                else Write(sb, v, depth);
                return;
            }
            var items = new List<KeyValuePair<string, object>>();
            if (map != null)
            {
                foreach (DictionaryEntry e in map)
                    items.Add(new KeyValuePair<string, object>(Convert.ToString(e.Key, CultureInfo.InvariantCulture), e.Value));
                items.Sort((a, b) => string.CompareOrdinal(a.Key, b.Key));
            }
            else
                foreach (var item in seq) items.Add(new KeyValuePair<string, object>(null, item));
            if (items.Count == 0) { sb.Append(map != null ? "{}" : "[]"); return; }
            sb.Append(map != null ? '{' : '[');
            for (var i = 0; i < items.Count; i++)
            {
                sb.Append(i == 0 ? "\n" : ",\n").Append(' ', 2 * (depth + 1));
                if (map != null) { WriteString(sb, items[i].Key, Ascii); sb.Append(": "); }
                WritePretty(sb, items[i].Value, depth + 1);
            }
            sb.Append('\n').Append(' ', 2 * depth).Append(map != null ? '}' : ']');
        }

        // The shortest form that reads back as the same double (.NET
        // Framework's "R" can give 17 digits where 16 do); a whole value
        // keeps ".0" so it reads back as a float: 1.0, 0.1, 1e-05, 1e+16.
        internal static string Number(double d)
        {
            var text = d.ToString("G15", CultureInfo.InvariantCulture);
            if (double.Parse(text, CultureInfo.InvariantCulture) != d) text = d.ToString("G16", CultureInfo.InvariantCulture);
            if (double.Parse(text, CultureInfo.InvariantCulture) != d) text = d.ToString("G17", CultureInfo.InvariantCulture);
            text = text.Replace("E", "e");
            return text.IndexOfAny(new[] { '.', 'e' }) < 0 ? text + ".0" : text;
        }

        static void Write(StringBuilder sb, object v, int depth)
        {
            if (depth > MaxDepth) throw new JsonException("nesting deeper than " + MaxDepth);
            if (v == null) { sb.Append("null"); return; }
            var s = v as string;
            if (s != null) { WriteString(sb, s, LineBreaks); return; }
            if (v is bool) { sb.Append((bool)v ? "true" : "false"); return; }
            if (v is DateTime)
            {
                WriteString(sb, ((DateTime)v).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture), LineBreaks);
                return;
            }
            if (v is double || v is float)
            {
                var d = Convert.ToDouble(v, CultureInfo.InvariantCulture);
                if (double.IsNaN(d) || double.IsInfinity(d)) sb.Append("null");
                else sb.Append(Number(d));
                return;
            }
            if (v is sbyte || v is byte || v is short || v is ushort || v is int || v is uint || v is long || v is ulong)
            {
                sb.Append(Convert.ToString(v, CultureInfo.InvariantCulture));
                return;
            }
            if (v is Enum) { WriteString(sb, v.ToString(), LineBreaks); return; }
            var map = v as IDictionary;
            if (map != null)
            {
                sb.Append('{');
                var first = true;
                foreach (DictionaryEntry e in map)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteString(sb, Convert.ToString(e.Key, CultureInfo.InvariantCulture), LineBreaks);
                    sb.Append(':');
                    Write(sb, e.Value, depth + 1);
                }
                sb.Append('}');
                return;
            }
            var seq = v as IEnumerable;
            if (seq != null)
            {
                sb.Append('[');
                var first = true;
                foreach (var item in seq)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    Write(sb, item, depth + 1);
                }
                sb.Append(']');
                return;
            }
            throw new JsonException("cannot serialize " + v.GetType().FullName);
        }

        // What WriteString escapes besides the control characters: ensure_ascii's
        // everything past '~'; U+2028/2029, legal JSON that some line readers
        // split on; or nothing, as json.dumps(ensure_ascii=False) writes.
        static readonly Func<char, bool> Ascii = c => c > '~';
        static readonly Func<char, bool> LineBreaks = c => c == 0x2028 || c == 0x2029;
        internal static readonly Func<char, bool> Nothing = c => false;

        internal static void WriteString(StringBuilder sb, string s, Func<char, bool> escape)
        {
            sb.Append('"');
            foreach (var c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < ' ' || escape(c)) sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }
    }
}
