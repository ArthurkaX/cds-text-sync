using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // A function block with no VAR of its own and no methods, actions or
    // properties: nothing survives between calls, so a FUNCTION would do.
    internal sealed class CTS0032 : Rule
    {
        static readonly HashSet<string> StateScopes = new HashSet<string> { "VAR", "VAR_STAT", "VAR_TEMP" };

        internal CTS0032() : base("CTS0032", "Stateless function block", Analysis.Severity.Style, "Style", "A stateless function block may be clearer as a FUNCTION.", Analysis.Kinds.FunctionBlock)
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.VarBlocks.Any(block => StateScopes.Contains(block.Scope)) || context.Snapshot.OwnedBy(unit.QualifiedName).Any()) yield break;
            var section = unit.DeclarationSection;
            if (!unit.Header.Groups["kind"].Value.Equals("FUNCTION_BLOCK", StringComparison.OrdinalIgnoreCase)) yield break;
            var name = unit.Header.Groups["name"];
            yield return Finding.In(unit, "function block '" + name.Value + "' has no internal state and may be better modelled as a FUNCTION", section.At(name.Index), section.At(name.Index) + name.Length,
                name.Value, "stateless FUNCTION_BLOCK");
        }
    }
}
