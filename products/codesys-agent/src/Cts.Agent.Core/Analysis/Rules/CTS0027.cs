using System.Collections.Generic;

namespace Cts.Analysis.Rules
{
    // A function-block instance in a function's or method's VAR: it starts
    // afresh on every call, so its timers and edges never see a second cycle.
    internal sealed class CTS0027 : Rule
    {
        internal CTS0027() : base("CTS0027", "Temporary function-block instance", Analysis.Severity.Danger, "Correctness", "Local function-block instances are recreated on every call.", Analysis.Kinds.Function, Analysis.Kinds.Method)
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var member in unit.Members("VAR", "VAR_TEMP"))
            {
                if (!context.Snapshot.IsFunctionBlockType(member.Type))
                {
                    continue;
                }

                yield return Finding.In(unit,
                    "local function-block instance '" + member.Name + "' is recreated on each call",
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }
    }
}
