using System.Collections.Generic;
using System.Linq;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // A FOR block of a unit's implementation: its header "FOR ... DO", the
    // counter, and, when the bounds and step are integer literals, those.
    // Offsets are local to the implementation section.
    internal sealed class ForLoop
    {
        static readonly Regex Header = new Regex(@"\bFOR\b(?<header>.*?)\bDO\b", RegexOptions.IgnoreCase | RegexOptions.Singleline);
        static readonly Regex CounterForm = new Regex(@"^\s*(?<counter>[A-Za-z_]\w*)\s*(?::\s*(?<type>[A-Za-z_]\w*)\s*)?:=");
        internal static readonly Regex LiteralForm = new Regex(@"^\s*(?<counter>[^:=]+?)\s*(?::\s*(?<type>[A-Za-z_]\w*)\s*)?:=\s*(?<start>[+-]?\d+)\s+TO\s+(?<end>[+-]?\d+)(?:\s+BY\s+(?<step>[+-]?\d+))?\s*$",
            RegexOptions.IgnoreCase);

        internal Block Block;
        // "FOR ... DO" as written, where it starts, where its text after FOR starts, where the body starts and the loop ends.
        internal string Text;
        internal int Start, HeaderStart, BodyStart, End;
        // The counter and its inline type ("FOR i : INT := ..."), null when the header names none.
        internal string Counter, InlineType;
        // The literal form; Literal.Groups start/end/step are relative to HeaderStart.
        internal Match Literal;

        internal BigInteger StartValue => IecTypes.Literal(Literal.Groups["start"].Value);
        internal BigInteger EndValue => IecTypes.Literal(Literal.Groups["end"].Value);
        internal BigInteger? StepValue => Literal.Groups["step"].Success ? IecTypes.Literal(Literal.Groups["step"].Value) : (BigInteger?)null;

        internal static IEnumerable<ForLoop> Of(Unit unit)
        {
            var section = unit.Body;
            if (section.IsEmpty) yield break;
            var text = section.Text;
            foreach (var block in unit.Tree.Descendants().Where(block => block.Kind == "FOR"))
            {
                var start = block.Start - section.Base;
                var end = block.End.HasValue ? block.End.Value - section.Base : text.Length;
                var header = Header.Match(text, start, end - start);
                if (!header.Success) continue;
                var headerText = header.Groups["header"].Value;
                var counter = CounterForm.Match(headerText);
                var literal = LiteralForm.Match(headerText);
                yield return new ForLoop
                {
                    Block = block, Text = header.Value, Start = header.Index, HeaderStart = header.Groups["header"].Index, BodyStart = header.Index + header.Length, End = end,
                    Counter = counter.Success ? counter.Groups["counter"].Value : null, InlineType = counter.Success && counter.Groups["type"].Success ? counter.Groups["type"].Value : null,
                    Literal = literal.Success ? literal : null,
                };
            }
        }
    }
}
