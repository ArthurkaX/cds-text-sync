using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Dynamic memory allocation or release in executable Structured Text.
    internal sealed class CTS0099 : Rule
    {
        static readonly Regex DynamicMemory = new Regex(@"\b(?<operation>__NEW|__DELETE)\b", RegexOptions.IgnoreCase);

        internal CTS0099() : base("CTS0099", "Dynamic memory operation", Analysis.Severity.Suspicious, "Correctness", "Dynamic memory operations can make cyclic execution unpredictable.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Implementation == null)
            {
                yield break;
            }

            foreach (Match match in DynamicMemory.Matches(unit.Body.Text))
            {
                var operation = match.Groups["operation"];
                yield return Finding.In(unit,
                    "dynamic memory operation '" + operation.Value + "' in implementation code; heap allocation and release can make cycle time and memory availability unpredictable",
                    unit.Body.At(operation.Index), unit.Body.At(operation.Index + operation.Length),
                    anchor: operation.Value, context: operation.Value + " in POU implementation");
            }
        }
    }
}
