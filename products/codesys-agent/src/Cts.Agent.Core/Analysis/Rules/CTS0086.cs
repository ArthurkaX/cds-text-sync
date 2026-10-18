using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "itf.Method()" on an interface variable no code has assigned before:
    // the call goes through a null pointer. Inputs and in-outs come from the
    // caller; a function block's methods and actions count as its code, so
    // an assignment in FB_Init or any of them counts as visible.
    internal sealed class CTS0086 : Rule
    {
        // Not a member after '.'.
        static readonly Regex Access = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\s*\.\s*(?<member>[A-Za-z_]\w*)\b");

        internal CTS0086() : base("CTS0086", "Uninitialized interface use", Analysis.Severity.Danger, "Correctness", "An interface is accessed before a visible assignment or initialization.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var interfaces = new Dictionary<string, VarMember>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members().Where(member => member.Scope != "VAR_INPUT" && member.Scope != "VAR_IN_OUT" && IsInterface(context.Snapshot, member.Type)))
            {
                var initial = member.Initial.Trim();
                if (initial.Length == 0 || initial == "0" || initial.Equals("NULL", StringComparison.OrdinalIgnoreCase)) interfaces[member.Name] = member;
            }
            foreach (var owned in context.Snapshot.OwnedBy(unit.QualifiedName))
            {
                var locals = new HashSet<string>(owned.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
                foreach (Match match in StBlocks.WholeAssignment.Matches(owned.Body.Text))
                    if (!locals.Contains(match.Groups["name"].Value)) interfaces.Remove(match.Groups["name"].Value);
            }
            if (interfaces.Count == 0) yield break;
            var section = unit.Body;
            var assigned = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (Match match in StBlocks.WholeAssignment.Matches(section.Text))
                if (interfaces.ContainsKey(match.Groups["name"].Value) && !assigned.ContainsKey(match.Groups["name"].Value)) assigned[match.Groups["name"].Value] = match.Index;
            foreach (Match match in Access.Matches(section.Text))
            {
                if (!interfaces.TryGetValue(match.Groups["name"].Value, out var member)) continue;
                var known = assigned.TryGetValue(member.Name, out var first);
                if (known && first < match.Index) continue;
                var expression = match.Value.Trim();
                yield return Finding.In(unit, known ? "interface '" + member.Name + "' is used before its first visible initialization"
                    : "interface '" + member.Name + "' is used before it is initialized; no assignment is visible in this POU",
                    section.At(match.Index), section.At(match.Index + match.Length), expression, expression);
                yield break;
            }
        }

        // A project interface, named in full or by its last segment.
        static bool IsInterface(Snapshot snapshot, string type)
        {
            var name = type.Trim();
            return snapshot.ByName(name).Concat(snapshot.ByName(Snapshot.LastSegment(name))).Any(unit => unit.Kind == Analysis.Kinds.Interface);
        }
    }
}
