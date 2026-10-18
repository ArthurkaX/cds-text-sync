using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A VAR_OUTPUT member its callable and owned methods/actions never write:
    // no assignment to it or to a member or element of it, no output mapping
    // into it or passing to a callee's VAR_IN_OUT, no call of it.
    internal sealed class CTS0009 : Rule
    {
        internal CTS0009() : base("CTS0009", "Output not assigned", Analysis.Severity.Suspicious, "Interfaces", "VAR_OUTPUT members that are never assigned by their callable.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var outputs = unit.Members("VAR_OUTPUT").ToList();
            if (outputs.Count == 0) yield break;
            var candidates = new[] { unit }.Concat(context.Snapshot.OwnedBy(unit.QualifiedName));
            var assigned = new HashSet<string>(candidates.Where(item => !string.IsNullOrEmpty(item.Implementation)).SelectMany(item => StBlocks.Written(item.Body.Text).Concat(context.Graph.InOutArguments(item))), StringComparer.OrdinalIgnoreCase);
            foreach (var member in outputs)
            {
                if (assigned.Contains(member.Name)) continue;
                yield return Finding.In(unit, "output '" + member.Name + "' is never assigned by " + unit.QualifiedName,
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }
    }
}
