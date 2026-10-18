using System.Collections.Generic;
using System.Numerics;

namespace Cts.Analysis.Rules
{
    // "FOR i := 1 TO 10 BY 0" never ends; "FOR i := 1 TO 10 BY -1" never runs.
    internal sealed class CTS0038 : Rule
    {
        internal CTS0038() : base("CTS0038", "Invalid FOR loop step", Analysis.Severity.Danger, "Correctness", "A FOR loop has a zero or directionally invalid literal step.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var loop in ForLoop.Of(unit))
            {
                if (loop.Literal == null || loop.StepValue == null) continue;
                BigInteger start = loop.StartValue, end = loop.EndValue, step = loop.StepValue.Value;
                string message;
                if (step == 0) message = "FOR loop has a zero step and cannot make progress";
                else if (start < end && step < 0 || start > end && step > 0) message = "FOR loop step moves away from its literal boundary";
                else continue;
                var literal = loop.Literal.Groups["step"];
                var offset = unit.Body.At(loop.HeaderStart + literal.Index);
                yield return Finding.In(unit, message, offset, offset + literal.Length, literal.Value, loop.Text.Trim());
            }
        }
    }
}
