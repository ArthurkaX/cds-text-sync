using System;
using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // "1..10:" then "5..20:": values 5 to 10 never reach the second arm.
    // Only decimal labels are compared (enum members and constants need
    // types); an exact repeat is CTS0015's.
    internal sealed class CTS0044 : Rule
    {
        static readonly Regex Separator = new Regex(@"\s*,\s*");
        static readonly Regex IntegerRange = new Regex(@"^\s*([+-]?\d+)\s*(?:\.\.\s*([+-]?\d+))?\s*$");

        internal CTS0044() : base("CTS0044", "Overlapping CASE range", Analysis.Severity.Danger, "Correctness", "Numeric CASE ranges must not overlap an earlier branch.", "CALLABLE")
        {
            Requires = new[] { Needs.StText, Needs.BlockStructure };
        }

        internal override IEnumerable<Finding> Check(Unit unit, RuleContext context)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "CASE"))
            {
                var previous = new List<Tuple<string, BigInteger, BigInteger>>();
                foreach (var branch in block.Branches)
                {
                    var current = Ranges(branch.Label).ToList();
                    var overlap = current.Select(range => Tuple.Create(range, previous.FirstOrDefault(earlier =>
                            !(range.Item2 == earlier.Item2 && range.Item3 == earlier.Item3) && range.Item2 <= earlier.Item3 && earlier.Item2 <= range.Item3)))
                        .FirstOrDefault(pair => pair.Item2 != null);
                    if (overlap != null)
                        yield return Finding.In(unit, "CASE range " + Quoted(overlap.Item1.Item1) + " overlaps previous range " + Quoted(overlap.Item2.Item1) + "; part of this branch is unreachable",
                            branch.Start, branch.Start + branch.Label.Length, overlap.Item1.Item1, branch.Label);
                    previous.AddRange(current);
                }
            }
        }

        // Each decimal label or range of a CASE arm: as written, its low and high end.
        static IEnumerable<Tuple<string, BigInteger, BigInteger>> Ranges(string label)
        {
            foreach (var part in Separator.Split(label))
            {
                var match = IntegerRange.Match(part);
                if (!match.Success) continue;
                var first = IecTypes.Literal(match.Groups[1].Value);
                var last = match.Groups[2].Success ? IecTypes.Literal(match.Groups[2].Value) : first;
                yield return Tuple.Create(part.Trim(), BigInteger.Min(first, last), BigInteger.Max(first, last));
            }
        }
    }
}
