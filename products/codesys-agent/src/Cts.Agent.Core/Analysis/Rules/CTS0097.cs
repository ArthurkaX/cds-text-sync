using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A callable whose implementation contains no executable text. A
    // function block or program with methods or actions may leave its own
    // body empty: its code lives in them.
    internal sealed class CTS0097 : Rule
    {

        internal CTS0097() : base("CTS0097", "Empty callable implementation", Analysis.Severity.Suspicious, "Dead code", "A callable POU contains no executable implementation.", "CALLABLE")
        {
            Requires = new[] { Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (unit.Implementation == null || Regex.Replace(unit.Body.Text, @"[;\s]", "").Length > 0 || context.Snapshot.OwnedBy(unit.QualifiedName).Any()) yield break;

            int? offset = unit.Header.Success ? unit.DeclarationStart + unit.Header.Groups["name"].Index : (int?)null;
            yield return Finding.In(unit, unit.Kind.Replace('_', ' ') + " '" + unit.QualifiedName + "' has an empty implementation",
                offset, offset.HasValue ? offset.Value + Snapshot.LastSegment(unit.QualifiedName).Length : (int?)null, anchor: unit.QualifiedName, context: unit.Kind);
        }
    }
}
