using System;
using System.Collections.Generic;
using System.Numerics;
using System.Text.RegularExpressions;

namespace Cts.Analysis
{
    // Elementary types: integer and bit-string width and range, sizes in
    // bytes, string capacities and literal lengths. Literal values are
    // BigInteger, so no literal of any length overflows.
    internal static class IecTypes
    {
        static readonly Dictionary<string, Tuple<int, bool>> Integers = new Dictionary<string, Tuple<int, bool>>(StringComparer.OrdinalIgnoreCase)
        {
            ["SINT"] = Tuple.Create(8, true), ["USINT"] = Tuple.Create(8, false), ["BYTE"] = Tuple.Create(8, false),
            ["INT"] = Tuple.Create(16, true), ["UINT"] = Tuple.Create(16, false), ["WORD"] = Tuple.Create(16, false),
            ["DINT"] = Tuple.Create(32, true), ["UDINT"] = Tuple.Create(32, false), ["DWORD"] = Tuple.Create(32, false),
            ["LINT"] = Tuple.Create(64, true), ["ULINT"] = Tuple.Create(64, false), ["LWORD"] = Tuple.Create(64, false),
        };

        // The width in bits of an integer or bit-string type, else null.
        internal static int? Bits(string type) => type != null && Integers.TryGetValue(type, out var integer) ? integer.Item1 : (int?)null;

        // The bit width of each integer or bit-string variable, by lower-cased name.
        internal static Dictionary<string, int> Widths(IEnumerable<VarMember> members)
        {
            var widths = new Dictionary<string, int>();
            foreach (var member in members)
            {
                var type = StDeclarations.ClassifyType(member.Type);
                if (type.Kind == "scalar" && Bits(type.Base) is int width) widths[member.Name.ToLowerInvariant()] = width;
            }
            return widths;
        }

        // The smallest and largest value of an integer or bit-string type, else null.
        internal static Tuple<BigInteger, BigInteger> Range(string type)
        {
            if (type == null || !Integers.TryGetValue(type, out var integer)) return null;
            return integer.Item2
                ? Tuple.Create(-BigInteger.Pow(2, integer.Item1 - 1), BigInteger.Pow(2, integer.Item1 - 1) - 1)
                : Tuple.Create(BigInteger.Zero, BigInteger.Pow(2, integer.Item1) - 1);
        }

        static readonly Regex IntegerForm = new Regex(@"^(?<sign>[+-]?)(?:(?<base>2|8|16)#)?(?<digits>[0-9A-Fa-f]+(?:_[0-9A-Fa-f]+)*)$");

        // A decimal literal with an optional sign, as a pattern already matched it.
        internal static BigInteger Literal(string text) => Integer(text).Value;

        // An integer literal: decimal or 2#, 8#, 16# based, '_' between
        // digits, an optional sign; else null.
        internal static BigInteger? Integer(string text)
        {
            var form = IntegerForm.Match((text ?? "").Trim());
            if (!form.Success) return null;
            var radix = form.Groups["base"].Success ? int.Parse(form.Groups["base"].Value) : 10;
            BigInteger value = 0;
            foreach (var digit in form.Groups["digits"].Value.Replace("_", ""))
            {
                var place = "0123456789abcdef".IndexOf(char.ToLowerInvariant(digit));
                if (place >= radix) return null;
                value = value * radix + place;
            }
            return form.Groups["sign"].Value == "-" ? -value : value;
        }

        static readonly Dictionary<string, BigInteger> ScalarBytes = new Dictionary<string, BigInteger>(StringComparer.OrdinalIgnoreCase)
        {
            ["BOOL"] = 1, ["BIT"] = 1, ["SINT"] = 1, ["USINT"] = 1, ["BYTE"] = 1, ["CHAR"] = 1,
            ["INT"] = 2, ["UINT"] = 2, ["WORD"] = 2, ["WCHAR"] = 2, ["DINT"] = 4, ["UDINT"] = 4,
            ["DWORD"] = 4, ["REAL"] = 4, ["TIME"] = 4, ["LINT"] = 8, ["ULINT"] = 8,
            ["LWORD"] = 8, ["LREAL"] = 8, ["LTIME"] = 8,
        };
        static readonly Regex Decimal = new Regex(@"^[+-]?\d+$");
        internal static readonly Regex StringType = new Regex(@"^(?<wide>W)?STRING\s*\(\s*(?<size>\d+)\s*\)$", RegexOptions.IgnoreCase);

        // A plain decimal integer, signed or not.
        internal static bool IsDecimal(string text) => Decimal.IsMatch(text);

        // Bytes of a type made of scalars, strings of a given length and
        // arrays with literal bounds, else null. A string holds its length
        // plus a terminating character.
        internal static BigInteger? Bytes(string type)
        {
            var text = type.Trim();
            var sized = StringType.Match(text);
            if (sized.Success) return (BigInteger.Parse(sized.Groups["size"].Value) + 1) * (sized.Groups["wide"].Success ? 2 : 1);
            var shape = StDeclarations.ClassifyType(text);
            if (shape.Kind == "scalar") return ScalarBytes.TryGetValue(shape.Base, out var bytes) ? bytes : (BigInteger?)null;
            if (shape.Kind != "array") return null;
            var size = Bytes(shape.Element);
            foreach (var dimension in shape.Dimensions)
                size *= Integer(dimension.Value) - Integer(dimension.Key) + 1;
            return size;
        }

        // The characters a STRING(n) or WSTRING(n) holds, else null.
        internal static int? StringCapacity(string type)
        {
            var sized = StringType.Match(type.Trim());
            return sized.Success && int.TryParse(sized.Groups["size"].Value, out var size) ? size : (int?)null;
        }

        // A STRING ('...') or WSTRING ("...") literal.
        internal const string StringLiteral = @"W?(?:'(?:\$.|''|[^'$])*'|""(?:\$.|""""|[^""$])*"")";
        static readonly Regex WholeLiteral = new Regex("^" + StringLiteral + "$", RegexOptions.Singleline);
        // One character of a STRING and of a WSTRING literal.
        static readonly Regex Character = new Regex(@"\$[0-9A-Fa-f]{2}|\$.|''|.", RegexOptions.Singleline);
        static readonly Regex WideCharacter = new Regex(@"\$[0-9A-Fa-f]{4}|\$.|""""|.", RegexOptions.Singleline);

        // The characters of a whole string literal, each '$' escape ("$'",
        // "$N", "$0A") one; else null.
        internal static int? StringLength(string literal)
        {
            if (!WholeLiteral.IsMatch(literal)) return null;
            var quoted = literal.TrimStart('W', 'w');
            return (quoted[0] == '"' ? WideCharacter : Character).Matches(quoted.Substring(1, quoted.Length - 2)).Count;
        }
    }
}
