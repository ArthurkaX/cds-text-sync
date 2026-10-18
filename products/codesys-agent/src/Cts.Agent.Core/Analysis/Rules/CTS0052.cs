using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A stateful function-block output is read before its current-cycle call:
    // the value is the previous cycle's.
    internal sealed class CTS0052 : Rule
    {
        static readonly Regex Access = new Regex(@"\b(?<instance>[A-Za-z_]\w*)\s*\.\s*(?<field>[A-Za-z_]\w*)\b", RegexOptions.IgnoreCase);
        static readonly Regex Call = new Regex(@"\b(?<instance>[A-Za-z_]\w*)\s*\(", RegexOptions.IgnoreCase);
        static readonly Regex Assignment = new Regex(@"\A\s*:=" );
        static readonly Regex Output = new Regex(@"\A\s*=>");
        static readonly Dictionary<string, HashSet<string>> KnownOutputs = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase)
        {
            ["ton"] = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "q", "et" },
            ["tof"] = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "q", "et" },
            ["tp"] = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "q", "et" },
            ["r_trig"] = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "q", "clk" },
            ["f_trig"] = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "q", "clk" },
        };

        internal CTS0052() : base("CTS0052", "Function-block output read before call", Analysis.Severity.Suspicious, "Correctness", "A stateful function-block field is read before its current-cycle call.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var outputs = new Dictionary<string, Tuple<string, HashSet<string>>>(StringComparer.OrdinalIgnoreCase);
            var customOutputs = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
            foreach (var candidate in context.Units.Where(candidate => candidate.Kind == Analysis.Kinds.FunctionBlock))
            {
                var fields = new HashSet<string>(candidate.Members("VAR_OUTPUT").Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
                customOutputs[candidate.QualifiedName] = fields;
                customOutputs[Snapshot.LastSegment(candidate.QualifiedName)] = fields;
            }
            var declarations = context.Snapshot.MembersSeenBy(unit);
            foreach (var member in declarations)
            {
                var type = member.Type.Trim();
                var baseName = Snapshot.LastSegment(type);
                if (KnownOutputs.TryGetValue(baseName, out var known)) outputs[member.Name] = Tuple.Create(member.Name, known);
                else if (customOutputs.TryGetValue(type, out var fields) || customOutputs.TryGetValue(baseName, out fields))
                {
                    if (fields.Count > 0) outputs[member.Name] = Tuple.Create(member.Name, fields);
                }
            }
            // A method or action reads its owner's instance after the owner's
            // body or another member called it: an order this rule cannot see.
            var owner = context.Snapshot.InstanceOwner(unit);
            if (owner != null)
            {
                var own = new HashSet<string>(unit.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
                var called = new HashSet<string>(new[] { owner }.Concat(context.Snapshot.OwnedBy(owner.QualifiedName)).Where(other => other != unit)
                    .SelectMany(other => Call.Matches(other.Body.Text).Cast<Match>().Select(call => call.Groups["instance"].Value)), StringComparer.OrdinalIgnoreCase);
                foreach (var name in outputs.Keys.Where(name => !own.Contains(name) && called.Contains(name)).ToList()) outputs.Remove(name);
            }
            if (outputs.Count == 0) yield break;
            var text = section.Text;
            var firstCalls = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            foreach (Match call in Call.Matches(text))
            {
                var name = call.Groups["instance"].Value;
                if (outputs.ContainsKey(name) && !firstCalls.ContainsKey(name)) firstCalls[name] = call.Index;
            }
            foreach (Match access in Access.Matches(text))
            {
                var instance = access.Groups["instance"].Value;
                if (!outputs.TryGetValue(instance, out var info)) continue;
                var field = access.Groups["field"].Value;
                if (!info.Item2.Contains(field)) continue;
                var remainder = text.Substring(access.Index + access.Length);
                if (Assignment.IsMatch(remainder) || Output.IsMatch(remainder)) continue;
                if (firstCalls.TryGetValue(instance, out var callOffset) && callOffset < access.Index) continue;
                var message = firstCalls.ContainsKey(instance)
                    ? "function-block instance '" + info.Item1 + "' field '." + field + "' is read before the instance is called in this cycle"
                    : "function-block instance '" + info.Item1 + "' is never called before reading '." + field + "' in this cycle";
                yield return Finding.In(unit, message, section.At(access.Index), section.At(access.Index + access.Length), info.Item1 + "." + field, access.Value);
            }
        }
    }
}
