using System;
using System.Collections.Generic;
using System.Globalization;
using Cts.Agent;

namespace Cts.Visu
{
    // Render the parsed element specs, keeping preview geometry and colours aligned with compilation.
    internal static class Preview
    {
        static readonly IDictionary<string, IDictionary<string, string>> NativeRoles =
            new Dictionary<string, IDictionary<string, string>>(StringComparer.Ordinal)
            {
                ["button"] = Roles("button.fill", "frame", "button.text"),
                ["textfield"] = Roles("field.fill", "field.frame", "field.text"),
                ["combobox"] = Roles("field.fill", "field.frame", "field.text"),
                ["alarm-banner"] = Roles("alarm.fill", "alarm.frame", "text.bright"),
                ["image-switcher"] = Roles("panel", "frame", "text.muted"),
                ["frame"] = Roles("panel", "frame", "text.muted"),
            };

        static readonly IDictionary<string, string> LampColors = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["Element-Lamp-Lamp1-Red"] = "#D64545", ["Element-Lamp-Lamp1-Green"] = "#4CAF50",
            ["Element-Lamp-Lamp1-Yellow"] = "#E0B020", ["Element-Lamp-Lamp1-Blue"] = "#3F7FD6",
            ["Element-Lamp-Lamp1-Gray"] = "#A8AEB6",
        };

        internal static string Render(Sketch sketch, int grid = 0)
        {
            var width = sketch.Width;
            var height = sketch.Height;
            var theme = sketch.Theme;
            var background = sketch.Background ?? Role(theme, "screen", "#F4F5F7");
            var parts = new List<string>
            {
                "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + N(width) + "\" height=\"" + N(height)
                    + "\" viewBox=\"0 0 " + N(width) + " " + N(height) + "\">",
                "<rect x=\"0\" y=\"0\" width=\"" + N(width) + "\" height=\"" + N(height) + "\" fill=\"" + Markup.Escape(background) + "\"/>",
            };
            var gradients = new List<string>();
            for (var i = 0; i < sketch.Elements.Count; i++)
            {
                if (sketch.Elements[i].Gradient == null) continue;
                gradients.Add(Gradient(sketch.Elements[i].Gradient, i));
            }
            if (gradients.Count > 0) parts.Add("<defs>" + string.Concat(gradients) + "</defs>");
            if (grid > 0)
            {
                var lines = new List<string>();
                for (var x = 0; x < width; x += grid)
                    lines.Add("<line x1=\"" + N(x) + "\" y1=\"0\" x2=\"" + N(x) + "\" y2=\"" + N(height) + "\"/>");
                for (var y = 0; y < height; y += grid)
                    lines.Add("<line x1=\"0\" y1=\"" + N(y) + "\" x2=\"" + N(width) + "\" y2=\"" + N(y) + "\"/>");
                parts.Add("<g stroke=\"" + (sketch.Scheme == "dark" ? "#FFFFFF" : "#000000")
                    + "\" stroke-opacity=\"0.06\" stroke-width=\"1\">" + string.Concat(lines) + "</g>");
            }
            for (var i = 0; i < sketch.Elements.Count; i++)
                parts.AddRange(RenderElement(sketch.Elements[i], theme, sketch.Scheme, i));
            parts.Add("</svg>");
            return string.Join("\n", parts) + "\n";
        }

