using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A clocked function-block instance called only inside an IF or CASE
    // arm: on cycles that skip the call its timer, counter or controller
    // stands still (Snapshot.IsClocked). An instance the unit resets by
    // hand (IN := FALSE, RESET or LOAD := TRUE) has its lifetime managed, as
    // a state machine's timeout does; the others are reported once, at the
    // first conditional call.
    internal sealed class CTS0031 : Rule
    {
        static readonly Regex Reset = new Regex(@"^\s*(?:IN\s*:=\s*FALSE|(?:RESET|LOAD)\s*:=\s*TRUE)\s*$", RegexOptions.IgnoreCase);

        internal CTS0031() : base("CTS0031", "Conditional function-block call", Analysis.Severity.Suspicious, "Correctness", "Stateful function-block instances should be called every cycle.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var instances = new HashSet<string>(context.Snapshot.MembersSeenBy(unit)
                .Where(member => member.Name.Length > 0 && context.Snapshot.IsClocked(member.Type))
                .Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (instances.Count == 0) yield break;
            instances.ExceptWith(instances.Where(name => ResetByHand(section.Text, name)).ToList());
            var end = section.At(section.Text.Length);
            foreach (Match match in StCalls.Call.Matches(section.Text))
            {
                var name = match.Groups["name"];
                if (!instances.Contains(name.Value)) continue;
                var offset = section.At(name.Index);
                var conditional = Conditional(unit.Tree, offset, end);
                if (conditional == null) continue;
                instances.Remove(name.Value);
                yield return Finding.In(unit, "function-block instance '" + name.Value + "' holds a timer, counter or controller and is called conditionally inside " + conditional + "; it stands still on the cycles that skip it",
                    offset, section.At(name.Index + name.Length), name.Value, name.Value + "(...) in " + conditional);
            }
        }

        // Whether text resets instance: "instance(IN := FALSE, ...)" or
        // "instance.IN := FALSE;" (RESET or LOAD := TRUE for a counter or PID).
        static bool ResetByHand(string text, string instance)
        {
            var name = Regex.Escape(instance);
            if (new Regex(@"(?<![\w.])" + name + @"\s*\.\s*(?:IN\s*:=\s*FALSE|(?:RESET|LOAD)\s*:=\s*TRUE)\b", RegexOptions.IgnoreCase).IsMatch(text)) return true;
            foreach (Match call in new Regex(@"(?<![\w.])" + name + @"\s*\(", RegexOptions.IgnoreCase).Matches(text))
            {
                var opening = call.Index + call.Length - 1;
                var close = StCalls.Close(text, opening);
                if (close > opening && StCalls.Arguments(text.Substring(opening + 1, close - opening - 1)).Any(Reset.IsMatch)) return true;
            }
            return false;
        }

        // The IF or CASE whose arm holds offset, outermost first.
        static string Conditional(Block node, int offset, int end)
        {
            foreach (var child in node.Children.Where(child => child.Start <= offset && offset < (child.End ?? end)))
            {
                if ((child.Kind == "IF" || child.Kind == "CASE") && child.Branches.Any(branch => branch.Start <= offset && offset < branch.End)) return child.Kind;
                var nested = Conditional(child, offset, end);
                if (nested != null) return nested;
            }
            return null;
        }
    }
}
