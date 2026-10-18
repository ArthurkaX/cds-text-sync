using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A VAR_IN_OUT parameter no code assigns, passes to an output or to a
    // callee's VAR_IN_OUT, or calls (an instance's call or method changes
    // it): it is only read. A small
    // scalar reads as VAR_INPUT; anything larger keeps its reference as
    // VAR_IN_OUT CONSTANT, which is left alone. A function block's methods
    // and actions count as its code.
    internal sealed class CTS0076 : Rule
    {
        internal CTS0076() : base("CTS0076", "VAR_IN_OUT never written", Analysis.Severity.Style, "Interfaces", "VAR_IN_OUT parameters that are only read should be VAR_INPUT or VAR_IN_OUT CONSTANT.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var inOut = unit.VarBlocks.Where(block => block.Scope == "VAR_IN_OUT" && !block.Constant).SelectMany(block => block.Members).Where(member => member.Name.Length > 0).ToList();
            if (inOut.Count == 0) yield break;
            var written = StBlocks.Written(unit.Body.Text);
            written.UnionWith(context.Graph.InOutArguments(unit));
            foreach (var owned in context.Snapshot.OwnedBy(unit.QualifiedName))
            {
                var locals = new HashSet<string>(owned.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
                written.UnionWith(StBlocks.Written(owned.Body.Text).Concat(context.Graph.InOutArguments(owned)).Where(name => !locals.Contains(name)));
            }
            foreach (var member in inOut.Where(member => !written.Contains(member.Name)))
                yield return Finding.In(unit, "VAR_IN_OUT '" + member.Name + "' is never written; declare it as " + (IecTypes.Bytes(member.Type) <= 8 ? "VAR_INPUT" : "VAR_IN_OUT CONSTANT") + " if it is read-only",
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
        }
    }
}