        static IEnumerable<string> RenderElement(Sketch.Element element, IDictionary<string, string> theme, string scheme, int index)
        {
            var parameters = element.SpecParams;
            var x = (int)JsonMap.Number(parameters, "x");
            var y = (int)JsonMap.Number(parameters, "y");
            var width = (int)JsonMap.Number(parameters, "width");
            var height = (int)JsonMap.Number(parameters, "height");
            var colors = ElementTemplates.ResolvePreviewColors(VisuCatalog.Load(element.Type), parameters, theme, scheme);
            var fill = Rgba(colors.Item1);
            var frame = Rgba(colors.Item2);
            var font = Rgba(colors.Item3).Color;
            var native = NativeRoles.TryGetValue(element.Type, out var roles) ? roles : null;
            if (native != null)
            {
                if (fill.Color == null) fill = WithAlpha(Role(theme, native["fill"], Role(theme, "panel", "#DDDDDD")));
                if (frame.Color == null) frame = WithAlpha(Role(theme, native["frame"], Role(theme, "frame", "#808080")));
                if (element.Type == "button" || element.Type == "alarm-banner") font = Role(theme, native["text"], Role(theme, "text.bright", "#FFFFFF"));
            }
            var gradient = element.Gradient == null ? null : "url(#cts-grad-" + index.ToString(CultureInfo.InvariantCulture) + ")";
            var paint = gradient == null ? Paint(fill, frame) : PaintGradient(gradient, frame);

            if (element.Type == "line")
            {
                var stroke = frame.Color ?? fill.Color ?? "#000000";
                yield return "<line x1=\"" + N((int)JsonMap.Number(parameters, "x1", x)) + "\" y1=\"" + N((int)JsonMap.Number(parameters, "y1", y))
                    + "\" x2=\"" + N((int)JsonMap.Number(parameters, "x2", x + width)) + "\" y2=\"" + N((int)JsonMap.Number(parameters, "y2", y + height))
                    + "\" stroke=\"" + Markup.Escape(stroke) + "\" stroke-width=\"1\"/>";
                yield break;
            }
            if (element.Type == "rectangle")
            {
                var shape = JsonMap.Text(parameters, "shape", "rectangle").ToLowerInvariant();
                if (shape == "ellipse")
                    yield return "<ellipse cx=\"" + F(x + width / 2.0) + "\" cy=\"" + F(y + height / 2.0) + "\" rx=\""
                        + F(width / 2.0) + "\" ry=\"" + F(height / 2.0) + "\" " + paint + "/>";
                else
                    yield return "<rect x=\"" + N(x) + "\" y=\"" + N(y) + "\" width=\"" + N(width) + "\" height=\"" + N(height)
                        + "\" rx=\"" + N(shape == "rounded" ? (int)JsonMap.Number(parameters, "corner_radius") : 0) + "\" " + paint + "/>";
                if (JsonMap.Text(parameters, "text", "").Length > 0)
                    yield return TextNode(parameters, x, y, width, height, font, (int)JsonMap.Number(parameters, "font_size", 12), JsonMap.Text(parameters, "text", ""), "HCENTER", "VCENTER");
                yield break;
            }
            if (element.Type == "label")
            {
                if ((fill.Color != null && fill.Alpha > 0) || (frame.Color != null && frame.Alpha > 0))
                    yield return Box(x, y, width, height, paint);
                yield return TextNode(parameters, x, y, width, height, font, (int)JsonMap.Number(parameters, "font_size", 12), JsonMap.Text(parameters, "text", ""));
                yield break;
            }
            if (element.Type == "button")
            {
                yield return "<rect x=\"" + N(x) + "\" y=\"" + N(y) + "\" width=\"" + N(width) + "\" height=\"" + N(height)
                    + "\" rx=\"2\" " + paint + "/>";
                yield return TextNode(parameters, x, y, width, height, font, (int)JsonMap.Number(parameters, "font_size", 12), JsonMap.Text(parameters, "text", ""), "HCENTER", "VCENTER");
                yield break;
            }
            if (element.Type == "textfield")
            {
                yield return Box(x, y, width, height, paint);
                var text = JsonMap.Text(parameters, "text", "");
                if (text.Length == 0 && JsonMap.Text(parameters, "text_var", "").Length > 0) text = "%s";
                yield return TextNode(parameters, x, y, width, height, font, (int)JsonMap.Number(parameters, "font_size", 12), text, inset: 2);
                yield break;
            }
            if (element.Type == "lamp")
            {
                var style = JsonMap.Text(parameters, "style_role", "");
                var color = LampColors.TryGetValue(style, out var lampColor) ? lampColor : "#A8AEB6";
                yield return "<circle cx=\"" + F(x + width / 2.0) + "\" cy=\"" + F(y + height / 2.0) + "\" r=\""
                    + F(Math.Min(width, height) / 2.0) + "\" fill=\"" + color + "\" stroke=\""
                    + Markup.Escape(Role(theme, "frame", "#808080")) + "\" stroke-width=\"1\"/>";
                yield break;
            }
            yield return Box(x, y, width, height, paint);
            yield return TextNode(parameters, x, y, width, height, Role(theme, "text.muted", "#666666"), 11, element.Type, "HCENTER", "VCENTER");
        }

        static string Gradient(Sketch.GradientSpec gradient, int index)
        {
            var id = "cts-grad-" + index.ToString(CultureInfo.InvariantCulture);
            var first = GradientColor(gradient.Color1, "#000000");
            var second = GradientColor(gradient.Color2, "#FFFFFF");
            if (gradient.Type == "radial")
                return "<radialGradient id=\"" + id + "\" cx=\"" + N(gradient.CenterX) + "%\" cy=\"" + N(gradient.CenterY)
                    + "%\" r=\"50%\"><stop offset=\"0%\" stop-color=\"" + first + "\"/><stop offset=\"100%\" stop-color=\""
                    + second + "\"/></radialGradient>";
            var angle = gradient.Angle * Math.PI / 180.0;
            var dx = Math.Cos(angle) * 50.0;
            var dy = Math.Sin(angle) * 50.0;
            return "<linearGradient id=\"" + id + "\" x1=\"" + F(50 - dx) + "%\" y1=\"" + F(50 - dy) + "%\" x2=\""
                + F(50 + dx) + "%\" y2=\"" + F(50 + dy) + "%\"><stop offset=\"0%\" stop-color=\"" + first
                + "\"/><stop offset=\"100%\" stop-color=\"" + second + "\"/></linearGradient>";
        }

