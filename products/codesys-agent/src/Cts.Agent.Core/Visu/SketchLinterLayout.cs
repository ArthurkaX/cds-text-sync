using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Visu
{
    // The layout findings: overlaps, empty panels, lonely cards, container padding and crowding.
    internal static partial class SketchLinter
    {
        // The elements that cover an area: all but lines.
        static List<IndexedElement> Boxes(Sketch sketch) =>
            sketch.Elements.Select((element, index) => new IndexedElement { Element = element, Index = index }).Where(item => item.Element.Type != "line").ToList();

        static void AddOverlaps(Sketch sketch, IList<Finding> findings)
        {
            var boxes = Boxes(sketch);
            for (var first = 0; first < boxes.Count; first++)
            {
                for (var second = first + 1; second < boxes.Count; second++)
                {
                    var a = boxes[first];
                    var b = boxes[second];
                    var ax = Int(a.Element, "x");
                    var ay = Int(a.Element, "y");
                    var aw = Int(a.Element, "width");
                    var ah = Int(a.Element, "height");
                    var bx = Int(b.Element, "x");
                    var by = Int(b.Element, "y");
                    var bw = Int(b.Element, "width");
                    var bh = Int(b.Element, "height");
                    if (Contains(ax, ay, aw, ah, bx, by, bw, bh) || Contains(bx, by, bw, bh, ax, ay, aw, ah)) continue;
                    if (ax + aw <= bx || bx + bw <= ax || ay + ah <= by || by + bh <= ay) continue;
                    var decorative = new[] { "rectangle", "line" }.Contains(a.Element.Type) && new[] { "rectangle", "line" }.Contains(b.Element.Type);
                    var startsInA = StartsInside(a.Element, ax, ay, aw, ah, b.Element, bx, by);
                    var startsInB = StartsInside(b.Element, bx, by, bw, bh, a.Element, ax, ay);
                    if (startsInA)
                        findings.Add(new Finding { Rule = "overflow", Severity = decorative ? "info" : "warn", Index = b.Index,
                                                   Message = Describe(b) + " overflows " + Describe(a) });
                    else if (startsInB)
                        findings.Add(new Finding { Rule = "overflow", Severity = decorative ? "info" : "warn", Index = a.Index,
                                                   Message = Describe(a) + " overflows " + Describe(b) });
                    else
                        findings.Add(new Finding { Rule = "overlap", Severity = decorative ? "info" : "warn", Index = a.Index,
                                                   Message = Describe(a) + " overlaps " + Describe(b) });
                }
            }
        }

        static bool StartsInside(Sketch.Element outer, int outerX, int outerY, int outerWidth, int outerHeight, Sketch.Element inner, int innerX,
                                 int innerY)
        {
            return outer.Type == "rectangle" && inner.Type != "rectangle" && outerX <= innerX && innerX <= outerX + outerWidth && outerY <= innerY
                   && innerY <= outerY + outerHeight;
        }

        static bool Contains(int outerX, int outerY, int outerWidth, int outerHeight, int innerX, int innerY, int innerWidth, int innerHeight)
        {
            return innerX >= outerX && innerY >= outerY && innerX + innerWidth <= outerX + outerWidth && innerY + innerHeight <= outerY + outerHeight;
        }

        static string Describe(IndexedElement item)
        {
            var element = item.Element;
            var index = item.Index;
            var text = (element.Params["text"] ?? "").Trim();
            if (text.Length > 20) text = text.Substring(0, 17) + "...";
            var source = element.Source;
            var x = (string)source.Attribute("x") ?? (string)source.Attribute("cx") ?? (string)source.Attribute("x1") ?? element.Params["x"];
            var y = (string)source.Attribute("y") ?? (string)source.Attribute("cy") ?? (string)source.Attribute("y1") ?? element.Params["y"];
            var shape = ShapeName(element);
            return shape + " #" + index + (text.Length == 0 ? "" : " \"" + text + "\"") + " at " + x + "," + y;
        }

        static string ShapeName(Sketch.Element element)
        {
            if (element.Type != "rectangle") return element.Type;
            if (!element.Params.TryGetValue("shape", out var shape)) return "rectangle";
            if (shape == "ellipse") return "ellipse";
            if (shape == "rounded") return "rounded rectangle";
            return "rectangle";
        }

        static void AddEmptyPanels(Sketch sketch, IList<Finding> findings)
        {
            for (var index = 0; index < sketch.Elements.Count; index++)
            {
                var panel = sketch.Elements[index];
                if (!((string)panel.Source.Attribute("class") ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries).Contains("panel"))
                    continue;
                var x = Int(panel, "x");
                var y = Int(panel, "y");
                var width = Int(panel, "width");
                var height = Int(panel, "height");
                var hasContents
                    = sketch.Elements.Where((element, childIndex) => childIndex != index)
                          .Any(child => Contains(x, y, width, height, Int(child, "x"), Int(child, "y"), Int(child, "width"), Int(child, "height")));
                if (!hasContents)
                    findings.Add(new Finding { Rule = "empty-panel", Severity = "warn", Index = index,
                                               Message = "panel at " + SourceXy(panel) + " has nothing in it" });
            }
        }

        static void AddLonelyCards(Sketch sketch, IList<Finding> findings)
        {
            if (!sketch.Theme.TryGetValue("card", out var cardColor) || !sketch.Theme.TryGetValue("screen", out var screenColor)) return;
            if (!TryLuma(cardColor, out var cardLuma) || !TryLuma(screenColor, out var screenLuma)) return;
            if (Math.Abs(cardLuma - screenLuma) >= 12) return;
            for (var index = 0; index < sketch.Elements.Count; index++)
            {
                var element = sketch.Elements[index];
                var classes = ((string)element.Source.Attribute("class") ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                if (!classes.Contains("card")) continue;
                var x = Int(element, "x");
                var y = Int(element, "y");
                var width = Int(element, "width");
                var height = Int(element, "height");
                var nested = sketch.Elements.Where((candidate, candidateIndex) => candidateIndex != index)
                                 .Any(candidate => Contains(Int(candidate, "x"), Int(candidate, "y"), Int(candidate, "width"),
                                                            Int(candidate, "height"), x, y, width, height));
                if (!nested)
                    findings.Add(
                        new Finding { Rule = "lonely-card", Severity = "warn", Index = index,
                                      Message
                                      = "card at " + x + "," + y
                                        + " sits on the screen background, where it is almost invisible; a top-level box is class=\"panel\"" });
            }
        }

        static bool TryLuma(string color, out double luma)
        {
            var raw = (color ?? "").Trim().TrimStart('#');
            luma = 0;
            if (raw.Length != 6) return false;
            try
            {
                var red = Convert.ToInt32(raw.Substring(0, 2), 16);
                var green = Convert.ToInt32(raw.Substring(2, 2), 16);
                var blue = Convert.ToInt32(raw.Substring(4, 2), 16);
                luma = 0.299 * red + 0.587 * green + 0.114 * blue;
                return true;
            }
            catch (FormatException)
            {
                return false;
            }
        }

        static void AddContainerPadding(Sketch sketch, IList<Finding> findings)
        {
            var containers = sketch.Elements.Select((element, index) => new IndexedElement { Element = element, Index = index })
                                 .Where(item => (item.Element.Type == "rectangle" || item.Element.Type == "line")
                                                && (((string)item.Element.Source.Attribute("class") ?? "")
                                                        .Split((char[])null, StringSplitOptions.RemoveEmptyEntries)
                                                        .Contains("panel")
                                                    || ((string)item.Element.Source.Attribute("class") ?? "")
                                                           .Split((char[])null, StringSplitOptions.RemoveEmptyEntries)
                                                           .Contains("card")))
                                 .ToList();
            for (var index = 0; index < sketch.Elements.Count; index++)
            {
                var child = sketch.Elements[index];
                if (child.Type == "rectangle" || child.Type == "line") continue;
                var x = Int(child, "x");
                var y = Int(child, "y");
                var width = Int(child, "width");
                var height = Int(child, "height");
                var holders = containers
                                  .Where(item => item.Index != index
                                                 && Contains(Int(item.Element, "x"), Int(item.Element, "y"), Int(item.Element, "width"),
                                                             Int(item.Element, "height"), x, y, width, height))
                                  .ToList();
                if (holders.Count == 0) continue;
                var holder = holders.OrderBy(item => Int(item.Element, "width") * Int(item.Element, "height")).First();
                var left = Int(holder.Element, "x");
                var top = Int(holder.Element, "y");
                var rightGap = left + Int(holder.Element, "width") - x - width;
                var bottomGap = top + Int(holder.Element, "height") - y - height;
                var gaps = new[] { Tuple.Create("left", x - left), Tuple.Create("top", y - top), Tuple.Create("right", rightGap),
                                   Tuple.Create("bottom", bottomGap) };
                var tight = gaps.Where(gap => gap.Item2 < 8).OrderBy(gap => gap.Item2).FirstOrDefault();
                if (tight != null)
                {
                    var classes = ((string)holder.Element.Source.Attribute("class") ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
                    var kind = classes.Contains("panel") ? "panel" : "card";
                    findings.Add(new Finding { Rule = "padding", Severity = "warn", Index = index,
                                               Message = Describe(new IndexedElement { Element = child, Index = index }) + " is " + tight.Item2
                                                         + "px from the " + tight.Item1 + " edge of the " + kind + " at " + SourceXy(holder.Element)
                                                         + "; keep 16px inside a container" });
                }
            }
        }

        static void AddCrowding(Sketch sketch, IList<Finding> findings)
        {
            var boxes = Boxes(sketch);
            for (var first = 0; first < boxes.Count; first++)
            {
                for (var second = first + 1; second < boxes.Count; second++)
                {
                    var left = boxes[first];
                    var right = boxes[second];
                    var a = left.Element;
                    var b = right.Element;
                    if (IsProcessDrawing(a.Source) && IsProcessDrawing(b.Source)) continue;
                    if (IsTypeLabel(a.Source) && IsTypeLabel(b.Source)) continue;
                    var ax = Int(a, "x");
                    var ay = Int(a, "y");
                    var aw = Int(a, "width");
                    var ah = Int(a, "height");
                    var bx = Int(b, "x");
                    var by = Int(b, "y");
                    var bw = Int(b, "width");
                    var bh = Int(b, "height");
                    var horizontalGap = bx >= ax ? bx - ax - aw : ax - bx - bw;
                    var verticalGap = by >= ay ? by - ay - ah : ay - by - bh;
                    if (horizontalGap > 0 && horizontalGap < 8 && ay < by + bh && by < ay + ah)
                    {
                        findings.Add(
                            new Finding { Rule = "crowding", Severity = "info", Index = left.Index,
                                          Message = Describe(left) + " and " + Describe(right) + " are " + horizontalGap + "px apart horizontally" });
                    }
                    else if (verticalGap > 0 && verticalGap < 8 && ax < bx + bw && bx < ax + aw)
                    {
                        findings.Add(
                            new Finding { Rule = "crowding", Severity = "info", Index = left.Index,
                                          Message = Describe(left) + " and " + Describe(right) + " are " + verticalGap + "px apart vertically" });
                    }
                }
            }
        }

        static bool IsProcessDrawing(System.Xml.Linq.XElement source)
        {
            var classes = ((string)source.Attribute("class") ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            return classes.Contains("pipe-water") || classes.Contains("metal");
        }

        static bool IsTypeLabel(System.Xml.Linq.XElement source)
        {
            return source.Name.LocalName == "text";
        }

        static string SourceXy(Sketch.Element element)
        {
            var source = element.Source;
            var x = (string)source.Attribute("x") ?? (string)source.Attribute("cx") ?? (string)source.Attribute("x1") ?? element.Params["x"];
            var y = (string)source.Attribute("y") ?? (string)source.Attribute("cy") ?? (string)source.Attribute("y1") ?? element.Params["y"];
            return x + "," + y;
        }
    }
}
