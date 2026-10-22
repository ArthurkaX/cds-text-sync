using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "r.x" through a REFERENCE with no __ISVALIDREF(r) guarding it (see
    // Guards), and not after "IF NOT __ISVALIDREF(r) THEN ... RETURN".
    internal sealed class CTS0061 : Rule
    {
        // A name and a member; not a member after '.'.
        static readonly Regex Access = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\s*\.\s*(?<member>[A-Za-z_]\w*)");
        static readonly Regex IsValid = new Regex(@"^\(?\s*(?<not>NOT\s+)?__ISVALIDREF\s*\(\s*(?<name>[A-Za-z_]\w*)\s*\)\s*\)?$", RegexOptions.IgnoreCase);

        internal CTS0061() : base("CTS0061", "Unchecked reference use", Analysis.Severity.Danger, "Correctness", "A REFERENCE is used without a simple dominating __ISVALIDREF check.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var references = new HashSet<string>(context.Snapshot.MembersSeenBy(unit).Where(member => StDeclarations.ClassifyType(member.Type).Base == "REFERENCE").Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (references.Count == 0) yield break;
            var section = unit.Body;
            foreach (Match match in Access.Matches(section.Text))
            {
                var name = match.Groups["name"].Value;
                var offset = section.At(match.Index);
                if (!references.Contains(name)) continue;
                Func<string, bool?> test = condition => IsValidTest(condition, name);
                Func<string, bool?> otherwise = condition => !test(condition);
                if (Guards.At(unit.Tree, offset, test, otherwise, start => true) == true || Guards.ExitsBefore(section, offset, (condition, at) => otherwise(condition), start => true)) continue;
                var expression = match.Value.Trim();
                yield return Finding.In(unit, "reference '" + name + "' is used without a dominating __ISVALIDREF check",
                    offset, section.At(match.Index + match.Length), expression, expression);
            }
        }

        // "__ISVALIDREF(name)": true; "NOT __ISVALIDREF(name)": false.
        static bool? IsValidTest(string test, string name)
        {
            var match = IsValid.Match(test);
            if (!match.Success || !match.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase)) return null;
            return !match.Groups["not"].Success;
        }
    }
}
