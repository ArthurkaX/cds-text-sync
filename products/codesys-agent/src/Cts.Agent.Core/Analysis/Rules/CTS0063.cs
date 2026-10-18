using System;
using System.Collections.Generic;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A MEMCPY/MemMove length exceeds the destination or takes SIZEOF of a pointer.
    internal sealed class CTS0063 : Rule
    {
        static readonly Regex Call = new Regex(@"\b(?<name>MEMCPY|MEMMOVE)\s*\(", RegexOptions.IgnoreCase);
        static readonly Regex Address = new Regex(@"^\s*ADR\s*\(\s*(?<name>[A-Za-z_]\w*)\s*\)\s*$", RegexOptions.IgnoreCase);
        static readonly Regex SizeOf = new Regex(@"^\s*SIZEOF\s*\(\s*(?<name>[A-Za-z_]\w*)\s*\)\s*$", RegexOptions.IgnoreCase);
        static readonly Regex Integer = new Regex(@"^\s*(?<value>\d+)\s*$");

        internal CTS0063() : base("CTS0063", "Inconsistent MEMCPY/MemMove size", Analysis.Severity.Danger, "Correctness", "A memory-copy size may exceed the destination or use pointer size.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var members = new Dictionary<string, Tuple<BigInteger?, bool>>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                members[member.Name] = Tuple.Create(IecTypes.Bytes(member.Type), shape.Kind == "scalar" && shape.Base == "POINTER");
            }
            if (members.Count == 0) yield break;
            var section = unit.Body;
            foreach (Match match in Call.Matches(section.Text))
            {
                var close = StCalls.Close(section.Text, match.Index + match.Length - 1);
                if (close < 0) continue;
                var arguments = StCalls.Arguments(section.Text.Substring(match.Index + match.Length, close - match.Index - match.Length));
                if (arguments.Count != 3) continue;
                var destination = Address.Match(arguments[0]);
                var source = Address.Match(arguments[1]);
                var size = SizeOf.Match(arguments[2]);
                var destinationName = destination.Success ? destination.Groups["name"].Value : null;
                var sourceName = source.Success ? source.Groups["name"].Value : null;
                string reason = null;
                var reasonStart = match.Index;
                var reasonEnd = close + 1;
                if (size.Success && members.TryGetValue(size.Groups["name"].Value, out var sizeMember))
                {
                    if (sizeMember.Item2)
                    {
                        reason = "SIZEOF(" + size.Groups["name"].Value + ") is the pointer size rather than the pointed object size";
                        reasonStart = ArgumentOffset(section.Text, match.Index + match.Length, close, arguments[2]);
                        reasonEnd = reasonStart + arguments[2].Length;
                    }
                    else if (destination.Success && source.Success && members.TryGetValue(destinationName, out var destinationMember)
                        && members.TryGetValue(sourceName, out var sourceMember) && destinationMember.Item1.HasValue && sourceMember.Item1.HasValue
                        && size.Groups["name"].Value.Equals(sourceName, StringComparison.OrdinalIgnoreCase) && destinationMember.Item1 < sourceMember.Item1)
                    {
                        reason = "destination '" + destinationName + "' is " + destinationMember.Item1 + " bytes but SIZEOF(" + sourceName + ") copies " + sourceMember.Item1 + " bytes";
                    }
                }
                else
                {
                    var literal = Integer.Match(arguments[2]);
                    var requested = literal.Success ? IecTypes.Integer(literal.Groups["value"].Value) : null;
                    if (requested.HasValue && destination.Success && members.TryGetValue(destinationName, out var destinationMember) && destinationMember.Item1.HasValue
                        && requested.Value > destinationMember.Item1.Value)
                        reason = "destination '" + destinationName + "' is " + destinationMember.Item1 + " bytes but the call requests " + requested.Value + " bytes";
                }
                if (reason == null) continue;
                var expression = section.Text.Substring(match.Index, close + 1 - match.Index);
                yield return Finding.In(unit, match.Groups["name"].Value + " has an inconsistent size: " + reason,
                    section.At(reasonStart), section.At(reasonEnd), expression, expression);
            }
        }

        static int ArgumentOffset(string text, int start, int end, string argument)
        {
            var relative = text.Substring(start, end - start).IndexOf(argument, StringComparison.Ordinal);
            return start + (relative >= 0 ? relative : 0);
        }
    }
}
