using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // One function-block instance called twice on one control-flow path:
    // the second call runs it again in the same cycle. A block without a
    // clock whose output is read between the calls is reused on purpose, as
    // a worker that answers each call (Snapshot.IsClocked).
    internal sealed class CTS0029 : Rule
    {

        internal CTS0029() : base("CTS0029", "Multiple calls to one function-block instance", Analysis.Severity.Suspicious, "Correctness", "A function-block instance is called more than once on one path.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var instances = new HashSet<string>(context.Snapshot.MembersSeenBy(unit)
                .Where(member => member.Name.Length > 0 && context.Snapshot.IsFunctionBlockType(member.Type))
                .Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            if (instances.Count == 0) yield break;
            var clocked = new HashSet<string>(context.Snapshot.MembersSeenBy(unit)
                .Where(member => instances.Contains(member.Name) && context.Snapshot.IsClocked(member.Type))
                .Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var end = section.At(section.Text.Length);
            var calls = StCalls.Call.Matches(section.Text).Cast<Match>().Select(match => match.Groups["name"]).Where(name => instances.Contains(name.Value));
            foreach (var path in calls.GroupBy(name => name.Value.ToLowerInvariant() + "|" + unit.Tree.PathTo(section.At(name.Index), end)))
                foreach (var (before, name) in path.Zip(path.Skip(1), (before, name) => (before, name)))
                {
                    if (!clocked.Contains(name.Value) && ReadsOutput(section.Text, name.Value, before.Index + before.Length, name.Index)) continue;
                    yield return Finding.In(unit, "function-block instance '" + name.Value + "' is called more than once in the same control-flow path",
                        section.At(name.Index), section.At(name.Index + name.Length), name.Value, name.Value + "(...)");
                }
        }

        // Whether text between from and to reads instance.member.
        static bool ReadsOutput(string text, string instance, int from, int to) =>
            new Regex(@"\b" + Regex.Escape(instance) + @"\s*\.\s*[A-Za-z_]", RegexOptions.IgnoreCase).IsMatch(text.Substring(from, to - from));
    }
}
