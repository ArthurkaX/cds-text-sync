using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Analysis.Rules
{
    // Local and interface declarations that hide global or owner symbols.
    internal sealed class CTS0070 : Rule
    {
        static readonly HashSet<string> LocalScopes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "VAR", "VAR_TEMP", "VAR_STAT", "VAR_INPUT", "VAR_OUTPUT", "VAR_IN_OUT",
        };

        internal CTS0070() : base("CTS0070", "Shadowed symbol", Analysis.Severity.Suspicious, "Code quality", "Local symbols must not hide global variables or owning FB members.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var owner = context.Snapshot.InstanceOwner(unit);
            var ownerNames = new HashSet<string>(owner == null ? Enumerable.Empty<string>() : owner.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members().Where(member => member.Name.Length > 0 && LocalScopes.Contains(member.Scope)))
            {
                var hidden = ownerNames.Contains(member.Name) ? "member of '" + owner.QualifiedName + "'" : context.Globals.Declares(member.Name) ? "global variable" : null;
                var declared = member.Name + " : " + member.Type;
                if (hidden != null)
                    yield return Finding.In(unit, "local symbol '" + member.Name + "' hides a " + hidden, unit.MemberOffset(member), anchor: member.Name, context: declared);
                if (!seen.Add(member.Name))
                    yield return Finding.In(unit, "local symbol '" + member.Name + "' duplicates another declaration in this POU", unit.MemberOffset(member), anchor: member.Name, context: declared);
            }
        }
    }
}
