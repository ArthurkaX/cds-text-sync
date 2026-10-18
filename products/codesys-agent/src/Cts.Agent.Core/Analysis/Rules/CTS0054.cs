using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "small := wide" between variables: DINT into INT loses range, LREAL
    // into REAL precision, a real into an integer both. A named argument of
    // a call ("F(x := wide)") is the callee's business.
    internal sealed class CTS0054 : Rule
    {
        // Not a member after '.'.
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<target>[A-Za-z_]\w*)\s*:=\s*(?<source>[A-Za-z_]\w*)\b");
        static readonly Dictionary<string, int> RealOrder = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase) { ["REAL"] = 1, ["LREAL"] = 2 };

        internal CTS0054() : base("CTS0054", "Implicit narrowing conversion", Analysis.Severity.Suspicious, "Correctness", "Assignments must not silently narrow a known scalar type.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var types = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind == "scalar" && !types.ContainsKey(member.Name)) types[member.Name] = shape.Base.ToUpperInvariant();
            }
            var section = unit.Body;
            foreach (Match match in Assignment.Matches(section.Text))
            {
                if (!types.TryGetValue(match.Groups["target"].Value, out var target) || !types.TryGetValue(match.Groups["source"].Value, out var source)) continue;
                var reason = Narrowing(source, target);
                if (reason == null || StCalls.InArgument(section.Text, match.Index)) continue;
                yield return Finding.In(unit, "implicit narrowing conversion from " + source + " to " + target + " may lose " + reason + "; use an explicit TO_ conversion",
                    section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
        }

        // What source into target may lose, null when nothing. Integer into
        // real is not reported: its precision loss needs a value to prove.
        static string Narrowing(string source, string target)
        {
            var sourceRange = IecTypes.Range(source);
            var targetRange = IecTypes.Range(target);
            if (sourceRange != null && targetRange != null) return targetRange.Item1 <= sourceRange.Item1 && sourceRange.Item2 <= targetRange.Item2 ? null : "value range";
            if (RealOrder.TryGetValue(source, out var sourceOrder) && RealOrder.TryGetValue(target, out var targetOrder)) return sourceOrder > targetOrder ? "precision" : null;
            return RealOrder.ContainsKey(source) && targetRange != null ? "range and fractional precision" : null;
        }
    }
}
