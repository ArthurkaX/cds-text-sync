using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A SEL or MUX value argument contains a call that may have side effects.
    internal sealed class CTS0083 : Rule
    {
        static readonly Regex Selector = new Regex(@"\b(?:SEL|MUX)\s*\(", RegexOptions.IgnoreCase);
        static readonly HashSet<string> PureCalls = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "ABS", "CONCAT", "FIND", "LEFT", "LEN", "LIMIT", "MAX", "MID", "MIN", "REPLACE", "RIGHT", "SEL", "MUX", "SIZEOF", "TO_STRING",
        };

        internal CTS0083() : base("CTS0083", "SEL/MUX argument may have side effects", Analysis.Severity.Suspicious, "Correctness", "A SEL or MUX argument contains a call that may execute even when its value is not selected.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var instances = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
                if (context.Snapshot.IsFunctionBlockType(member.Type.Trim())) instances.Add(member.Name);
            var text = section.Text;
            foreach (Match selector in Selector.Matches(text))
            {
                var closing = StCalls.Close(text, selector.Index + selector.Length - 1);
                if (closing < 0) continue;
                var arguments = StCalls.Arguments(text.Substring(selector.Index + selector.Length, closing - selector.Index - selector.Length));
                if (arguments.Count < 3) continue;
                var sideEffects = new List<string>();
                foreach (var argument in arguments.Skip(1))
                    foreach (Match call in StCalls.Call.Matches(argument))
                    {
                        var name = call.Groups["name"].Value;
                        if (MayHaveSideEffect(name, instances) && !sideEffects.Contains(name, StringComparer.Ordinal)) sideEffects.Add(name);
                    }
                if (sideEffects.Count == 0) continue;
                var expression = text.Substring(selector.Index, closing + 1 - selector.Index);
                var calls = string.Join(", ", sideEffects);
                yield return Finding.In(unit,
                    "SEL/MUX evaluates argument call(s) with possible side effects before selecting a value: " + calls,
                    section.At(selector.Index), section.At(closing + 1), selector.Value.Trim(), expression);
            }
        }

        static bool MayHaveSideEffect(string callName, HashSet<string> instances)
        {
            var upper = callName.ToUpperInvariant();
            return instances.Contains(callName) || (!PureCalls.Contains(upper) && !upper.StartsWith("TO_", StringComparison.Ordinal) && !upper.Contains("_TO_"));
        }
    }
}
