using System;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis
{
    // What the IFs around a use prove about a guarded value. A test reads one
    // condition or AND operand: true when it implies the guard ("p <> 0",
    // "n > 5"), false when it implies its negation ("p = 0"), null neither;
    // otherwise does the same for the condition being false (after "n <= 0"
    // fails n is non-zero; after "n > 5" fails nothing is known).
    // unchanged(start) says the value is not reassigned between the absolute
    // offset start and the use.
    internal static class Guards
    {
        static readonly Regex Condition = new Regex(@"^\s*(?:IF|ELSIF)\b(?<condition>.*)$", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex Either = new Regex(@"\b(?:OR|XOR|OR_ELSE)\b", RegexOptions.IgnoreCase);
        static readonly Regex And = new Regex(@"\bAND(?:_THEN)?\b", RegexOptions.IgnoreCase);
        static readonly Regex If = new Regex(@"\bIF\b", RegexOptions.IgnoreCase);
        static readonly Regex Exit = new Regex(@"\GIF\b(?<condition>.*?)\bTHEN\b(?<body>.*?)\bEND_IF\b", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex Terminal = new Regex(@"\b(?:RETURN|EXIT|CONTINUE)\b", RegexOptions.IgnoreCase);

        // true: an enclosing arm requires the guard (its condition, or an AND
        // operand of it, past the condition itself: AND evaluates both
        // sides), or an earlier arm of its IF failing implies it. false: the
        // same for the negation; it wins. null: neither.
        internal static bool? At(Block root, int offset, Func<string, bool?> test, Func<string, bool?> otherwise, Func<int, bool> unchanged)
        {
            bool? state = null;
            foreach (var block in root.Descendants().Where(block => block.Kind == "IF" && block.End.HasValue && block.Start <= offset && offset < block.End.Value))
            {
                var index = block.Branches.FindIndex(branch => branch.Start <= offset && offset < branch.End);
                if (index < 0) continue;
                var branch = block.Branches[index];
                var earlier = block.Branches.Take(index).Select(previous => Whole(previous.Label, otherwise)).ToList();
                var arm = earlier.Contains(false) ? false : earlier.Contains(true) ? true
                    : offset >= branch.Start + branch.Label.Length ? Arm(branch.Label, test) : null;
                if (arm == null || !unchanged(branch.Start)) continue;
                if (arm == false) return false;
                state = true;
            }
            return state;
        }

        // "IF <condition> THEN ... RETURN/EXIT/CONTINUE ... END_IF" before the
        // use (absolute offset) in section whose failing implies the guard,
        // the value unchanged since.
        internal static bool ExitsBefore(Section section, int offset, Func<string, bool?> otherwise, Func<int, bool> unchanged)
        {
            var text = section.Text.Substring(0, offset - section.Base);
            return If.Matches(text).Cast<Match>().Select(keyword => Exit.Match(text, keyword.Index))
                .Any(guard => guard.Success && otherwise(guard.Groups["condition"].Value.Trim()) == true && Terminal.IsMatch(guard.Groups["body"].Value) && unchanged(section.At(guard.Index + guard.Length)));
        }

        // No "name := ...;" in section between the absolute offsets start and
        // use: the assignment the use is part of happens after it.
        internal static Func<int, bool> Unchanged(Section section, string name, int use)
        {
            var assigned = Assignment(name);
            return start => !assigned.IsMatch(section.Text.Substring(start - section.Base, use - start));
        }

        // "name := <value>;" for name dotted with any spacing.
        internal static Regex Assignment(string name) =>
            new Regex(@"(?<![\w.])" + string.Join(@"\s*\.\s*", StText.Unspaced(name).Split('.').Select(Regex.Escape)) + @"\s*:=(?<value>[^;]*);", RegexOptions.IgnoreCase);

        // An IF or ELSIF label's condition, null for another label.
        internal static string ConditionOf(string label)
        {
            var condition = Condition.Match(label);
            return condition.Success ? condition.Groups["condition"].Value.Trim() : null;
        }

        // An IF or ELSIF label's whole condition put to test.
        internal static bool? Whole(string label, Func<string, bool?> test)
        {
            var condition = ConditionOf(label);
            return condition != null ? test(condition) : null;
        }

        static bool? Arm(string label, Func<string, bool?> test)
        {
            var text = ConditionOf(label);
            if (text == null) return null;
            var whole = test(text);
            if (whole.HasValue || Either.IsMatch(text)) return whole;
            var operands = And.Split(text).Select(operand => test(operand.Trim())).ToList();
            return operands.Contains(false) ? false : operands.Contains(true) ? true : (bool?)null;
        }
    }
}
