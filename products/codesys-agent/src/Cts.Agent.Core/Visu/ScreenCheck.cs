using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Xml.Linq;

namespace Cts.Visu
{
    // What `cts visu check` finds wrong with a screen before CODESYS does.
    internal static class ScreenCheck
    {
        sealed class Box
        {
            internal string Identifier;
            internal string Type;
            internal int X;
            internal int Y;
            internal int Width;
            internal int Height;
        }

        internal static List<string> Problems(int sizeX, int sizeY, IEnumerable<ScreenElement> elements)
        {
            var problems = new List<string>();
            var boxes = new List<Box>();
            foreach (var element in elements)
            {
                var name = element.Identifier;
                if (!Number(element.Value(ScreenXml.X), out var x) || !Number(element.Value(ScreenXml.Y), out var y)
                    || !Number(element.Value(ScreenXml.Width), out var width) || !Number(element.Value(ScreenXml.Height), out var height))
                {
                    problems.Add(name + ": non-numeric geometry");
                    continue;
                }
                if (x < 0 || y < 0) problems.Add(name + ": X and Y must be >= 0 (got X=" + x + ", Y=" + y + ")");
                if (width <= 0 || height <= 0) problems.Add(name + ": Width and Height must be > 0 (got W=" + width + ", H=" + height + ")");
                if (x + width > sizeX) problems.Add(name + ": X+Width (" + (x + width) + ") exceeds screen SizeX (" + sizeX + ")");
                if (y + height > sizeY) problems.Add(name + ": Y+Height (" + (y + height) + ") exceeds screen SizeY (" + sizeY + ")");
                Center(problems, element, ScreenXml.CenterX, x + width / 2, "CenterX", "X+W/2");
                Center(problems, element, ScreenXml.CenterY, y + height / 2, "CenterY", "Y+H/2");
                foreach (var member in element.Members)
                {
                    if (member.Value.Kind == "color" && member.Value.CanonicalName.Trim().Length == 0)
                        problems.Add(name + ": color member " + member.Key + " has empty CanonicalName");
                }
                if ((element.Value(ScreenXml.Text) ?? "").Trim().Length > 0 && (element.Value(ScreenXml.TextId) ?? "").Trim().Length == 0)
                    problems.Add(name + ": has non-empty text but no Text ID (" + ScreenXml.TextId + "); CODESYS will reject the import");
                boxes.Add(new Box { Identifier = name, Type = element.Type, X = x, Y = y, Width = width, Height = height });
            }
            for (var i = 0; i < boxes.Count; i++)
            {
                for (var j = i + 1; j < boxes.Count; j++)
                {
                    if (Overlap(boxes[i], boxes[j]) && !Expected(boxes[i], boxes[j]))
                        problems.Add("overlap: " + boxes[i].Identifier + " overlaps " + boxes[j].Identifier);
                }
            }
            return problems;
        }

        // A colour whose ExplicitColor differs from its live NamedColor:
        // CODESYS paints the named one, so the explicit value is a lie (CODESYS
        // itself writes both, the same value, on a font).
        internal static IEnumerable<string> ColorConflicts(XElement root)
        {
            foreach (var explicitColor in root.Descendants("Single").Where(e => (string)e.Attribute("Name") == "ExplicitColor"))
            {
                var owner = explicitColor.Parent;
                var named = owner?.Elements("Single").FirstOrDefault(e => (string)e.Attribute("Name") == "NamedColor");
                if (named == null) continue;
                var shown = named.Elements("Single").FirstOrDefault(e => (string)e.Attribute("Name") == "Color")?.Value.Trim();
                if (shown == explicitColor.Value.Trim()) continue;
                var canonical = named.Elements("Single").FirstOrDefault(e => (string)e.Attribute("Name") == "CanonicalName")?.Value ?? "";
                yield return "ExplicitColor " + explicitColor.Value.Trim() + " is ignored: a live NamedColor" + (canonical.Length > 0 ? " (" + canonical + ")" : "")
                    + " takes precedence (line " + ((System.Xml.IXmlLineInfo)explicitColor).LineNumber + ")";
            }
        }

        // A missing or empty geometry member counts as 0, as CODESYS reads it.
        static bool Number(string text, out int value)
        {
            value = 0;
            return string.IsNullOrWhiteSpace(text) || int.TryParse(text.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out value);
        }

        static void Center(List<string> problems, ScreenElement element, long id, int expected, string label, string formula)
        {
            var actual = element.Value(id);
            if (actual != null && actual.Trim() != expected.ToString(CultureInfo.InvariantCulture))
                problems.Add(element.Identifier + ": " + label + " " + actual + " != " + formula + " (" + expected + ")");
        }

        static bool Overlap(Box a, Box b)
        {
            return a.X < b.X + b.Width && b.X < a.X + a.Width && a.Y < b.Y + b.Height && b.Y < a.Y + a.Height;
        }

        // Lines and simple elements decorate others, and an element inside
        // another (a lamp on its panel) is a composition, not a collision.
        static bool Expected(Box a, Box b)
        {
            if (Decoration(a) || Decoration(b)) return true;
            return Inside(a, b) || Inside(b, a);
        }

        static bool Decoration(Box box)
        {
            return box.Type == "VisuFbElemLine" || box.Type == "VisuFbElemSimple";
        }

        static bool Inside(Box outer, Box inner)
        {
            return inner.X >= outer.X && inner.Y >= outer.Y && inner.X + inner.Width <= outer.X + outer.Width && inner.Y + inner.Height <= outer.Y + outer.Height;
        }
    }
}
