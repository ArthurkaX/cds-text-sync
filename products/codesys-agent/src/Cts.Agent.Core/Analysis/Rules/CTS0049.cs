using System;
using System.Collections.Generic;
using System.Globalization;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // An integer variable given a literal-only value (see StConstants) out
    // of its type's range, as its initial value or in the code: "b : BYTE :=
    // 16#100", "i := 200 * 200".
    internal sealed class CTS0049 : Rule
    {
        static readonly Regex Assignment = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\s*:=\s*(?<expression>[^;]+)");

        internal CTS0049() : base("CTS0049", "Constant arithmetic overflow", Analysis.Severity.Danger, "Correctness", "A constant arithmetic result does not fit its integer target.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            foreach (var member in unit.Members())
            {
                var expression = member.Initial.Trim();
                var message = Overflow(member, expression);
                if (message == null) continue;
                var offset = unit.MemberOffset(member);
                yield return Finding.In(unit, message, offset, offset + member.Name.Length, member.Name, member.Name + " : " + member.Type + " := " + expression);
            }
            var targets = new Dictionary<string, VarMember>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
                if (!targets.ContainsKey(member.Name)) targets[member.Name] = member;
            var section = unit.Body;
            foreach (Match match in Assignment.Matches(section.Text))
            {
                var name = match.Groups["name"];
                if (!targets.TryGetValue(name.Value, out var target)) continue;
                var message = Overflow(target, match.Groups["expression"].Value.Trim());
                if (message == null) continue;
                yield return Finding.In(unit, message, section.At(name.Index), section.At(name.Index) + target.Name.Length, target.Name, match.Value.Trim());
            }
        }

        static string Overflow(VarMember target, string expression)
        {
            var type = StDeclarations.ClassifyType(target.Type).Base;
            var range = IecTypes.Range(type);
            if (range == null || expression.Length == 0) return null;
            var value = StConstants.Value(expression);
            string shown;
            if (value is BigInteger integer && (integer < range.Item1 || integer > range.Item2)) shown = integer.ToString(CultureInfo.InvariantCulture);
            else if (value is double real && !double.IsInfinity(real) && !double.IsNaN(real) && (real < (double)range.Item1 || real > (double)range.Item2)) shown = Cts.Agent.Json.Number(real);
            else return null;
            return "constant expression " + Quoted(expression) + " evaluates to " + shown + " outside " + type.ToUpperInvariant() + " range [" + range.Item1 + ".." + range.Item2 + "]";
        }
    }
}
