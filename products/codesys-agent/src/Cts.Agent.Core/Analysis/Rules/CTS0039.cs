using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Analysis.Rules
{
    // "FOR i := 0 TO 10 DO a[i] ..." with a declared ARRAY[1..10]: the
    // literal range of the counter reaches past the array's literal bounds.
    internal sealed class CTS0039 : Rule
    {
        static readonly Regex Access = new Regex(@"\b(?<array>[A-Za-z_]\w*)\s*\[\s*(?<indices>[^\]\n]+?)\s*\]");

        internal CTS0039() : base("CTS0039", "FOR range exceeds array bounds", Analysis.Severity.Danger, "Correctness", "A literal FOR counter range can index an array outside its bounds.", "CALLABLE")
        {
            Requires = new[] { Needs.Declarations, Needs.BlockStructure };
        }

        sealed class Range
        {
            internal int Start, BodyStart, End;
            internal string Counter;
            internal BigInteger Low, High;
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var arrays = Arrays(unit);
            var section = unit.Body;
            if (arrays.Count == 0 || section.IsEmpty) yield break;
            var loops = new List<Range>();
            foreach (var loop in ForLoop.Of(unit).Where(loop => loop.Block.End.HasValue && loop.Literal != null && loop.Counter != null))
            {
                BigInteger start = loop.StartValue, end = loop.EndValue, step = loop.StepValue ?? 1;
                if (step == 0 || start < end && step < 0 || start > end && step > 0) continue;
                loops.Add(new Range { Start = loop.Block.Start, BodyStart = loop.BodyStart, End = loop.End, Counter = loop.Counter, Low = step > 0 ? start : end, High = step > 0 ? end : start });
            }
            foreach (Match access in Access.Matches(section.Text))
            {
                if (!arrays.TryGetValue(access.Groups["array"].Value, out var array)) continue;
                var indices = access.Groups["indices"].Value.Split(',').Select(part => part.Trim()).ToList();
                if (indices.Count != array.Item2.Count) continue;
                var enclosing = loops.Where(loop => loop.BodyStart <= access.Index && access.Index < loop.End).ToList();
                for (var dimension = 0; dimension < indices.Count; dimension++)
                {
                    var index = indices[dimension];
                    if (!StText.IsIdentifier(index)) continue;
                    // The innermost loop with this counter.
                    var loop = enclosing.Where(candidate => candidate.Counter.Equals(index, StringComparison.OrdinalIgnoreCase)).OrderByDescending(candidate => candidate.Start).FirstOrDefault();
                    var bounds = array.Item2[dimension];
                    if (loop == null || loop.Low >= bounds.Item1 && loop.High <= bounds.Item2) continue;
                    var at = access.Groups["indices"].Index + access.Groups["indices"].Value.IndexOf(index, StringComparison.OrdinalIgnoreCase);
                    yield return Finding.In(unit, "FOR counter range [" + loop.Low + ".." + loop.High + "] can access dimension " + (dimension + 1) + " of array '" + array.Item1 + "' outside declared bounds [" + bounds.Item1 + ".." + bounds.Item2 + "]",
                        section.At(at), section.At(at + index.Length), access.Value, access.Value);
                }
            }
        }

        // The arrays whose every dimension has decimal literal bounds.
        static Dictionary<string, Tuple<string, List<Tuple<BigInteger, BigInteger>>>> Arrays(Unit unit)
        {
            var arrays = new Dictionary<string, Tuple<string, List<Tuple<BigInteger, BigInteger>>>>(StringComparer.OrdinalIgnoreCase);
            foreach (var member in unit.Members())
            {
                var shape = StDeclarations.ClassifyType(member.Type);
                if (shape.Kind != "array") continue;
                var dimensions = new List<Tuple<BigInteger, BigInteger>>();
                foreach (var dimension in shape.Dimensions)
                {
                    if (!BigInteger.TryParse(dimension.Key, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var lower)
                        || !BigInteger.TryParse(dimension.Value, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var upper)) break;
                    dimensions.Add(Tuple.Create(lower, upper));
                }
                if (dimensions.Count == shape.Dimensions.Count) arrays[member.Name] = Tuple.Create(member.Name, dimensions);
            }
            return arrays;
        }
    }
}
