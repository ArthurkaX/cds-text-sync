using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Visu
{
    // Colours, sizes, grid and attribute values as a sketch writes them.
    internal static partial class SvgSketch
    {
        static string Resolve(string expression, IDictionary<string, string> theme)
        {
            if (expression == null) return null;
            var value = expression.Trim();
            if (value.Length == 0 || value.Equals("none", StringComparison.OrdinalIgnoreCase)) return null;
            var match = Regex.Match(value, @"var\(--([^)]+)\)");
            if (match.Success)
            {
                var key = match.Groups[1].Value.Replace('-', '.');
                if (!theme.TryGetValue(key, out value)) throw new VisuException("Color role '--" + match.Groups[1].Value + "' not found in theme");
            }
            var raw = value;
            if (raw.StartsWith("#", StringComparison.Ordinal))
                raw = raw.Substring(1);
            else if (raw.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
                raw = raw.Substring(2);
            if (Regex.IsMatch(raw, @"^[0-9a-fA-F]{1,8}$"))
            {
                var number = uint.Parse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture);
                if (raw.Length <= 6) number |= 0xff000000;
                return number.ToString(CultureInfo.InvariantCulture);
            }
            if (int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var integer))
                return unchecked((uint)integer).ToString(CultureInfo.InvariantCulture);
            throw new VisuException("Cannot resolve color expression: '" + expression + "'");
        }

        static string ApplyOpacity(string color, string opacity)
        {
            if (color == null || !color.StartsWith("#", StringComparison.Ordinal)) return color;
            if (color.Length != 7 && color.Length != 9) return color;
            var ratio = 1.0;
            if (!string.IsNullOrEmpty(opacity) && !double.TryParse(opacity, NumberStyles.Float, CultureInfo.InvariantCulture, out ratio)) ratio = 1.0;
            ratio = Math.Max(0, Math.Min(1, ratio));
            var alpha = ((int)Math.Round(ratio * 255)).ToString("X2", CultureInfo.InvariantCulture);
            return color.Length == 7 ? "#" + alpha + color.Substring(1) : "#" + alpha + color.Substring(3);
        }

        static double Percent(string value, double fallback)
        {
            if (string.IsNullOrWhiteSpace(value)) return fallback;
            var text = value.Trim();
            var percent = text.EndsWith("%", StringComparison.Ordinal);
            if (percent) text = text.Substring(0, text.Length - 1);
            if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out var number)) return fallback;
            return percent ? number : number * 100;
        }

        static int FontSize(XElement element)
        {
            var size = Number(element, "font-size", 12);
            return (int)size;
        }

        static int TextWidth(string text, int fontSize)
        {
            const string narrow = " .,:;'`|!ijlI";
            const string thin = "ft()[]{}/\\-\"J";
            const string wide = "ABCDEFGHKLNOPQRSTUVXYZ&$#";
            const string widest = "mwMW%@";
            var em = (text ?? "")
                         .Sum(character => narrow.Contains(character)   ? 280
                                           : thin.Contains(character)   ? 333
                                           : wide.Contains(character)   ? 667
                                           : widest.Contains(character) ? 833
                                                                        : 556);
            var raw = Math.Max(20, (int)(em * fontSize / 1000.0) + 8);
            return ToGrid(raw);
        }

        static int TextHeight(int fontSize)
        {
            return ToGrid(Math.Max(16, (int)(fontSize * 1.4)));
        }

        static int ToGrid(int value)
        {
            return ((value + 3) / 4) * 4;
        }

        static string ParseTap(string value)
        {
            var text = (value ?? "").Trim();
            var lower = text.ToLowerInvariant();
            foreach (var prefix in new[] { "tap:", "tap ", "toggle:", "toggle " })
            {
                if (lower.StartsWith(prefix, StringComparison.Ordinal)) return text.Substring(prefix.Length).Trim();
            }
            return text;
        }

        static string BooleanString(string value, bool fallback)
        {
            var parsed = string.IsNullOrWhiteSpace(value) ? fallback : value.Trim().Equals("true", StringComparison.OrdinalIgnoreCase);
            return parsed ? "True" : "False";
        }

        static IDictionary<string, string> AttributeMap(XElement element, string prefix)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var attribute in element.Attributes().Where(attribute => attribute.Name.LocalName.StartsWith(prefix, StringComparison.Ordinal)))
            {
                values[attribute.Name.LocalName.Substring(prefix.Length)] = attribute.Value;
            }
            return values;
        }

        static void AddOptional(IDictionary<string, object> values, string key, object value)
        {
            if (value == null) return;
            if (value is string text && string.IsNullOrEmpty(text)) return;
            if (value is System.Collections.ICollection collection && collection.Count == 0) return;
            values[key] = value;
        }

        static double Number(XElement element, string name, double fallback)
        {
            return Number((string)element.Attribute(name), fallback);
        }

        static double Number(string value, double fallback)
        {
            return double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number) ? number : fallback;
        }

        static string Integer(XElement element, string name, int fallback)
        {
            return ParseInteger((string)element.Attribute(name), fallback).ToString(CultureInfo.InvariantCulture);
        }

        static int ParseInteger(string value, int fallback)
        {
            return int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number) ? number : fallback;
        }

        static string Integer(double value)
        {
            return ((int)value).ToString(CultureInfo.InvariantCulture);
        }
    }
}
