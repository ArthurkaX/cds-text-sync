using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Finds pointer dereferences in declaration initializers, before body guards can run.
    internal sealed class CTS0092 : Rule
    {
        static readonly Regex Dereference = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s*\^");

        internal CTS0092() : base("CTS0092", "Pointer dereference in declaration initializer", Analysis.Severity.Danger, "Correctness", "A pointer is dereferenced before the POU body can establish a guard.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.DeclarationSection;
            if (section.IsEmpty) yield break;
            var pointers = ProjectLookup.PointerMembers(unit, context);
            if (pointers.Count == 0) yield break;

            foreach (Match match in Dereference.Matches(section.Text))
            {
                var name = match.Groups["name"];
                if (!pointers.TryGetValue(name.Value.ToLowerInvariant(), out var pointer)) continue;
                var statementStart = match.Index == 0 ? 0 : section.Text.LastIndexOf(';', match.Index - 1) + 1;
                var statementEnd = section.Text.IndexOf(';', match.Index + match.Length);
                if (statementEnd < 0) statementEnd = section.Text.Length;
                var statement = section.Text.Substring(statementStart, statementEnd - statementStart);
                var assignment = statement.IndexOf(":=", System.StringComparison.Ordinal);
                if (assignment < 0 || match.Index < statementStart + assignment + 2) continue;
                var contextText = statement.Trim();
                yield return Finding.In(unit,
                    "pointer '" + pointer.Item1 + "' is dereferenced in a declaration initializer before the POU body can validate it",
                    section.At(name.Index), section.At(match.Index + match.Length), match.Value.Trim(), contextText);
            }
        }
    }
}
