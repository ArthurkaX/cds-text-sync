using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "name := 'PUMP-01'" into a STRING(4), in the code or as the initial
    // value. A literal's length counts each '$' escape ("$'", "$N", "$0A")
    // as the one character it stands for.
    internal sealed class CTS0078 : Rule
    {
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<target>[A-Za-z_]\w*)\s*:=\s*(?<literal>" + IecTypes.StringLiteral + ")", RegexOptions.Singleline);

        internal CTS0078() : base("CTS0078", "String literal exceeds declared capacity", Analysis.Severity.Danger, "Correctness", "String literals must fit the explicit capacity of their STRING destination.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var declaration = unit.DeclarationSection;
            var declared = StText.Blank(declaration.Raw);
            foreach (var member in unit.Members())
            {
                var capacity = IecTypes.StringCapacity(member.Type);
                var initial = member.Initial.Trim();
                if (capacity == null || !(IecTypes.StringLength(initial) > capacity)) continue;
                var match = Regex.Match(declared, @"\b" + Regex.Escape(member.Name) + @"\b\s*:\s*[^;]*?:=\s*" + Regex.Escape(initial), RegexOptions.IgnoreCase);
                if (!match.Success) continue;
                var start = match.Index + match.Length - initial.Length;
                yield return Finding.In(unit, Message(initial, member.Name, capacity.Value), declaration.At(start), declaration.At(match.Index + match.Length), initial, initial);
            }
            var capacities = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
                if (IecTypes.StringCapacity(member.Type) is int capacity && !capacities.ContainsKey(member.Name)) capacities[member.Name] = capacity;
            if (capacities.Count == 0) yield break;
            var body = unit.Body;
            foreach (Match match in Assignment.Matches(StText.Blank(body.Raw)))
            {
                var literal = match.Groups["literal"];
                if (!capacities.TryGetValue(match.Groups["target"].Value, out var capacity) || IecTypes.StringLength(literal.Value) <= capacity) continue;
                yield return Finding.In(unit, Message(literal.Value, match.Groups["target"].Value, capacity), body.At(literal.Index), body.At(literal.Index + literal.Length), literal.Value, literal.Value);
            }
        }


        static string Message(string literal, string target, int capacity) =>
            "string literal has " + IecTypes.StringLength(literal) + " characters but " + target + " is limited to STRING(" + capacity + ")";
    }
}
