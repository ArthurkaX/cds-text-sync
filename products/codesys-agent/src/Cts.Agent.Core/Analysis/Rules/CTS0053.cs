using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A call the execution graph could not tie to a project POU, a declared
    // instance or a known library symbol: a typo, a missing library, or code
    // the view does not hold.
    internal sealed class CTS0053 : Rule
    {
        static readonly Regex QualifiedCall = new Regex(@"\b(?<name>[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*)\s*\(", RegexOptions.IgnoreCase);
        static readonly HashSet<string> NonCalls = new HashSet<string> { "IF", "FOR", "WHILE", "CASE", "REPEAT", "RETURN", "SEL", "MUX", "AND", "OR", "XOR", "NOT" };

        internal CTS0053() : base("CTS0053", "Unresolved call", Analysis.Severity.Suspicious, "Code quality", "A call is not resolved to a project POU or known library symbol.")
        {
            Requires = new[] { Needs.ExecutionGraph, Needs.StText };
        }

        internal override bool PerUnit => false;

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            foreach (var unit in context.Units.Where(unit => Analysis.Kinds.IsCallable(unit.Kind)))
            {
                if (!context.Graph.Unresolved.TryGetValue(ExecutionGraph.Key(unit.QualifiedName), out var unresolved) || unit.Body.IsEmpty) continue;
                var names = new HashSet<string>(unresolved, StringComparer.OrdinalIgnoreCase);
                var libraryInstances = new HashSet<string>(unit.Members().Where(m => m.Name.Length > 0 && Library.IsFunctionBlock(m.Type)).Select(m => m.Name), StringComparer.OrdinalIgnoreCase);
                foreach (Match match in QualifiedCall.Matches(unit.Body.Text))
                {
                    var name = string.Join(".", match.Groups["name"].Value.Split('.').Select(part => part.Trim()));
                    var parts = name.Split('.');
                    if (NonCalls.Contains(parts[parts.Length - 1].ToUpperInvariant())) continue;
                    if (parts[0].Equals("THIS", StringComparison.OrdinalIgnoreCase) || parts[0].Equals("SUPER", StringComparison.OrdinalIgnoreCase)) continue;
                    if (libraryInstances.Contains(name) || !names.Contains(name)) continue;
                    yield return Finding.In(unit, "call '" + name + "' cannot be resolved to a project POU or known library symbol",
                        unit.Body.At(match.Index), unit.Body.At(match.Index + match.Length), name, name + "(...)");
                }
            }
        }
    }
}
