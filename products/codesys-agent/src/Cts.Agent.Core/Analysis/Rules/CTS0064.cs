using System.Collections.Generic;

namespace Cts.Analysis.Rules
{
    // A pointer in VAR RETAIN, VAR PERSISTENT or a persistent variable list
    // keeps an address across a restart or download, where it no longer
    // points at what it did.
    internal sealed class CTS0064 : Rule
    {
        internal CTS0064() : base("CTS0064", "Retained pointer", Analysis.Severity.Danger, "Correctness", "A RETAIN/PERSISTENT pointer may contain an invalid address after restart.", "ANY")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var block in unit.VarBlocks)
            {
                var persistent = block.Persistent || unit.Kind == Analysis.Kinds.GvlPersistent;
                if (!persistent && !block.Retain) continue;
                foreach (var member in block.Members)
                {
                    var shape = StDeclarations.ClassifyType(member.Type);
                    if (shape.Kind != "scalar" || shape.Base != "POINTER") continue;
                    var offset = unit.MemberOffset(member);
                    if (offset == null) continue;
                    yield return Finding.In(unit, "pointer '" + member.Name + "' is declared in " + (persistent ? "PERSISTENT" : "RETAIN") + " storage; its address may be invalid after a restart",
                        offset, offset + member.Name.Length, member.Name, member.Type);
                }
            }
        }
    }
}
