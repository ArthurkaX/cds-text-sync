using System.Collections.Generic;

namespace Cts.Analysis.Rules
{
    // Enumeration declarations without the strict attribute.
    internal sealed class CTS0067 : Rule
    {
        internal CTS0067() : base("CTS0067", "Non-strict enumeration", Analysis.Severity.Suspicious, "Correctness", "Enumerations should use the strict attribute.", "TYPE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var dut = unit.Dut;
            if (dut == null || dut.Kind != "enum" || dut.Strict) yield break;
            yield return Finding.In(unit, "enumeration '" + dut.Name + "' is not declared with {attribute 'strict'}",
                unit.DeclarationSection.At(0), unit.DeclarationSection.At(0) + dut.Name.Length, dut.Name, dut.Name);
        }
    }
}
