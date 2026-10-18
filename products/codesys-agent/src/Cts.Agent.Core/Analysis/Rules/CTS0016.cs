using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A statement right after RETURN, EXIT or CONTINUE in the same block.
    internal sealed class CTS0016 : Rule
    {
        static readonly Regex Terminal = new Regex(@"\b(?:RETURN|EXIT|CONTINUE)\b\s*;", RegexOptions.IgnoreCase);
        static readonly Regex Word = new Regex(@"\b[A-Za-z_]\w*\b");
        static readonly HashSet<string> Boundaries = new HashSet<string> { "ELSE", "ELSIF", "END_IF", "END_CASE", "END_FOR", "END_WHILE", "END_REPEAT" };

        internal CTS0016() : base("CTS0016", "Unreachable code after control flow exit", Analysis.Severity.Suspicious, "Correctness", "Statements immediately following an unconditional control-flow exit.", "CALLABLE")
        {
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (Match terminal in Terminal.Matches(section.Text))
            {
                var next = Word.Match(section.Text, terminal.Index + terminal.Length);
                if (!next.Success || Boundaries.Contains(next.Value.ToUpperInvariant())) continue;
                yield return Finding.In(unit, "statement after " + terminal.Value.Trim() + " is unreachable", section.At(next.Index), section.At(next.Index + next.Length), next.Value, next.Value);
            }
        }
    }
}
