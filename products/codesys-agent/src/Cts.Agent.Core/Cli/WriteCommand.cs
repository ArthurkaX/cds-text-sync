using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using System.Threading;
using Cts.Agent;
using Cts.Analysis;
using static Cts.Agent.JsonMap;

namespace Cts.Cli
{
    // `cts write NAME VALUE [NAME VALUE ...]`: the pairs in one PLC cycle,
    // then each read back until the PLC shows it. The runtime applies a write
    // on a task cycle, so the read-back polls a short while; a value it still
    // does not show is said so (confirmed=false and a note), never printed as
    // verified.
    public static class WriteCommand
    {
        internal const double ReadBackS = 2.0;
        const double ReadBackPollS = 0.2;
        public const string NotConnected = "Not connected: the PLC session is not logged in. Run 'cts connect' first "
            + "(or log in through the CODESYS UI).";

        // `INT#0`, `REAL#1.5`, `T#2s`: the PLC may print a value with its type.
        static readonly Regex TypePrefix = new Regex("^[A-Za-z_][A-Za-z0-9_]*#");
        static readonly Regex EnumValue = new Regex(@"^[A-Za-z_]\w*\.[A-Za-z_]\w*$");

        public static IDictionary<string, object> Execute(CliCall call)
        {
            var words = call.Options.Arguments;
            if (words.Count % 2 == 1)
                throw Usage(words[words.Count - 1] + " has no value: cts write takes NAME VALUE pairs");
            var pairs = Enumerable.Range(0, words.Count / 2).Select(i => new KeyValuePair<string, string>(words[2 * i], words[2 * i + 1])).ToList();
            if (pairs.Select(p => p.Key).Distinct().Count() != pairs.Count) throw Usage("a name is written twice");

            var values = new Dictionary<string, object>();
            foreach (var pair in pairs) values[pair.Key] = pair.Value;
            var answer = call.Call("vars.write", new Dictionary<string, object> { { "values", values } });
            if (!Equals(Value(answer, "logged_in"), true)) throw Refused(NotConnected, "cts connect");
            var rows = Rows(answer);
            var watch = Stopwatch.StartNew();
            Func<double> clock = () => watch.Elapsed.TotalSeconds;
            Action<double> sleep = s => Thread.Sleep(TimeSpan.FromSeconds(s));
            Func<string, IDictionary<string, object>> read = name => ReadBack(call, name);

            if (pairs.Count == 1)
            {
                var row = rows.FirstOrDefault() ?? new Dictionary<string, object>();
                if (!Equals(Value(row, "ok"), true)) throw Refused("Write variable error: " + ErrorOf(row, "write failed"), null);
                var written = Value(row, "text") as string ?? pairs[0].Value;
                var data = new Dictionary<string, object> { { "name", pairs[0].Key }, { "written", true }, { "value", written } };
                foreach (var item in Confirm(pairs[0].Key, pairs[0].Value, written, read, clock, sleep)) data[item.Key] = item.Value;
                return data;
            }

            var refused = rows.Where(r => !Equals(Value(r, "ok"), true) && !Equals(CodeOf(r), "not_written"))
                .Select(r => Value(r, "name") + ": " + ErrorOf(r, "write failed")).ToList();
            if (refused.Count > 0) throw Refused("nothing written; " + string.Join("; ", refused), null);
            var results = new List<object>();
            for (var i = 0; i < pairs.Count; i++)
            {
                var expected = (i < rows.Count ? Value(rows[i], "text") as string : null) ?? pairs[i].Value;
                var result = new Dictionary<string, object> { { "name", pairs[i].Key } };
                foreach (var item in Confirm(pairs[i].Key, pairs[i].Value, expected, read, clock, sleep)) result[item.Key] = item.Value;
                results.Add(result);
            }
            return new Dictionary<string, object>
            {
                { "written", true }, { "results", results }, { "count", (long)results.Count },
                { "confirmed", results.All(r => Equals(((IDictionary<string, object>)r)["confirmed"], true)) },
            };
        }

