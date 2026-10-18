using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // An output of a function, method, action or accessor read before the
    // call assigns it: it holds its default (or, in a method, whatever the
    // last call left in an output kept between calls).
    internal sealed class CTS0022 : Rule
    {
        static readonly Regex Qualified = new Regex(@"\G\s*[.\[]");
        // Read leftwards, ending where the name starts.
        static readonly Regex Selected = new Regex(@"[.^]\s*\G", RegexOptions.RightToLeft);
        static readonly HashSet<string> CallKinds = new HashSet<string> { Analysis.Kinds.Function, Analysis.Kinds.Method, Analysis.Kinds.Action, Analysis.Kinds.PropertyGet, Analysis.Kinds.PropertySet };

        internal CTS0022() : base("CTS0022", "Output read before assignment", Analysis.Severity.Suspicious, "Correctness", "VAR_OUTPUT values read before the callable assigns them.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.StText };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            if (!CallKinds.Contains(unit.Kind)) yield break;
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var pending = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members("VAR_OUTPUT").Where(member => member.Name.Length > 0))
                if (!pending.ContainsKey(member.Name)) pending[member.Name] = member.Name;
            var text = section.Text;
            foreach (Match match in StText.Name.Matches(text))
            {
                if (pending.Count == 0) yield break;
                if (!pending.TryGetValue(match.Value, out var name)) continue;
                var end = match.Index + match.Length;
                if (Selected.IsMatch(text, match.Index) || Qualified.IsMatch(text, end)) continue;
                // In "label => output" the left name labels an argument; it is no read.
                if (StBlocks.LabelsArgument(text, end)) continue;
                pending.Remove(name);
                if (StBlocks.WrittenAt(text, match.Index, end)) continue;
                yield return Finding.In(unit, "output '" + name + "' is read before its first assignment", section.At(match.Index), section.At(match.Index) + name.Length, name, name);
            }
        }
    }
}
