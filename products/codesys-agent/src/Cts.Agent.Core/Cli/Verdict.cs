using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Cli
{
    // The one line every cts command answers with first:
    //
    //     <ok|partial|error> <command> key=value ...
    //
    // The reader is mostly an agent, and the first thing it needs is the
    // outcome; the whole payload is one flag away (--json).
    public static class Verdict
    {
        public const string Ok = "ok";
        public const string Error = "error";
        public const string Partial = "partial";

        // One value as it appears on the line: numbers and bare words stay
        // bare, anything with a space, an `=` or a quote is quoted, a line
        // break is written \n so the line stays one.
        public static string Quote(object value)
        {
            if (value == null) return "?";
            if (value is bool b) return b ? "true" : "false";
            if (value is double || value is float)
                return Convert.ToDouble(value, CultureInfo.InvariantCulture).ToString("G6", CultureInfo.InvariantCulture).Replace("E", "e");
            var text = value is IDictionary<string, object> || value is IList<object> ? Cts.Agent.Json.Serialize(value) : Convert.ToString(value, CultureInfo.InvariantCulture);
            if (text.Length > 0 && !text.Any(c => char.IsWhiteSpace(c) || c == '=' || c == '"')) return text;
            return "\"" + text.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", "\\r").Replace("\n", "\\n") + "\"";
        }

        // `<status> <command> key=value ...`; a pair whose value is null is left
        // out rather than rendered as a guess.
        public static string Line(string status, string command, IEnumerable<KeyValuePair<string, object>> pairs)
        {
            var parts = new List<string> { status, command };
            parts.AddRange(pairs.Where(p => p.Value != null).Select(p => p.Key + "=" + Quote(p.Value)));
            return string.Join(" ", parts);
        }

        // The first line of a command that failed, with the way out when cts knows one.
        public static string ErrorLine(string command, string cause, string next)
        {
            var line = Line(Error, command, new[] { Pair("cause", cause) });
            return string.IsNullOrEmpty(next) ? line : line + "\nNext: " + next;
        }

        public static KeyValuePair<string, object> Pair(string key, object value)
        {
            return new KeyValuePair<string, object>(key, value);
        }
    }
}
