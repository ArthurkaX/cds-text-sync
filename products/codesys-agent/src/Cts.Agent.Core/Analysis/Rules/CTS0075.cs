using System;
using System.Linq;
using System.Collections.Generic;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A function whose result variable (its own name) some path leaves
    // unassigned: the caller reads a stale or default value. A method with
    // a result type counts when it assigns the result on some path only; one
    // that never does leaves a result nobody reads. Only an IF or CASE with
    // an ELSE whose every arm assigns covers all paths.
    internal sealed class CTS0075 : Rule
    {

        internal CTS0075() : base("CTS0075", "Function result not assigned on all paths", Analysis.Severity.Suspicious, "Correctness", "FUNCTION results must be assigned on every reachable return path.",
            Analysis.Kinds.Function, Analysis.Kinds.Method)
        {
            Requires = new[] { Needs.Declarations, Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var header = unit.Header;
            var section = unit.Body;
            var kind = header.Groups["kind"].Value.ToUpperInvariant();
            if (section.IsEmpty || kind != "FUNCTION" && !(kind == "METHOD" && header.Groups["type"].Value.Trim().Length > 0)) yield break;
            var name = header.Groups["name"].Value;
            var writes = StBlocks.WholeAssignment.Matches(section.Text).Cast<Match>().Where(match => match.Groups["name"].Value.Equals(name, StringComparison.OrdinalIgnoreCase))
                .Select(match => section.At(match.Index)).ToList();
            var root = unit.Tree;
            if (writes.Count == 0 ? kind == "METHOD" : root.Covers(writes, root.Start, section.At(section.Text.Length))) yield break;
            var offset = writes.Count > 0 ? writes[0] : unit.DeclarationSection.At(header.Groups["name"].Index);
            var message = writes.Count > 0 ? "is not assigned on all control-flow paths" : "is never assigned; every caller gets the type's default value";
            yield return Finding.In(unit, kind + " result '" + name + "' " + message, offset, offset + name.Length, name, kind + " " + name);
        }
    }
}
