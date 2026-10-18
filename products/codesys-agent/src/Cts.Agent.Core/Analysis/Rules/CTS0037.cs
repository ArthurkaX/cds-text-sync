using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // An IF or CASE arm holding nothing but ";", unless a comment right
    // before it says the arm is meant to do nothing.
    internal sealed class CTS0037 : Rule
    {

        internal CTS0037() : base("CTS0037", "No-op control-flow branch", Analysis.Severity.Suspicious, "Code quality", "An IF or CASE branch contains only a standalone no-op statement.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "IF" || block.Kind == "CASE"))
                foreach (var branch in block.Branches)
                {
                    var end = branch.End - section.Base;
                    var contentStart = branch.Body - section.Base;
                    if (contentStart > end || text.Substring(contentStart, end - contentStart).Trim() != ";") continue;
                    var semicolon = text.IndexOf(';', contentStart, end - contentStart);
                    if (StText.HasIntentionalNoopComment(section.Raw, semicolon)) continue;
                    yield return Finding.In(unit, "branch contains only a no-op statement", section.At(semicolon), section.At(semicolon) + 1, ";", branch.Label.Trim());
                }
        }
    }
}
