using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Standalone calls to project functions discard their return values.
    internal sealed class CTS0034 : Rule
    {
        static readonly Regex Call = new Regex(@"^\s*(?<name>[A-Za-z_]\w*)\s*\(.*\)\s*\z", RegexOptions.Singleline);

        internal CTS0034() : base("CTS0034", "Ignored function return value", Analysis.Severity.Style, "Correctness", "Standalone calls to project functions whose return values are ignored.", "CALLABLE")
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var functions = new HashSet<string>(context.Units
                .Where(candidate => candidate.Kind == Analysis.Kinds.Function)
                .SelectMany(candidate => new[] { candidate.QualifiedName, Snapshot.LastSegment(candidate.QualifiedName) }),
                System.StringComparer.OrdinalIgnoreCase);
            if (functions.Count == 0 || string.IsNullOrEmpty(unit.Implementation)) yield break;

            foreach (var statement in unit.Body.Statements())
            {
                var match = Call.Match(statement.Value);
                if (!match.Success || !functions.Contains(match.Groups["name"].Value)) continue;
                var name = match.Groups["name"].Value;
                var start = statement.Key + statement.Value.IndexOf(name, System.StringComparison.Ordinal);
                yield return Finding.In(unit,
                    "return value of function '" + name + "' is ignored; verify that the call is intentional",
                    start, start + name.Length, name, statement.Value);
            }
        }
    }
}
