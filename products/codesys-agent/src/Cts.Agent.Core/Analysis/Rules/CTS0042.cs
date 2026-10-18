using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A timer call that supplies an explicit zero preset time ("PT := T#0s").
    internal sealed class CTS0042 : Rule
    {
        static readonly Regex Call = new Regex(
            @"\b(?<timer>[A-Za-z_]\w*)\s*\([^;]*?\bPT\s*:=\s*(?<pt>T#0(?:ms|s|m|h|d))\b[^;]*?\)",
            RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex KnownTypes = new Regex(@"\b(?:TON|TOF|TP)\b", RegexOptions.IgnoreCase);

        internal CTS0042() : base("CTS0042", "Zero timer preset time", Analysis.Severity.Suspicious, "Correctness", "TON, TOF or TP is called with an explicit zero PT value.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Body.IsEmpty) yield break;
            // A method's or action's timer is usually an instance of its function block.
            var owner = context.Snapshot.Find(unit.OwnerId);
            if (!KnownTypes.IsMatch(unit.Declaration ?? "") && !KnownTypes.IsMatch(owner?.Declaration ?? "")) yield break;
            foreach (Match match in Call.Matches(unit.Body.Text))
            {
                var preset = match.Groups["pt"];
                yield return Finding.In(unit, "timer preset time PT is zero", unit.Body.At(preset.Index), unit.Body.At(preset.Index + preset.Length),
                    preset.Value, match.Value);
            }
        }
    }
}
