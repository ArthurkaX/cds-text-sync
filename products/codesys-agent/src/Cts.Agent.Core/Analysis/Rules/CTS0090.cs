using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // FB_Init calls a method (its own or inherited, bare or through THIS)
    // that a function block derived from the owner overrides: the call runs
    // the override before the derived part is initialized. Once per method.
    internal sealed class CTS0090 : Rule
    {
        static readonly Regex Call = new Regex(@"(?<this>\bTHIS\s*\^?\s*\.\s*)?\b(?<name>[A-Za-z_]\w*)\s*\(", RegexOptions.IgnoreCase);
        static readonly Regex Member = new Regex(@"[.^]\s*$");

        internal CTS0090() : base("CTS0090", "Overridable method called from FB_Init", Analysis.Severity.Danger, "Correctness", "Dynamic dispatch during FB_Init can reach partially initialized derived state.", Analysis.Kinds.Method)
        {
            Requires = new[] { Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (!Snapshot.LastSegment(unit.QualifiedName).Equals("FB_Init", StringComparison.OrdinalIgnoreCase)) yield break;
            var blocks = context.Units.Where(candidate => candidate.Kind == Analysis.Kinds.FunctionBlock).ToList();
            var owner = context.Snapshot.InstanceOwner(unit);
            if (owner == null || owner.Kind != Analysis.Kinds.FunctionBlock) yield break;
            var inherited = new HashSet<string>(Ancestry(owner, blocks).SelectMany(block => Methods(block, context)), StringComparer.OrdinalIgnoreCase);
            var overridden = new HashSet<string>(blocks.Where(block => block != owner && Ancestry(block, blocks).Contains(owner))
                .SelectMany(block => Methods(block, context)).Where(inherited.Contains), StringComparer.OrdinalIgnoreCase);
            if (overridden.Count == 0) yield break;
            var section = unit.Body;
            var reported = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (Match match in Call.Matches(section.Text))
            {
                var name = match.Groups["name"];
                if (!overridden.Contains(name.Value) || !match.Groups["this"].Success && Member.IsMatch(section.Text.Substring(0, match.Index)) || !reported.Add(name.Value)) continue;
                yield return Finding.In(unit, "overridable method '" + name.Value + "' is called from FB_Init; derived state may not be initialized",
                    section.At(name.Index), section.At(name.Index + name.Length), name.Value, match.Value);
            }
        }

        // The block and the blocks it extends, nearest first.
        static IEnumerable<Unit> Ancestry(Unit block, List<Unit> blocks)
        {
            var seen = new HashSet<Unit>();
            for (var current = block; current != null && seen.Add(current); )
            {
                yield return current;
                var extends = Snapshot.LastSegment(StDeclarations.PouHeader(current.Declaration).Key);
                current = extends.Length == 0 ? null : blocks.FirstOrDefault(candidate => Snapshot.LastSegment(candidate.QualifiedName).Equals(extends, StringComparison.OrdinalIgnoreCase));
            }
        }

        static IEnumerable<string> Methods(Unit block, RuleContext context) =>
            context.Snapshot.OwnedBy(block.QualifiedName).Where(member => member.Kind == Analysis.Kinds.Method && member.OwnerName.Equals(block.QualifiedName, StringComparison.OrdinalIgnoreCase))
                .Select(member => Snapshot.LastSegment(member.QualifiedName));
    }
}
