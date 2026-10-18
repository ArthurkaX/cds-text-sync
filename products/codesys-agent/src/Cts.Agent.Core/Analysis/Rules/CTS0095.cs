using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A local POU variable declared with a direct hardware address.
    internal sealed class CTS0095 : Rule
    {
        static readonly Regex VariableOpen = new Regex(@"^\s*(?<scope>VAR(?:_(?:INPUT|OUTPUT|IN_OUT|TEMP|STAT))?)\b", RegexOptions.IgnoreCase);
        static readonly Regex AtDeclaration = new Regex(@"\b(?<name>[A-Za-z_]\w*)\s+AT\s+%(?:I|Q|M)(?:X|B|W|D|L)\d+(?:\.\d+)?\b", RegexOptions.IgnoreCase);
        static readonly Regex VariableClose = new Regex(@"^\s*END_VAR\b", RegexOptions.IgnoreCase);
        static readonly HashSet<string> LocalScopes = new HashSet<string> { "VAR", "VAR_TEMP", "VAR_STAT" };

        internal CTS0095() : base("CTS0095", "Local variable uses AT hardware mapping", Analysis.Severity.Suspicious, "Code quality", "Local POU variables should not own direct hardware mappings.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            string scope = null;
            foreach (var line in unit.DeclarationSection.Lines())
            {
                var value = line.Item3;
                if (VariableClose.IsMatch(value))
                {
                    scope = null;
                    continue;
                }

                var opener = VariableOpen.Match(value);
                if (opener.Success)
                {
                    scope = opener.Groups["scope"].Value.ToUpperInvariant();
                    continue;
                }
                if (scope == null || !LocalScopes.Contains(scope)) continue;

                foreach (Match match in AtDeclaration.Matches(value))
                {
                    var name = match.Groups["name"];
                    var offset = line.Item2 + name.Index;
                    yield return Finding.In(unit, "local variable '" + name.Value + "' uses an AT hardware mapping; keep hardware addresses in a global I/O map",
                        offset, offset + name.Length, name.Value, match.Value);
                }
            }
        }
    }
}
