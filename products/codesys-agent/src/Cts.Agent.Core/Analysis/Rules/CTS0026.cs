using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;

namespace Cts.Analysis.Rules
{
    // Two "name AT %IX0.1 : BOOL;" declarations whose bits overlap in one
    // area (%I, %Q, %M), anywhere in the project. The later declaration is
    // reported, naming the first one it overlaps.
    internal sealed class CTS0026 : Rule
    {
        static readonly Regex AtDeclaration = new Regex(@"^\s*(?<name>[A-Za-z_]\w*)\s+AT\s+%(?<area>[IQM])(?<width>[XBWDL])(?<byte>\d+)(?:\.(?<bit>\d+))?\s*:\s*(?<type>[A-Za-z_]\w*)\s*;",
            RegexOptions.IgnoreCase | RegexOptions.Multiline);
        static readonly Dictionary<string, int> TypeBits = new Dictionary<string, int>
        {
            ["BOOL"] = 1, ["BYTE"] = 8, ["SINT"] = 8, ["USINT"] = 8, ["WORD"] = 16, ["INT"] = 16, ["UINT"] = 16,
            ["DWORD"] = 32, ["DINT"] = 32, ["UDINT"] = 32, ["REAL"] = 32, ["LWORD"] = 64, ["LINT"] = 64, ["ULINT"] = 64, ["LREAL"] = 64,
        };
        // Byte-indexed addresses: %IX1.0 is bit 8 of the area, not bit 1.
        static readonly Dictionary<char, int> AddressBits = new Dictionary<char, int> { ['X'] = 8, ['B'] = 8, ['W'] = 16, ['D'] = 32, ['L'] = 64 };

        internal CTS0026() : base("CTS0026", "Overlapping AT memory areas", Analysis.Severity.Danger, "Correctness", "Explicit AT declarations must not claim overlapping memory.")
        {
            Requires = new[] { Needs.Declarations };
        }

        internal override bool PerUnit => false;

        sealed class Placed
        {
            internal Unit Unit;
            internal Group Name;
            internal string Address;
            internal long Start, End;
        }

        internal override IEnumerable<Finding> Check(RuleContext context)
        {
            foreach (var area in Declarations(context.Units).GroupBy(placed => placed.Address[1]))
            {
                var earlier = new List<Placed>();
                foreach (var item in area)
                {
                    var other = earlier.FirstOrDefault(previous => item.Start < previous.End && previous.Start < item.End);
                    if (other != null)
                    {
                        var section = item.Unit.DeclarationSection;
                        yield return Finding.In(item.Unit, "AT variable '" + item.Name.Value + "' overlaps '" + other.Name.Value + "' at " + item.Address,
                            section.At(item.Name.Index), section.At(item.Name.Index + item.Name.Length), item.Name.Value, other.Name.Value + " / " + item.Address);
                    }
                    earlier.Add(item);
                }
            }
        }

        static IEnumerable<Placed> Declarations(IEnumerable<Unit> units)
        {
            foreach (var unit in units)
            {
                var section = unit.DeclarationSection;
                if (section.IsEmpty) continue;
                foreach (Match match in AtDeclaration.Matches(section.Text))
                {
                    var width = char.ToUpperInvariant(match.Groups["width"].Value[0]);
                    var bit = match.Groups["bit"];
                    // A bit address is %IXn.b with b in 0..7; byte and wider ones have no bit.
                    if (bit.Success != (width == 'X') || bit.Success && int.Parse(bit.Value, CultureInfo.InvariantCulture) > 7) continue;
                    if (!TypeBits.TryGetValue(match.Groups["type"].Value.ToUpperInvariant(), out var size)) continue;
                    var start = long.Parse(match.Groups["byte"].Value, CultureInfo.InvariantCulture) * AddressBits[width] + (bit.Success ? int.Parse(bit.Value, CultureInfo.InvariantCulture) : 0);
                    yield return new Placed
                    {
                        Unit = unit, Name = match.Groups["name"], Start = start, End = start + size,
                        Address = "%" + match.Groups["area"].Value.ToUpperInvariant() + width + match.Groups["byte"].Value + (bit.Success ? "." + bit.Value : ""),
                    };
                }
            }
        }
    }
}
