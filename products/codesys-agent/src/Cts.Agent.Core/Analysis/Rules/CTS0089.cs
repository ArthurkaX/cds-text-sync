using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // FB_Init that uses a global function block or writes a global: FB_Init
    // runs while the application initialises, in an order the code does
    // not set, so that state may not be ready yet.
    internal sealed class CTS0089 : Rule
    {
        // Not a member after '.'.
        static readonly Regex Identifier = new Regex(@"(?<![\w.])(?<name>[A-Za-z_]\w*)\b");
        static readonly Regex MethodHeader = new Regex(@"\bMETHOD(?:\s+(?:PUBLIC|PROTECTED|PRIVATE|INTERNAL))?\s+(?<name>[A-Za-z_]\w*)\b", RegexOptions.IgnoreCase);
        static readonly Regex Write = new Regex(@"\G\s*(?:\.\s*[A-Za-z_]\w*\s*)?:=");

        internal CTS0089() : base("CTS0089", "Global state access during FB_Init", Analysis.Severity.Suspicious, "Correctness", "Global FB state or writes during FB_Init can depend on initialization order.", Analysis.Kinds.Method)
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (!IsFbInit(unit)) yield break;
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var functionBlockTypes = ProjectLookup.FunctionBlockTypes(context);
            var globals = ProjectLookup.GlobalMembers(context);
            if (globals.Count == 0) yield break;
            var locals = new HashSet<string>(unit.Members().Select(member => member.Name), StringComparer.OrdinalIgnoreCase);
            var reported = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (Match match in Identifier.Matches(section.Text))
            {
                var name = match.Groups["name"].Value;
                if (locals.Contains(name) || reported.Contains(name) || !globals.TryGetValue(name.ToLowerInvariant(), out var global)) continue;
                string reason;
                if (ProjectLookup.IsFunctionBlockType(global.Item2.Type, functionBlockTypes)) reason = "global function-block state is used during initialization";
                else if (Write.IsMatch(section.Text, match.Index + match.Length)) reason = "global state is written during initialization";
                else continue;
                reported.Add(name);
                yield return Finding.In(unit, "global '" + name + "' is accessed from FB_Init; " + reason,
                    section.At(match.Index), section.At(match.Index + match.Length), name, match.Value);
            }
        }

        static bool IsFbInit(Unit unit)
        {
            var match = MethodHeader.Match(unit.Declaration ?? "");
            var name = match.Success ? match.Groups["name"].Value : Snapshot.LastSegment(unit.QualifiedName);
            return name.Equals("FB_Init", StringComparison.OrdinalIgnoreCase);
        }
    }
}