        public static Answer Build(IDictionary<string, object> data)
        {
            if (!data.ContainsKey("results"))
            {
                return new Answer()
                    .Add("name", Value(data, "name"))
                    .Add("value", Shown(data))
                    .Add("confirmed", Value(data, "confirmed"))
                    .Add("written_as", Value(data, "written_as"))
                    .Detail(Value(data, "note"))
                    .Detail(Value(Value(data, "read_back") as IDictionary<string, object>, "unavailable"));
            }
            var rows = ((IEnumerable<object>)data["results"]).OfType<IDictionary<string, object>>().ToList();
            var answer = new Answer().Add("count", Value(data, "count")).Add("confirmed", (long)rows.Count(r => Equals(Value(r, "confirmed"), true)));
            foreach (var row in rows)
                answer.Detail(Value(row, "name") + " = " + Shown(row) + (Equals(Value(row, "confirmed"), true) ? "" : " (not confirmed)"));
            return answer;
        }

        // What the PLC showed after the write, or why it could not be read.
        static object Shown(IDictionary<string, object> row)
        {
            var back = Value(row, "read_back") as IDictionary<string, object>;
            return Value(back, "value") ?? (back != null && back.ContainsKey("unavailable") ? "unreadable" : null);
        }

        // read_back and confirmed of a written value, with written_as when the
        // IDE spells it otherwise and a note when the PLC did not show it.
        public static Dictionary<string, object> Confirm(string name, string typed, string expected,
            Func<string, IDictionary<string, object>> read, Func<double> clock, Action<double> sleep)
            => Confirm(name, typed, expected, read, clock, sleep, clock() + ReadBackS);

        // One deadline shared by many values: once it has passed, a value is
        // read once and not waited for.
        internal static Dictionary<string, object> Confirm(string name, string typed, string expected,
            Func<string, IDictionary<string, object>> read, Func<double> clock, Action<double> sleep, double deadline)
        {
            IDictionary<string, object> back;
            bool confirmed;
            while (true)
            {
                back = read(name);
                if (back.ContainsKey("unavailable")) { confirmed = false; break; }
                var shown = Value(back, "value") as string;
                if (Agree(expected, shown)) { confirmed = true; break; }
                // An enum shows its member; a number written to it is checked
                // against the member's value.
                if (shown != null && EnumValue.IsMatch(shown.Trim()) && IecTypes.IsDecimal(Bare(expected)))
                {
                    var member = read(shown.Trim());
                    if (!member.ContainsKey("unavailable") && Agree(expected, Value(member, "value") as string)) { confirmed = true; break; }
                }
                if (clock() >= deadline) { confirmed = false; break; }
                sleep(ReadBackPollS);
            }
            var result = new Dictionary<string, object> { { "read_back", back }, { "confirmed", confirmed } };
            if (!Agree(typed, expected)) result["written_as"] = expected;
            if (!confirmed && !back.ContainsKey("unavailable"))
                result["note"] = "the PLC still reports '" + Value(back, "value") + "' after writing '" + expected + "' and waiting "
                    + ReadBackS.ToString("0.###", CultureInfo.InvariantCulture) + "s; the program may overwrite it every cycle, "
                    + "or the write may not have taken effect. Not confirmed.";
            return result;
        }

        // Whether the PLC's rendering of a value matches what was written:
        // case, blanks and a type prefix aside, an enum's member by its name,
        // two spellings of one number, two string literals of one content, case
        // included (the IDE answers a write with 'it's' and a read with
        // 'it$'s'). Anything else is a mismatch: a write is never reported
        // verified on a guess.
        internal static bool Agree(string written, string read)
        {
            if (read == null || written == null) return false;
            var left = Bare(written);
            var right = Bare(read);
            if (Quoted(left) && Quoted(right) && left[0] == right[0])
                return Content(left) == Content(right);
            if (string.Equals(left, right, StringComparison.OrdinalIgnoreCase)) return true;
            if (EnumValue.IsMatch(right) && StText.IsIdentifier(left))
                return string.Equals(left, Snapshot.LastSegment(right), StringComparison.OrdinalIgnoreCase);
            double a, b;
            return double.TryParse(left, NumberStyles.Float, CultureInfo.InvariantCulture, out a)
                && double.TryParse(right, NumberStyles.Float, CultureInfo.InvariantCulture, out b)
                && Math.Abs(a - b) <= 1e-9 * Math.Max(1.0, Math.Abs(a));
        }

