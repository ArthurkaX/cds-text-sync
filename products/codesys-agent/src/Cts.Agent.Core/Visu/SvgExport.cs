using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Xml.Linq;

namespace Cts.Visu
{
    // Decompile the screen elements and their stable member ids into SVG.
    internal static class SvgExport
    {
        const long Shape = 564465120;
        const long Radius = 1869484343;
        const long Fill = 2812299069;
        const long Frame = 494569607;
        const long Border = 2678395525;
        const long Font = 663104332;
        const long FontSize = 4253639993;
        const long Align = 2340015797;
        const long FontName = 1603690730;
        const long Variable = 743958181;
        const long UseGradient = 1375557818;
        const long GradientData = 494542316;
        const long InputVariable = 1186196937;
        const long TextVariable = 2477733581;
        const long ToggleColor = 1999528970;
        const long AlarmFill = 493260384;
        const long AlarmFrame = 135947015;
        const long FillVariable = 401380312;
        const long FrameVariable = 3450524324;

        internal static string ScreenToSvg(string xml, string scheme = null)
        {
            XElement root;
            try
            {
                root = ScreenXml.Parse(xml);
            }
            catch (VisuException error)
            {
                throw new VisuException("Could not parse screen XML: " + error.Message);
            }

            var size = ScreenXml.Size(root);
            var bgEnabled = root.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "BgColor")?.Value.Trim() == "True";
            var bgValue = root.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "BgUseColor")?.Value.Trim();
            var background = bgEnabled ? LiteralColor(bgValue) : null;
            var dark = StyleRoles.NormalizeScheme(scheme ?? (IsDark(background) ? "dark" : "light")) == "dark";
            var palette = Themes.Palette(dark ? "dark" : "light", "flat-style");
            var themeBlock = string.Join("", palette.OrderBy(pair => pair.Key, StringComparer.Ordinal)
                .Select(pair => " --" + pair.Key.Replace('.', '-') + ":" + pair.Value + ";"));
            var pieces = new List<string>
            {
                "<svg xmlns=\"http://www.w3.org/2000/svg\"",
                "     width=\"" + size.Width.ToString(CultureInfo.InvariantCulture) + "\" height=\""
                    + size.Height.ToString(CultureInfo.InvariantCulture) + "\"",
                "     viewBox=\"0 0 " + size.Width.ToString(CultureInfo.InvariantCulture) + " "
                    + size.Height.ToString(CultureInfo.InvariantCulture) + "\"",
                "     style=\"background:" + (background ?? "var(--surface)") + "\""
                    + (dark ? " data-cds-scheme=\"dark\"" : "") + ">",
                "  <defs><style>:root{" + themeBlock + "}</style></defs>",
            };
            var gradients = new List<string>();
            foreach (var element in ScreenXml.Elements(root))
            {
                var definition = GradientDefinition(element, "cts-grad-" + element.Index.ToString(CultureInfo.InvariantCulture));
                if (definition != null) gradients.Add(definition);
            }
            if (gradients.Count > 0)
            {
                pieces.Add("  <defs>");
                pieces.AddRange(gradients.Select(gradient => "    " + gradient));
                pieces.Add("  </defs>");
            }
            foreach (var element in ScreenXml.Elements(root))
            {
                var gradient = GradientDefinition(element, "cts-grad-" + element.Index.ToString(CultureInfo.InvariantCulture));
                var svg = Render(element, gradient == null ? null : "url(#cts-grad-" + element.Index.ToString(CultureInfo.InvariantCulture) + ")");
                var actions = InputActions(element);
                if (actions.Count > 0) svg = InjectAction(svg, string.Join(" || ", actions));
                pieces.Add("  " + svg);
            }
            pieces.Add("</svg>");
            return string.Join("\n", pieces) + "\n";
        }

        static string Render(ScreenElement element, string gradientRef = null)
        {
            var type = element.Type;
            var attrs = new SortedDictionary<string, string>(StringComparer.Ordinal);
            var tag = "rect";
            if (type == "VisuFbElemSimple")
            {
                var shape = Value(element, Shape) ?? "VISU_ST_RECTANGLE";
                if (shape == "VISU_ST_CIRCLE")
                {
                    tag = "circle";
                    var x = Number(Value(element, ScreenXml.X));
                    var y = Number(Value(element, ScreenXml.Y));
                    var w = Number(Value(element, ScreenXml.Width));
                    var h = Number(Value(element, ScreenXml.Height));
                    attrs["cx"] = (x + w / 2).ToString(CultureInfo.InvariantCulture);
                    attrs["cy"] = (y + h / 2).ToString(CultureInfo.InvariantCulture);
                    attrs["r"] = (Math.Min(w, h) / 2).ToString(CultureInfo.InvariantCulture);
                }
                else
                {
                    if (shape != "VISU_ST_RECTANGLE" && shape != "VISU_ST_ROUNDRECT")
                        throw new VisuException("Unsupported shape variant: '" + shape + "'");
                    Box(element, attrs);
                    if (shape == "VISU_ST_ROUNDRECT") attrs["rx"] = Value(element, Radius) ?? "8";
                }
                Paint(element, attrs, gradientRef);
                Put(attrs, "data-text", Value(element, ScreenXml.Text));
                Put(attrs, "data-text-var", Value(element, TextVariable));
                var toggle = Value(element, ToggleColor);
                if (!string.IsNullOrEmpty(toggle) && toggle != "<toggle/tap variable>")
                {
                    attrs["data-color-var"] = toggle;
                    Put(attrs, "data-on-fill", Color(element, AlarmFill));
                    Put(attrs, "data-on-stroke", Color(element, AlarmFrame));
                }
                Put(attrs, "data-fill-var", Value(element, FillVariable));
                Put(attrs, "data-stroke-var", Value(element, FrameVariable));
            }
            else if (type == "VisuFbElemButton" || type == "VisuFbElemLamp"
                || type == "VisuFbImageSwitcher" || type == "VisuFbComboBoxInteger" || type == "VisuFbElemAlarmBanner"
                || type == "VisuFbFrame" || type == "VisuFbElemSlider")
            {
                attrs["data-cds-type"] = type == "VisuFbElemButton" ? "button"
                    : type == "VisuFbElemTextfield" ? "textfield" : type == "VisuFbElemLamp" ? "lamp"
                    : type == "VisuFbImageSwitcher" ? "image-switcher" : type == "VisuFbComboBoxInteger" ? "combobox"
                    : type == "VisuFbElemAlarmBanner" ? "alarm-banner" : type == "VisuFbFrame" ? "frame" : "slider";
                Box(element, attrs);
                if (type == "VisuFbElemButton")
                {
                    Put(attrs, "data-text", Value(element, ScreenXml.Text));
                    Put(attrs, "fill", Color(element, Fill));
                    Put(attrs, "stroke", Color(element, Frame));
                }
                if (type == "VisuFbElemLamp")
                {
                    var role = Value(element, 4062784938);
                    var suffix = role == null ? "" : role.Split('-').Last();
                    var color = new Dictionary<string, string> { ["Red"] = "red", ["Green"] = "green", ["Yellow"] = "yellow", ["Blue"] = "blue", ["Gray"] = "gray" };
                    if (color.TryGetValue(suffix, out var lampColor)) attrs["data-color"] = lampColor;
                    Put(attrs, "data-var", Value(element, Variable));
                }
                if (type == "VisuFbImageSwitcher")
                {
                    Put(attrs, "data-image-on", Value(element, 427565733));
                    Put(attrs, "data-image-off", Value(element, 296037572));
                    Put(attrs, "data-var", Value(element, Variable));
                }
                if (type == "VisuFbComboBoxInteger")
                {
                    Put(attrs, "data-items", Value(element, 2114174855));
                    Put(attrs, "data-var", Value(element, 397264524));
                }
                if (type == "VisuFbElemSlider")
                {
                    Put(attrs, "data-var", Value(element, 397264524));
                    Put(attrs, "data-orientation", Value(element, 2640826223));
                    Put(attrs, "data-min", Value(element, 1404881523));
                    Put(attrs, "data-max", Value(element, 3837067714));
                }
                if (type == "VisuFbFrame")
                {
                    var reference = element.Source.DescendantsAndSelf()
                        .FirstOrDefault(node => node.Name.LocalName == "Single" && (string)node.Attribute("Name") == "VisNodeRefs33");
                    Put(attrs, "data-visu", reference?.Value.Trim());
                    var holder = reference?.Parent;
                    var children = holder?.Elements().FirstOrDefault(node => node.Name.LocalName == "List"
                        && (string)node.Attribute("Name") == "TypeNodeChildren");
                    foreach (var parameter in children?.Elements().Where(node => node.Name.LocalName == "Single") ?? Enumerable.Empty<XElement>())
                    {
                        var name = ScreenXml.NamedText(parameter, "TypeNodeName");
                        var validId = long.TryParse(ScreenXml.NamedText(parameter, "TypeNodeIdLong"), NumberStyles.Integer,
                            CultureInfo.InvariantCulture, out var id);
                        if (name.Length > 0 && validId && element.Members.TryGetValue(id, out var member))
                            Put(attrs, "data-param-" + name, member.Value);
                    }
                }
            }
            else if (type == "VisuFbElemLine")
            {
                tag = "line";
                attrs["x1"] = Value(element, 1357360684) ?? "0";
                attrs["y1"] = Value(element, 444643082) ?? "0";
                attrs["x2"] = Value(element, 1837598620) ?? "100";
                attrs["y2"] = Value(element, 669032122) ?? "100";
                Put(attrs, "stroke", Color(element, Frame));
                var lineWidth = Value(element, Border);
                if (int.TryParse(lineWidth, NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsedWidth) && parsedWidth > 0)
                    attrs["stroke-width"] = lineWidth;
            }
            else if (type == "VisuFbLabel" || type == "VisuFbElemTextfield")
            {
                tag = "text";
                var x = Value(element, ScreenXml.X) ?? "0";
                var y = Number(Value(element, ScreenXml.Y));
                var h = Number(Value(element, ScreenXml.Height));
                var size = Number(Value(element, FontSize), 12);
                attrs["x"] = x;
                attrs["y"] = (y + (Value(element, Align) == "HCENTER" ? h / 2 : size)).ToString(CultureInfo.InvariantCulture);
                Put(attrs, "data-width", Value(element, ScreenXml.Width));
                Put(attrs, "data-height", Value(element, ScreenXml.Height));
                attrs["font-family"] = Value(element, FontName) ?? "Arial";
                attrs["font-size"] = size.ToString(CultureInfo.InvariantCulture);
                var align = Value(element, Align);
                if (align == "HCENTER") attrs["text-anchor"] = "middle";
                if (align == "RIGHT") attrs["text-anchor"] = "end";
                var color = Color(element, Font);
                if (color != null) attrs["fill"] = color;
                if (type == "VisuFbElemTextfield")
                {
                    attrs["data-cds-type"] = "textfield";
                    Put(attrs, "data-text-var", Value(element, TextVariable));
                }
                return Tag(tag, attrs, Value(element, ScreenXml.Text) ?? "");
            }
            else
            {
                throw new VisuException("Unsupported element type: '" + (type ?? "unknown") + "'");
            }
            return Tag(tag, attrs, null);
        }

        static void Box(ScreenElement element, IDictionary<string, string> attrs)
        {
            attrs["x"] = Value(element, ScreenXml.X) ?? "0";
            attrs["y"] = Value(element, ScreenXml.Y) ?? "0";
            attrs["width"] = Value(element, ScreenXml.Width) ?? "0";
            attrs["height"] = Value(element, ScreenXml.Height) ?? "0";
        }

        static void Paint(ScreenElement element, IDictionary<string, string> attrs, string gradientRef)
        {
            var fill = Color(element, Fill);
            var frame = Color(element, Frame);
            if (gradientRef != null)
            {
                attrs["fill"] = gradientRef;
                if (GradientType(element) == 2) attrs["data-cds-gradient-type"] = "axial";
            }
            else if (fill != null) attrs["fill"] = fill;
            if (frame != null) attrs["stroke"] = frame;
            var border = Value(element, Border);
            if (int.TryParse(border, NumberStyles.Integer, CultureInfo.InvariantCulture, out var width) && width > 0)
                attrs["stroke-width"] = border;
        }

        static string Value(ScreenElement element, long id)
        {
            return element.Members.TryGetValue(id, out var member) ? member.Value : null;
        }

        static string GradientDefinition(ScreenElement element, string id)
        {
            if (!string.Equals(Value(element, UseGradient), "true", StringComparison.OrdinalIgnoreCase)) return null;
            var slots = ListValues(element, GradientData);
            if (slots == null || slots.Count < 6) return null;
            var first = Stop(slots[0], "0%", "#000000");
            var second = Stop(slots[1], "100%", "#ffffff");
            var type = Number(slots[5]);
            if (type == 1)
                return "<radialGradient id=\"" + id + "\" cx=\"" + Number(slots[3], 50).ToString(CultureInfo.InvariantCulture)
                    + "%\" cy=\"" + Number(slots[4], 50).ToString(CultureInfo.InvariantCulture) + "%\" r=\"50%\">"
                    + first + second + "</radialGradient>";
            var angle = Number(slots[2]) * Math.PI / 180.0;
            var dx = Math.Cos(angle) * 50;
            var dy = Math.Sin(angle) * 50;
            return "<linearGradient id=\"" + id + "\" x1=\"" + Percent(50 - dx) + "%\" y1=\"" + Percent(50 - dy)
                + "%\" x2=\"" + Percent(50 + dx) + "%\" y2=\"" + Percent(50 + dy) + "%\">" + first + second + "</linearGradient>";
        }

        static IList<string> InputActions(ScreenElement element)
        {
            var result = new List<string>();
            var configured = ScreenXml.Named(element.Source, "Array", "ConfiguredComplexInputs");
            if (configured != null)
            {
                foreach (var entry in configured.Elements("Single"))
                {
                    var signature = ScreenXml.NamedText(entry, "SignatureName");
                    var word = signature == "Visu_TapInput" ? "TAP" : signature == "Visu_ToggleInput" ? "TOGGLE" : null;
                    var variable = ScreenXml.Members(entry).TryGetValue(InputVariable, out var member) ? member.Value : null;
                    if (word != null && !string.IsNullOrEmpty(variable)) result.Add(word + " " + variable);
                }
            }

            var actions = ScreenXml.Named(element.Source, "Dictionary", "VisualElementInputActions");
            if (actions == null) return result;
            foreach (var entry in actions.Elements("Entry"))
            {
                var key = entry.Elements().FirstOrDefault(node => node.Name.LocalName == "Key");
                var value = entry.Elements().FirstOrDefault(node => node.Name.LocalName == "Value");
                var eventName = key?.Elements().FirstOrDefault(node => node.Name.LocalName == "Single")?.Value.Trim();
                var array = value?.Elements().FirstOrDefault(node => node.Name.LocalName == "Array");
                if (string.IsNullOrEmpty(eventName) || array == null) continue;
                foreach (var action in array.Elements("Single"))
                {
                    var type = (string)action.Attribute("Type") ?? "";
                    var field = type.StartsWith("{6302d3fe", StringComparison.Ordinal) ? "STSnippet"
                        : type.StartsWith("{9dcc475d", StringComparison.Ordinal) ? "ToggleVariable"
                        : type.StartsWith("{b4c3a27b", StringComparison.Ordinal) ? "Assign33" : null;
                    if (field == null) continue;
                    var text = ScreenXml.NamedText(action, field);
                    if (text.Length == 0) continue;
                    var body = field == "STSnippet" ? "ST " + text : field == "ToggleVariable" ? "toggle " + text : "screen " + text;
                    result.Add(eventName + ": " + body);
                    break;
                }
            }
            return result;
        }

        static string InjectAction(string svg, string action)
        {
            var close = svg.IndexOf(" />", StringComparison.Ordinal);
            if (close < 0) close = svg.IndexOf('>');
            if (close < 0) return svg;
            return svg.Substring(0, close) + " data-cds-action=\"" + Markup.Escape(action) + "\"" + svg.Substring(close);
        }

        static int GradientType(ScreenElement element)
        {
            var slots = ListValues(element, GradientData);
            return slots != null && slots.Count > 5 ? Number(slots[5]) : 0;
        }

        static IList<string> ListValues(ScreenElement element, long id)
        {
            var holder = ScreenXml.Named(element.Source, "Single", "VisualElemMemberList");
            var list = ScreenXml.Named(holder, "List", "VisualElemMemberList");
            var member = list?.Elements("Single").FirstOrDefault(node => Number(ScreenXml.NamedText(node, "Id"), -1) == id);
            var values = ScreenXml.Named(member, "List", "Value");
            if (values == null) return null;
            return values.Elements("Single").Select(node =>
            {
                var color = ScreenXml.Named(node, "Single", "Color");
                return (color ?? node).Value.Trim();
            }).ToList();
        }

        static string Stop(string value, string offset, string fallback)
        {
            if (!uint.TryParse(value ?? "", NumberStyles.Integer, CultureInfo.InvariantCulture, out var color))
            {
                if (!int.TryParse(value ?? "", NumberStyles.Integer, CultureInfo.InvariantCulture, out var signed))
                    return "<stop offset=\"" + offset + "\" stop-color=\"" + fallback + "\"/>";
                color = unchecked((uint)signed);
            }
            var alpha = (color >> 24) & 255;
            var rgb = "#" + ((color >> 16) & 255).ToString("x2", CultureInfo.InvariantCulture)
                + ((color >> 8) & 255).ToString("x2", CultureInfo.InvariantCulture) + (color & 255).ToString("x2", CultureInfo.InvariantCulture);
            var opacity = alpha == 255 ? "" : " stop-opacity=\"" + (alpha / 255.0).ToString("0.0000", CultureInfo.InvariantCulture) + "\"";
            return "<stop offset=\"" + offset + "\" stop-color=\"" + rgb + "\"" + opacity + "/>";
        }

        static int Number(string value, int fallback = 0)
        {
            return int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number) ? number : fallback;
        }

        static string Percent(double value) => value.ToString("0.0", CultureInfo.InvariantCulture);

        static string Color(ScreenElement element, long id)
        {
            if (!element.Members.TryGetValue(id, out var member)) return null;
            if (member.Kind == "color" && !string.IsNullOrEmpty(member.CanonicalName))
            {
                var canonical = member.CanonicalName;
                var mapping = new Dictionary<string, string>(StringComparer.Ordinal)
                {
                    ["BasicElement-Fill-Color"] = "fill", ["BasicElement-Frame-Color"] = "frame",
                    ["Font-Default-Color"] = "text", ["BasicElement-Alarm-Frame-Color"] = "alarm-frame",
                    ["BasicElement-Alarm-Fill-Color"] = "alarm-fill",
                };
                if (mapping.TryGetValue(canonical, out var role)) return "var(--" + role + ")";
                foreach (var prefix in new[] { "BasicElement-", "Font-", "Alarm-" })
                    if (canonical.StartsWith(prefix, StringComparison.Ordinal)) canonical = canonical.Substring(prefix.Length);
                if (canonical.EndsWith("-Color", StringComparison.Ordinal)) canonical = canonical.Substring(0, canonical.Length - 6);
                return "var(--" + string.Join("-", canonical.Split('-').Select(part => part.ToLowerInvariant())) + ")";
            }
            return Color(member.Kind == "color" ? member.Color : member.Value);
        }

        static string LiteralColor(string value)
        {
            if (!uint.TryParse(value ?? "", NumberStyles.Integer, CultureInfo.InvariantCulture, out var color))
            {
                if (!int.TryParse(value ?? "", NumberStyles.Integer, CultureInfo.InvariantCulture, out var signed)) return null;
                color = unchecked((uint)signed);
            }
            var rgb = color & 0xFFFFFF;
            return "#" + rgb.ToString("x6", CultureInfo.InvariantCulture);
        }

        static bool IsDark(string color)
        {
            if (string.IsNullOrEmpty(color) || color.Length != 7) return false;
            if (!int.TryParse(color.Substring(1, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var red)
                || !int.TryParse(color.Substring(3, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var green)
                || !int.TryParse(color.Substring(5, 2), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var blue)) return false;
            return 0.2126 * red + 0.7152 * green + 0.0722 * blue < 128;
        }

        static void Put(IDictionary<string, string> attrs, string key, string value)
        {
            if (!string.IsNullOrEmpty(value)) attrs[key] = value;
        }

        static string Color(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return null;
            if (!uint.TryParse(value.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var color))
            {
                if (!int.TryParse(value.Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out var signed)) return null;
                color = unchecked((uint)signed);
            }
            var alpha = (color >> 24) & 255;
            var rgb = "#" + ((color >> 16) & 255).ToString("x2", CultureInfo.InvariantCulture)
                + ((color >> 8) & 255).ToString("x2", CultureInfo.InvariantCulture)
                + (color & 255).ToString("x2", CultureInfo.InvariantCulture);
            return alpha == 255 ? rgb : rgb + alpha.ToString("x2", CultureInfo.InvariantCulture);
        }

        static string Tag(string name, IDictionary<string, string> attrs, string body)
        {
            var open = "<" + name + string.Concat(attrs.OrderBy(pair => pair.Key, StringComparer.Ordinal)
                .Select(pair => " " + pair.Key + "=\"" + Markup.Escape(pair.Value) + "\""));
            return body == null ? open + " />" : open + ">" + Markup.Escape(body) + "</" + name + ">";
        }
    }
}
