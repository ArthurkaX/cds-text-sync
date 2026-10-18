using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "T#5s + delayMs": TIME arithmetic with a number counts the number as
    // milliseconds without saying so.
    internal sealed class CTS0062 : Rule
    {
        const string TimeLiteral = @"(?:T|TIME)#[+-]?(?:\d+(?:\.\d+)?(?:ms|us|ns|d|h|m|s))+";
        const string NumberLiteral = @"(?:[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|(?:SINT|USINT|BYTE|INT|UINT|WORD|DINT|UDINT|DWORD|LINT|ULINT|LWORD|REAL|LREAL)#[-+]?\d+(?:\.\d*)?)";
        const string Operand = "(?:" + TimeLiteral + "|" + NumberLiteral + @"|[A-Za-z_]\w*)";
        static readonly Regex AnyTimeLiteral = new Regex(TimeLiteral, RegexOptions.IgnoreCase);
        static readonly Regex WholeTimeLiteral = new Regex("^" + TimeLiteral + "$", RegexOptions.IgnoreCase);
        static readonly Regex WholeNumberLiteral = new Regex("^" + NumberLiteral + "$", RegexOptions.IgnoreCase);
        // Not a member after '.', not followed by a member access.
        static readonly Regex MixedOperation = new Regex(@"(?<![A-Za-z0-9_.])(?<left>" + Operand + @")\s*(?<operator>[+*/-])\s*(?<right>" + Operand + @")(?![A-Za-z0-9_.])", RegexOptions.IgnoreCase);
        static readonly HashSet<string> Numeric = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "SINT", "USINT", "BYTE", "INT", "UINT", "WORD", "DINT", "UDINT", "DWORD", "LINT", "ULINT", "LWORD", "REAL", "LREAL",
        };

        internal CTS0062() : base("CTS0062", "Implicit TIME and numeric arithmetic", Analysis.Severity.Suspicious, "Correctness", "TIME arithmetic with numeric values must use an explicit conversion.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            var types = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind == "scalar" && !types.ContainsKey(member.Name)) types[member.Name] = shape.Base;
            }
            if (!types.Values.Any(type => type.Equals("TIME", StringComparison.OrdinalIgnoreCase)) && !AnyTimeLiteral.IsMatch(section.Text)) yield break;
            foreach (Match match in MixedOperation.Matches(section.Text))
            {
                var kinds = new HashSet<string> { OperandKind(match.Groups["left"].Value, types), OperandKind(match.Groups["right"].Value, types) };
                if (!kinds.SetEquals(new[] { "time", "numeric" })) continue;
                yield return Finding.In(unit, "arithmetic mixes TIME and numeric value in '" + match.Value + "'; use an explicit TIME_TO_/TO_TIME conversion",
                    section.At(match.Index), section.At(match.Index + match.Length), match.Value, match.Value);
            }
        }

        static string OperandKind(string operand, Dictionary<string, string> types)
        {
            if (WholeTimeLiteral.IsMatch(operand)) return "time";
            if (WholeNumberLiteral.IsMatch(operand)) return "numeric";
            if (!types.TryGetValue(operand, out var type)) return null;
            return type.Equals("TIME", StringComparison.OrdinalIgnoreCase) ? "time" : Numeric.Contains(type) ? "numeric" : null;
        }
    }
}
