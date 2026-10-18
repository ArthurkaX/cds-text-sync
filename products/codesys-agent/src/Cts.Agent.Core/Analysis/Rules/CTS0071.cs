using System.Collections.Generic;

namespace Cts.Analysis.Rules
{
    // Variables whose statically known size is greater than 1024 bytes.
    internal sealed class CTS0071 : Rule
    {
        const int Limit = 1024;

        internal CTS0071() : base("CTS0071", "Large variable", Analysis.Severity.Suspicious, "Code quality", "Variables with a statically known size above the configured limit need review.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var member in unit.Members())
            {
                var size = IecTypes.Bytes(member.Type);
                if (size > Limit)
                    yield return Finding.In(unit, "variable '" + member.Name + "' has a statically known size of " + size + " bytes",
                        unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }
    }
}