        static string TextNode(IDictionary<string, object> parameters, int x, int y, int width, int height, string color,
            int size, string content, string hAlign = null, string vAlign = null, int inset = 0)
        {
            hAlign = (hAlign ?? JsonMap.Text(parameters, "h_align", "LEFT")).ToUpperInvariant();
            vAlign = (vAlign ?? JsonMap.Text(parameters, "v_align", "TOP")).ToUpperInvariant();
            var tx = hAlign == "HCENTER" ? x + width / 2.0 : hAlign == "RIGHT" ? x + width - inset : x + inset;
            var anchor = hAlign == "HCENTER" ? "middle" : hAlign == "RIGHT" ? "end" : "start";
            var sizePart = (int)JsonMap.Number(parameters, "font_size", size);
            var ty = vAlign == "VCENTER" ? y + height / 2.0 + sizePart * 0.36 : vAlign == "BOTTOM" ? y + height - 2 : y + sizePart;
            var font = JsonMap.Text(parameters, "font_name", "Arial, Helvetica, sans-serif");
            if (font.IndexOf(",", StringComparison.Ordinal) < 0) font += ", Arial, Helvetica, sans-serif";
            return "<text x=\"" + F(tx) + "\" y=\"" + F(ty) + "\" font-family=\"" + Markup.Escape(font) + "\" font-size=\""
                + N(sizePart) + "\" fill=\"" + Markup.Escape(color ?? "#000000") + "\" text-anchor=\"" + anchor + "\">" + Markup.Escape(content) + "</text>";
        }

        static string Box(int x, int y, int width, int height, string paint)
        {
            return "<rect x=\"" + N(x) + "\" y=\"" + N(y) + "\" width=\"" + N(width) + "\" height=\"" + N(height) + "\" " + paint + "/>";
        }

        static string Paint((string Color, double Alpha) fill, (string Color, double Alpha) frame)
        {
            var parts = new List<string>();
            if (fill.Color != null && fill.Alpha > 0)
            {
                parts.Add("fill=\"" + fill.Color + "\"");
                if (fill.Alpha < 1) parts.Add("fill-opacity=\"" + fill.Alpha.ToString("0.000", CultureInfo.InvariantCulture) + "\"");
            }
            else parts.Add("fill=\"none\"");
            if (frame.Color != null && frame.Alpha > 0)
            {
                parts.Add("stroke=\"" + frame.Color + "\" stroke-width=\"1\"");
                if (frame.Alpha < 1) parts.Add("stroke-opacity=\"" + frame.Alpha.ToString("0.000", CultureInfo.InvariantCulture) + "\"");
            }
            return string.Join(" ", parts);
        }

        static string PaintGradient(string gradient, (string Color, double Alpha) frame)
        {
            var parts = new List<string> { "fill=\"" + gradient + "\"" };
            if (frame.Color != null && frame.Alpha > 0)
            {
                parts.Add("stroke=\"" + frame.Color + "\" stroke-width=\"1\"");
                if (frame.Alpha < 1) parts.Add("stroke-opacity=\"" + frame.Alpha.ToString("0.000", CultureInfo.InvariantCulture) + "\"");
            }
            return string.Join(" ", parts);
        }

        static (string Color, double Alpha) Rgba(string value)
        {
            if (string.IsNullOrWhiteSpace(value) || !uint.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var color))
                return (null, 0);
            var alpha = (color >> 24) & 255;
            return ("#" + ((color >> 16) & 255).ToString("X2", CultureInfo.InvariantCulture)
                + ((color >> 8) & 255).ToString("X2", CultureInfo.InvariantCulture) + (color & 255).ToString("X2", CultureInfo.InvariantCulture), alpha / 255.0);
        }

        static string GradientColor(string value, string fallback)
        {
            if (string.IsNullOrWhiteSpace(value)) return fallback;
            var text = value.Trim();
            if (text.StartsWith("#", StringComparison.Ordinal))
                return text.Length >= 7 ? text.Substring(0, 7).ToUpperInvariant() : fallback;
            return Rgba(text).Color ?? fallback;
        }

        static (string Color, double Alpha) WithAlpha(string color) => (color, 1.0);

        static IDictionary<string, string> Roles(string fill, string frame, string text)
        {
            return new Dictionary<string, string>(StringComparer.Ordinal) { ["fill"] = fill, ["frame"] = frame, ["text"] = text };
        }

        static string Role(IDictionary<string, string> theme, string name, string fallback)
        {
            if (theme != null && theme.TryGetValue(name, out var value) && !string.IsNullOrEmpty(value)) return value;
            var hyphen = name.Replace('.', '-');
            return theme != null && theme.TryGetValue(hyphen, out value) && !string.IsNullOrEmpty(value) ? value : fallback;
        }



        static string N(int value) => value.ToString(CultureInfo.InvariantCulture);
        static string F(double value) => value.ToString("0.0", CultureInfo.InvariantCulture);
    }
}
