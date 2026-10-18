using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // Two non-empty arms of one IF or CASE with the same statements,
    // comments and layout aside: one condition is likely a copy left
    // unedited.
    internal sealed class CTS0084 : Rule
    {
        static readonly Regex Punctuation = new Regex(@"\s*([,;:=()\[\]^.+*/<>-])\s*");

        internal CTS0084() : base("CTS0084", "Identical control-flow branch bodies", Analysis.Severity.Suspicious, "Code quality", "Two non-empty branches of one IF or CASE contain the same body.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "IF" || block.Kind == "CASE"))
            {
                var seen = new Dictionary<string, Tuple<string, int>>(StringComparer.Ordinal);
                foreach (var branch in block.Branches)
                {
                    var end = branch.End - section.Base;
                    var contentStart = branch.Body - section.Base;
                    var normalised = Normalise(section.Raw.Substring(contentStart, end - contentStart));
                    if (normalised.Length == 0 || normalised == ";") continue;
                    var label = branch.Label.Trim();
                    if (!seen.TryGetValue(normalised, out var previous))
                    {
                        seen[normalised] = Tuple.Create(label, branch.Start);
                        continue;
                    }
                    yield return Finding.In(unit, "branch '" + label + "' has the same body as branch '" + previous.Item1 + "' in the same " + block.Kind,
                        branch.Start, branch.Start + label.Length, label, previous.Item1 + " and " + label);
                }
            }
        }

        static string Normalise(string source)
        {
            var chars = source.ToCharArray();
            foreach (var comment in StText.Comments(source))
                for (var index = comment.Start; index < comment.End; index++) chars[index] = ' ';
            var text = StText.Squeezed(new string(chars)).ToLowerInvariant();
            return Punctuation.Replace(text, "$1");
        }
    }
}