        static string Bare(string text) => TypePrefix.Replace(text.Trim(), "", 1);

        static bool Quoted(string text) => text.Length >= 2 && (text[0] == '\'' || text[0] == '"') && text[text.Length - 1] == text[0];

        // A string literal's content: `$'` and `$"` are the quote, `$$` the
        // dollar, `$N` `$L` `$R` `$T` `$P` the control characters and `$hh`
        // (`$hhhh` in a WSTRING) a code; a `$` before anything else stays.
        static string Content(string literal)
        {
            var body = literal.Substring(1, literal.Length - 2);
            var digits = literal[0] == '"' ? 4 : 2;
            var text = new System.Text.StringBuilder();
            for (var i = 0; i < body.Length; i++)
            {
                if (body[i] != '$' || i + 1 >= body.Length) { text.Append(body[i]); continue; }
                var next = char.ToUpperInvariant(body[i + 1]);
                var escaped = next == 'N' || next == 'L' ? '\n' : next == 'R' ? '\r' : next == 'T' ? '\t' : next == 'P' ? '\f'
                    : next == '$' || next == '\'' || next == '"' ? body[i + 1] : '\0';
                int code;
                if (escaped != '\0') { text.Append(escaped); i++; }
                else if (i + digits < body.Length && int.TryParse(body.Substring(i + 1, digits), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out code))
                {
                    text.Append((char)code);
                    i += digits;
                }
                else text.Append('$');
            }
            return text.ToString();
        }

        // One variable read after the write: {name, value} as the IDE spells
        // it, or {unavailable: why}. An empty read-back is never shown as an
        // empty variable.
        internal static IDictionary<string, object> ReadBack(CliCall call, string name)
        {
            IDictionary<string, object> answer;
            try { answer = call.Call("vars.read", new Dictionary<string, object> { { "names", new List<object> { name } } }); }
            catch (CliFailure f) { return Unavailable(f.Message); }
            if (!Equals(Value(answer, "logged_in"), true)) return Unavailable(NotConnected);
            var result = Rows(answer).FirstOrDefault() ?? new Dictionary<string, object>();
            if (!Equals(Value(result, "ok"), true))
                return Unavailable("Read variable error: " + (Equals(CodeOf(result), "not_exported")
                    ? "'" + name + "' is not exported to the online application. It may be misspelled, not declared as a symbol, "
                        + "or not compiled into the PLC."
                    : ErrorOf(result, "read failed")));
            return new Dictionary<string, object>
            {
                { "name", name },
                { "value", Value(result, "text") as string ?? Convert.ToString(Value(result, "value") ?? "", CultureInfo.InvariantCulture) },
            };
        }

        static IDictionary<string, object> Unavailable(string why) => new Dictionary<string, object> { { "unavailable", why } };

        static List<IDictionary<string, object>> Rows(IDictionary<string, object> answer)
        {
            return (Value(answer, "results") as IEnumerable<object> ?? new object[0]).OfType<IDictionary<string, object>>().ToList();
        }

        static object CodeOf(IDictionary<string, object> row) => Value(Value(row, "error") as IDictionary<string, object>, "code");

        static string ErrorOf(IDictionary<string, object> row, string fallback)
        {
            return Value(Value(row, "error") as IDictionary<string, object>, "message") as string ?? fallback;
        }

        static CliFailure Usage(string message) => new CliFailure("write", "usage", message, "cts write --help", 2);

        static CliFailure Refused(string message, string next) => new CliFailure("write", message, message, next, 1);

    }
}
