using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // A FOR loop with literal bounds that indexes a one-dimensional array
    // with its counter while the unit leaves part of the array's range
    // untouched: no other loop (a slice 1..24, 25..48, 49..72; a shift
    // a[i + 1]) and no literal index (a[1] := ...) reaches the rest. A loop
    // that also indexes the array another way (a[i + 1], a[j] of an inner
    // loop) compares neighbours and stops short on purpose.
    internal sealed class CTS0065 : Rule
    {
        static readonly Regex Access = new Regex(@"\b(?<array>[A-Za-z_]\w*)\s*\[\s*(?<index>[^\[\]]*?)\s*\]");
        static readonly Regex Offset = new Regex(@"^(?<counter>[A-Za-z_]\w*)(?:\s*(?<sign>[+-])\s*(?<by>\d+))?$");

        internal CTS0065() : base("CTS0065", "Partial array coverage", Analysis.Severity.Suspicious, "Code quality", "A FOR loop indexes only part of an array.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var arrays = new Dictionary<string, Tuple<string, BigInteger, BigInteger>>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in context.Snapshot.MembersSeenBy(unit))
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind != "array" || shape.Dimensions.Count != 1) continue;
                var lower = IecTypes.Integer(shape.Dimensions[0].Key);
                var upper = IecTypes.Integer(shape.Dimensions[0].Value);
                if (lower.HasValue && upper.HasValue) arrays[member.Name] = Tuple.Create(member.Name, lower.Value, upper.Value);
            }
            if (arrays.Count == 0) yield break;
            var section = unit.Body;
            var reached = new Dictionary<string, List<Tuple<BigInteger, BigInteger>>>(StringComparer.OrdinalIgnoreCase);
            void Reach(string array, BigInteger low, BigInteger high)
            {
                if (!reached.TryGetValue(array, out var spans)) reached[array] = spans = new List<Tuple<BigInteger, BigInteger>>();
                spans.Add(Tuple.Create(low, high));
            }
            foreach (Match access in Access.Matches(section.Text))
                if (arrays.ContainsKey(access.Groups["array"].Value) && IecTypes.Integer(access.Groups["index"].Value) is BigInteger index) Reach(access.Groups["array"].Value, index, index);
            var candidates = new List<Tuple<string, Match, BigInteger, BigInteger>>();
            foreach (var loop in ForLoop.Of(unit))
            {
                if (loop.Literal == null || loop.Counter == null || !loop.Block.End.HasValue) continue;
                var low = BigInteger.Min(loop.StartValue, loop.EndValue);
                var high = BigInteger.Max(loop.StartValue, loop.EndValue);
                var bare = new Dictionary<string, Match>(StringComparer.OrdinalIgnoreCase);
                var other = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                for (var access = Access.Match(section.Text, loop.BodyStart, loop.End - loop.BodyStart); access.Success; access = access.NextMatch())
                {
                    var array = access.Groups["array"].Value;
                    if (!arrays.ContainsKey(array) || IecTypes.Integer(access.Groups["index"].Value).HasValue) continue;
                    var offset = Offset.Match(access.Groups["index"].Value);
                    if (!offset.Success || !offset.Groups["counter"].Value.Equals(loop.Counter, StringComparison.OrdinalIgnoreCase)) { other.Add(array); continue; }
                    if (!offset.Groups["sign"].Success) { if (!bare.ContainsKey(array)) bare[array] = access; Reach(array, low, high); continue; }
                    var by = BigInteger.Parse(offset.Groups["by"].Value) * (offset.Groups["sign"].Value == "-" ? -1 : 1);
                    Reach(array, low + by, high + by);
                    other.Add(array);
                }
                foreach (var item in bare.Where(item => !other.Contains(item.Key)))
                    candidates.Add(Tuple.Create(item.Key, item.Value, low, high));
            }
            foreach (var candidate in candidates)
            {
                var array = arrays[candidate.Item1];
                if (!(array.Item2 <= candidate.Item3 && candidate.Item4 <= array.Item3) || Covers(reached[candidate.Item1], array.Item2, array.Item3)) continue;
                var access = candidate.Item2;
                yield return Finding.In(unit, "FOR range [" + candidate.Item3 + ".." + candidate.Item4 + "] covers only part of array '" + array.Item1 + "' [" + array.Item2 + ".." + array.Item3 + "]",
                    section.At(access.Index), section.At(access.Index + access.Length), access.Value, access.Value);
            }
        }

        // Whether the spans together hold every index from low to high.
        static bool Covers(IEnumerable<Tuple<BigInteger, BigInteger>> spans, BigInteger low, BigInteger high)
        {
            var next = low;
            foreach (var span in spans.OrderBy(span => span.Item1))
            {
                if (span.Item1 > next) return false;
                if (span.Item2 >= next) next = span.Item2 + 1;
                if (next > high) return true;
            }
            return next > high;
        }
    }
}
