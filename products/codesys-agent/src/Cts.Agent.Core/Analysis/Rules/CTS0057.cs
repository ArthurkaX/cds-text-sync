using System;
using System.Collections.Generic;
using System.Numerics;

namespace Cts.Analysis.Rules
{
    // "FOR i := 0 TO 200" with i : SINT: the counter cannot hold the bounds,
    // so the loop wraps around and never ends or skips its range.
    internal sealed class CTS0057 : Rule
    {
        internal CTS0057() : base("CTS0057", "Inadequate FOR counter type", Analysis.Severity.Danger, "Correctness", "A FOR counter type cannot represent its literal loop bounds.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            Dictionary<string, string> types = null;
            foreach (var loop in ForLoop.Of(unit))
            {
                if (loop.Literal == null || loop.Counter == null) continue;
                if (types == null)
                {
                    types = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    foreach (var member in context.Snapshot.MembersSeenBy(unit))
                    {
                        var shape = StDeclarations.ClassifyType(member.Type);
                        if (shape.Kind == "scalar" && !types.ContainsKey(member.Name)) types[member.Name] = shape.Base;
                    }
                }
                var type = (loop.InlineType ?? (types.TryGetValue(loop.Counter, out var declared) ? declared : "")).ToUpperInvariant();
                var limits = IecTypes.Range(type);
                if (limits == null) continue;
                BigInteger start = loop.StartValue, end = loop.EndValue, step = loop.StepValue ?? 1;
                if (step == 0 || start < end && step < 0 || start > end && step > 0) continue;
                BigInteger low = step > 0 ? start : end, high = step > 0 ? end : start;
                var violations = new List<string>();
                if (low < limits.Item1) violations.Add("lower bound " + low + " < " + limits.Item1);
                if (high > limits.Item2) violations.Add("upper bound " + high + " > " + limits.Item2);
                if (violations.Count == 0) continue;
                var header = loop.Text.Trim();
                yield return Finding.In(unit, "FOR counter '" + loop.Counter + "' has type " + type + ", but its literal range [" + low + ".." + high + "] exceeds the type range ["
                    + limits.Item1 + ".." + limits.Item2 + "] (" + string.Join("; ", violations) + ")",
                    unit.Body.At(loop.Start), unit.Body.At(loop.BodyStart), header, header);
            }
        }
    }
}
