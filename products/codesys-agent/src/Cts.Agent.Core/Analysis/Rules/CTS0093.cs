using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "value : INT := refData.nValue" in VAR: the initial value reads
    // through a REFERENCE before any code can check __ISVALIDREF. Binding
    // one reference to another ("r2 : REFERENCE TO T := r1") reads nothing.
    internal sealed class CTS0093 : Rule
    {
        // A name with an optional member; not a member after '.'.
        static readonly Regex Use = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)(?:\s*\.\s*[A-Za-z_]\w*)?");
        static readonly Regex DirectBinding = new Regex(@"^\s*(?<left>[A-Za-z_]\w*)\s*:\s*REFERENCE\b.*?:=\s*(?<right>[A-Za-z_]\w*)\s*$", RegexOptions.IgnoreCase | RegexOptions.Singleline);

        internal CTS0093() : base("CTS0093", "Reference use in declaration initializer", Analysis.Severity.Danger, "Correctness", "A REFERENCE is read before the POU body can validate it.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var references = new HashSet<string>(context.Snapshot.MembersSeenBy(unit).Concat(context.Globals.Members)
                .Where(member => StDeclarations.ClassifyType(member.Type).Base == "REFERENCE").Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (references.Count == 0) yield break;
            var section = unit.DeclarationSection;
            var text = section.Text;
            foreach (Match match in Use.Matches(text))
            {
                var name = match.Groups["name"].Value;
                if (!references.Contains(name)) continue;
                var start = text.LastIndexOf(';', match.Index) + 1;
                var end = text.IndexOf(';', match.Index + match.Length);
                var statement = text.Substring(start, (end < 0 ? text.Length : end) - start);
                var assignment = statement.IndexOf(":=", StringComparison.Ordinal);
                if (assignment < 0 || match.Index < start + assignment + 2 || DirectBinding.IsMatch(statement)) continue;
                yield return Finding.In(unit, "reference '" + name + "' is used in a declaration initializer before its validity can be checked",
                    section.At(match.Index), section.At(match.Index + match.Length), match.Value.Trim(), statement.Trim());
            }
        }
    }
}
