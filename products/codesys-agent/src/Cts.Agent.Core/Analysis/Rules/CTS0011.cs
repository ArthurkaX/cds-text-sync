using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // A local variable assigned but never read. The VAR of a program or
    // function block lives as long as the instance, so its methods, actions
    // and property accessors read and write it too (unless they declare a
    // name of their own that hides it).
    internal sealed class CTS0011 : Rule
    {

        internal CTS0011() : base("CTS0011", "Assigned local not read", Analysis.Severity.Suspicious, "Dead code", "Local variables that are assigned but never read.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var locals = unit.Members("VAR", "VAR_TEMP", "VAR_STAT").ToList();
            if (locals.Count == 0) yield break;
            var assigned = new HashSet<string>();
            var read = new HashSet<string>();
            Scan(unit, assigned, read, new HashSet<string>());
            if (unit.Kind == Analysis.Kinds.Program || unit.Kind == Analysis.Kinds.FunctionBlock)
                foreach (var owned in context.Snapshot.OwnedBy(unit.QualifiedName))
                    Scan(owned, assigned, read, new HashSet<string>(owned.Members().Select(member => member.Name.ToLowerInvariant())));
            foreach (var member in locals)
            {
                var name = member.Name.ToLowerInvariant();
                if (!assigned.Contains(name) || read.Contains(name)) continue;
                yield return Finding.In(unit, "local variable '" + member.Name + "' is assigned but never read",
                    unit.MemberOffset(member), anchor: member.Name, context: member.Name + " : " + member.Type);
            }
        }

        static void Scan(Unit unit, HashSet<string> assigned, HashSet<string> read, HashSet<string> hidden)
        {
            if (string.IsNullOrEmpty(unit.Implementation)) return;
            var clean = unit.Body.Text;
            foreach (Match match in StBlocks.Assignment.Matches(clean))
            {
                var name = match.Groups["name"].Value.ToLowerInvariant();
                if (!hidden.Contains(name)) assigned.Add(name);
            }
            foreach (Match match in StText.Name.Matches(clean))
            {
                var after = match.Index + match.Length;
                while (after < clean.Length && char.IsWhiteSpace(clean[after])) after++;
                if (string.CompareOrdinal(clean, after, ":=", 0, 2) == 0) continue;
                // A qualified field is not a read of a local variable with the same name.
                var before = match.Index - 1;
                while (before >= 0 && char.IsWhiteSpace(clean[before])) before--;
                if (before >= 0 && (clean[before] == '.' || clean[before] == '^')) continue;
                var name = match.Groups["name"].Value.ToLowerInvariant();
                if (!hidden.Contains(name)) read.Add(name);
            }
        }
    }
}
