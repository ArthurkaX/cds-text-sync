using System.Globalization;
using System.Text.RegularExpressions;

namespace Cts.Visu
{
    // Screen-level edits are regular text substitutions so the remaining XML
    // keeps the exact layout produced by CODESYS.
    internal static class ScreenText
    {
        internal static string Resize(string xml, int width, int height)
        {
            xml = Replace(xml, "SizeX", width.ToString(CultureInfo.InvariantCulture));
            return Replace(xml, "SizeY", height.ToString(CultureInfo.InvariantCulture));
        }

        internal static string ClearElements(string xml)
        {
            var match = Regex.Match(xml, "<List\\s+Name=\"VisualElementList\"[^>]*>");
            if (!match.Success) throw new VisuException("Screen file has no VisualElementList");
            var end = ElementTemplates.ClosingList(xml, match.Index + match.Length);
            return xml.Substring(0, match.Index + match.Length) + xml.Substring(end);
        }

        internal static string SetBackground(string xml, string background)
        {
            var raw = (background ?? "").Trim();
            if (raw.Length == 0) return xml;
            if (raw[0] == '#') raw = raw.Substring(1);
            else if (raw.StartsWith("0x", System.StringComparison.OrdinalIgnoreCase)) raw = raw.Substring(2);
            if (!uint.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var color))
                throw new VisuException("Invalid background color: " + background);
            if (raw.Length <= 6) color |= 0xff000000;
            var signed = unchecked((int)color).ToString(CultureInfo.InvariantCulture);
            xml = Regex.Replace(xml, "(<Single Name=\"BgColor\" Type=\"bool\">)[^<]*(</Single>)",
                "$1True$2", RegexOptions.None, System.TimeSpan.FromSeconds(1));
            return Regex.Replace(xml, "(<Single Name=\"BgUseColor\" Type=\"int\">)[^<]*(</Single>)",
                "$1" + signed + "$2", RegexOptions.None, System.TimeSpan.FromSeconds(1));
        }

        static string Replace(string xml, string name, string value)
        {
            var pattern = "(<Single Name=\"" + Regex.Escape(name) + "\" Type=\"int\">)[^<]*(</Single>)";
            var result = Regex.Replace(xml, pattern, match => match.Groups[1].Value + value + match.Groups[2].Value,
                RegexOptions.None, System.TimeSpan.FromSeconds(1));
            if (result == xml) throw new VisuException("Screen file has no " + name);
            return result;
        }
    }
}
