using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Xml.Linq;

namespace Cts.Visu
{
    internal static partial class SvgSketch
    {
        internal sealed class ElementSpec
        {
            internal string Type { get; set; }
            internal IDictionary<string, object> Params { get; } = new Dictionary<string, object>(StringComparer.Ordinal);
            internal Sketch.GradientSpec Gradient { get; set; }
        }

        internal static ElementSpec Parse(XElement element, IDictionary<string, string> theme)
        {
            var tag = element.Name.LocalName;
            var control = (string)element.Attribute("data-cds-type");
            ElementSpec spec;
            if (tag == "rect" && control == "button")
                spec = ParseButton(element, theme);
            else if (tag == "rect" && control == "lamp")
                spec = ParseLamp(element);
            else if (tag == "rect" && control == "image-switcher")
                spec = ParseImageSwitcher(element);
            else if (tag == "rect" && control == "combobox")
                spec = ParseCombobox(element);
            else if (tag == "rect" && control == "alarm-banner")
                spec = ParseAlarmBanner(element);
            else if (tag == "rect" && control == "frame")
                spec = ParseFrame(element);
            else if (tag == "text" && control == "textfield")
                spec = ParseTextfield(element, theme);
            else if (tag == "rect")
                spec = ParseRectangle(element, theme);
            else if (tag == "circle")
                spec = ParseCircle(element, theme);
            else if (tag == "ellipse")
                spec = ParseEllipse(element, theme);
            else if (tag == "line")
                spec = ParseLine(element, theme);
            else if (tag == "text")
                spec = ParseText(element, theme);
            else
                throw new VisuException("Unsupported SVG element: <" + tag + ">");
            return AddDialogActions(spec, element);
        }

        static ElementSpec ParseRectangle(XElement element, IDictionary<string, string> theme)
        {
            var spec = Geometry("rectangle", element, 100, 100);
            var radius = (string)element.Attribute("rx");
            if (radius != null)
            {
                spec.Params["shape"] = "rounded";
                spec.Params["corner_radius"] = Integer(Number(radius, 0));
            }
            else
            {
                spec.Params["shape"] = "rectangle";
            }
            AddShapePaint(spec, element, theme);
            AddShapeBindings(spec, element, theme);
            return spec;
        }

        static ElementSpec ParseCircle(XElement element, IDictionary<string, string> theme)
        {
            var radius = Number(element, "r", 0);
            var spec = new ElementSpec { Type = "rectangle" };
            spec.Params["x"] = Integer(Number(element, "cx", 0) - radius);
            spec.Params["y"] = Integer(Number(element, "cy", 0) - radius);
            spec.Params["width"] = Integer(2 * radius);
            spec.Params["height"] = Integer(2 * radius);
            spec.Params["shape"] = "ellipse";
            AddShapePaint(spec, element, theme);
            AddShapeBindings(spec, element, theme);
            return spec;
        }

        static ElementSpec ParseEllipse(XElement element, IDictionary<string, string> theme)
        {
            var radiusX = Number(element, "rx", 0);
            var radiusY = Number(element, "ry", 0);
            var spec = new ElementSpec { Type = "rectangle" };
            spec.Params["x"] = Integer(Number(element, "cx", 0) - radiusX);
            spec.Params["y"] = Integer(Number(element, "cy", 0) - radiusY);
            spec.Params["width"] = Integer(2 * radiusX);
            spec.Params["height"] = Integer(2 * radiusY);
            spec.Params["shape"] = "ellipse";
            AddShapePaint(spec, element, theme);
            AddShapeBindings(spec, element, theme);
            return spec;
        }

        static ElementSpec ParseLine(XElement element, IDictionary<string, string> theme)
        {
            var x1 = Integer(element, "x1", 0);
            var y1 = Integer(element, "y1", 0);
            var x2 = Integer(element, "x2", 100);
            var y2 = Integer(element, "y2", 100);
            var spec = new ElementSpec { Type = "line" };
            spec.Params["x"] = Math.Min(ParseInteger(x1, 0), ParseInteger(x2, 100)).ToString(CultureInfo.InvariantCulture);
            spec.Params["y"] = Math.Min(ParseInteger(y1, 0), ParseInteger(y2, 100)).ToString(CultureInfo.InvariantCulture);
            spec.Params["width"] = Math.Max(1, Math.Abs(ParseInteger(x2, 100) - ParseInteger(x1, 0))).ToString(CultureInfo.InvariantCulture);
            spec.Params["height"] = Math.Max(1, Math.Abs(ParseInteger(y2, 100) - ParseInteger(y1, 0))).ToString(CultureInfo.InvariantCulture);
            spec.Params["x1"] = x1;
            spec.Params["y1"] = y1;
            spec.Params["x2"] = x2;
            spec.Params["y2"] = y2;
            AddLinePaint(spec, element, theme);
            return spec;
        }

        static ElementSpec ParseText(XElement element, IDictionary<string, string> theme)
        {
            var spec = TextBox("label", element, out var fontSize);
            spec.Params["fill"] = "#00000000";
            spec.Params["frame"] = "#00000000";
            AddTextPaint(spec, element, theme, true);
            AddOptionalTextAttributes(spec, element, fontSize);
            return spec;
        }

        static ElementSpec ParseTextfield(XElement element, IDictionary<string, string> theme)
        {
            var spec = TextBox("textfield", element, out var fontSize);
            spec.Params["text_var"] = (string)element.Attribute("data-text-var") ?? "";
            spec.Params["font_size"] = fontSize.ToString(CultureInfo.InvariantCulture);
            spec.Params["font_name"] = (string)element.Attribute("font-family") ?? "Arial";
            AddTextPaint(spec, element, theme, false);
            return spec;
        }

        // A <text> as a box: its size from data-width/-height or the text,
        // y moved from the baseline to the top, text-anchor as alignment.
        static ElementSpec TextBox(string type, XElement element, out int fontSize)
        {
            var text = (element.Value ?? "").Trim();
            fontSize = FontSize(element);
            var width = Number(element, "data-width", TextWidth(text, fontSize));
            var height = Number(element, "data-height", TextHeight(fontSize));
            var anchor = (string)element.Attribute("text-anchor");
            var y = Number(element, "y", 0) - (anchor == "middle" ? height / 2 : fontSize);
            var spec = new ElementSpec { Type = type };
            SetGeometry(spec, Number(element, "x", 0), y, width, height);
            spec.Params["text"] = text;
            spec.Params["h_align"] = anchor == "middle" ? "HCENTER" : anchor == "end" ? "RIGHT" : "LEFT";
            spec.Params["v_align"] = anchor == "middle" ? "VCENTER" : "TOP";
            return spec;
        }

        static ElementSpec ParseButton(XElement element, IDictionary<string, string> theme)
        {
            var spec = Geometry("button", element, 100, 100);
            spec.Params["text"] = (string)element.Attribute("data-text") ?? "";
            AddOptional(spec.Params, "text_id", (string)element.Attribute("data-text-id"));
            var tap = ParseTap((string)element.Attribute("data-cds-tap"));
            AddOptional(spec.Params, "tap_var", tap);
            var actions = ParseActions((string)element.Attribute("data-cds-action"));
            AddOptional(spec.Params, "configured_inputs", actions.Item1);
            AddOptional(spec.Params, "input_actions", actions.Item2);
            AddControlPaint(spec, element, theme, true);
            return spec;
        }

        static ElementSpec ParseLamp(XElement element)
        {
            var spec = Geometry("lamp", element, 32, 32);
            var color = ((string)element.Attribute("data-color") ?? "green").Trim().ToLowerInvariant();
            var colorRole = color == "gray" || color == "grey"                           ? "Gray"
                            : new[] { "red", "green", "yellow", "blue" }.Contains(color) ? char.ToUpperInvariant(color[0]) + color.Substring(1)
                                                                                         : "Green";
            spec.Params["style_role"] = "Element-Lamp-Lamp1-" + colorRole;
            spec.Params["var"] = (string)element.Attribute("data-var") ?? (string)element.Attribute("data-text-var") ?? "";
            return spec;
        }

        static ElementSpec ParseImageSwitcher(XElement element)
        {
            var spec = Geometry("image-switcher", element, 70, 70);
            spec.Params["image_on"] = ((string)element.Attribute("data-image-on") ?? "").Trim();
            spec.Params["image_off"] = ((string)element.Attribute("data-image-off") ?? "").Trim();
            spec.Params["var"] = (string)element.Attribute("data-var") ?? "";
            return spec;
        }

        static ElementSpec ParseCombobox(XElement element)
        {
            var spec = Geometry("combobox", element, 120, 25);
            spec.Params["items"] = ((string)element.Attribute("data-items") ?? "").Trim();
            spec.Params["var"] = (string)element.Attribute("data-var") ?? "";
            return spec;
        }

        static ElementSpec ParseAlarmBanner(XElement element)
        {
            return Geometry("alarm-banner", element, 400, 25);
        }

        static ElementSpec ParseFrame(XElement element)
        {
            var spec = Geometry("frame", element, 100, 100);
            spec.Params["visu"] = ((string)element.Attribute("data-visu") ?? "").Trim();
            var parameters = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var attribute in element.Attributes().Where(
                         attribute => attribute.Name.LocalName.StartsWith("data-param-", StringComparison.Ordinal)))
            {
                parameters[attribute.Name.LocalName.Substring("data-param-".Length)] = attribute.Value;
            }
            spec.Params["params"] = parameters;
            return spec;
        }

        static ElementSpec Geometry(string type, XElement element, double defaultWidth, double defaultHeight)
        {
            var spec = new ElementSpec { Type = type };
            SetGeometry(spec, Number(element, "x", 0), Number(element, "y", 0), Number(element, "width", defaultWidth),
                        Number(element, "height", defaultHeight));
            return spec;
        }

        static void SetGeometry(ElementSpec spec, double x, double y, double width, double height)
        {
            spec.Params["x"] = Integer(x);
            spec.Params["y"] = Integer(y);
            spec.Params["width"] = Integer(width);
            spec.Params["height"] = Integer(height);
        }

        static void AddShapePaint(ElementSpec spec, XElement element, IDictionary<string, string> theme)
        {
            spec.Gradient = ParseGradient(element, theme);
            if (spec.Gradient == null)
            {
                var fill = Resolve(ApplyOpacity((string)element.Attribute("fill"), (string)element.Attribute("fill-opacity")), theme);
                if (fill != null) spec.Params["fill"] = fill;
            }
            var stroke = Resolve(ApplyOpacity((string)element.Attribute("stroke"), (string)element.Attribute("stroke-opacity")), theme);
            if (stroke != null) spec.Params["frame"] = stroke;
            if (spec.Gradient != null)
            {
                spec.Params["gradient"] = GradientDictionary(spec.Gradient);
            }
        }

        // A plain shape is the IDE's rectangle: it shows a text or a variable through it, takes its
        // colours from variables and answers a click as a button does.
        static void AddShapeBindings(ElementSpec spec, XElement element, IDictionary<string, string> theme)
        {
            var textVar = (string)element.Attribute("data-text-var");
            AddOptional(spec.Params, "text", (string)element.Attribute("data-text") ?? (string.IsNullOrEmpty(textVar) ? null : "%s"));
            AddOptional(spec.Params, "text_id", (string)element.Attribute("data-text-id"));
            AddOptional(spec.Params, "text_var", textVar);
            if (spec.Params.ContainsKey("text"))
            {
                var color = Resolve((string)element.Attribute("data-text-color"), theme);
                if (color != null) spec.Params["font_color_explicit"] = true;
                else if (theme.ContainsKey("text")) color = Resolve("var(--text)", theme);
                if (color != null) spec.Params["font_color"] = color;
                AddOptionalTextAttributes(spec, element, FontSize(element));
            }
            AddOptional(spec.Params, "color_var", (string)element.Attribute("data-color-var"));
            AddOptional(spec.Params, "alarm_fill", Resolve(ApplyOpacity((string)element.Attribute("data-on-fill"), null), theme));
            AddOptional(spec.Params, "alarm_frame", Resolve(ApplyOpacity((string)element.Attribute("data-on-stroke"), null), theme));
            AddOptional(spec.Params, "fill_var", (string)element.Attribute("data-fill-var"));
            AddOptional(spec.Params, "border_var", (string)element.Attribute("data-stroke-var"));
            var actions = ParseActions((string)element.Attribute("data-cds-action"));
            AddOptional(spec.Params, "configured_inputs", actions.Item1);
            AddOptional(spec.Params, "input_actions", actions.Item2);
        }

        static void AddLinePaint(ElementSpec spec, XElement element, IDictionary<string, string> theme)
        {
            var fill = Resolve(ApplyOpacity((string)element.Attribute("fill"), (string)element.Attribute("fill-opacity")), theme);
            if (fill != null) spec.Params["fill"] = fill;
            var stroke = Resolve(ApplyOpacity((string)element.Attribute("stroke"), (string)element.Attribute("stroke-opacity")), theme);
            if (stroke != null) spec.Params["frame"] = stroke;
        }

        static void AddControlPaint(ElementSpec spec, XElement element, IDictionary<string, string> theme, bool button)
        {
            var fill = Resolve(ApplyOpacity((string)element.Attribute("fill"), (string)element.Attribute("fill-opacity")), theme);
            if (fill != null) spec.Params["fill"] = fill;
            var stroke = Resolve(ApplyOpacity((string)element.Attribute("stroke"), (string)element.Attribute("stroke-opacity")), theme);
            if (stroke != null) spec.Params["frame"] = stroke;
            if (button)
            {
                var color = Resolve("var(--button-text)", theme);
                if (color != null) spec.Params["font_color"] = color;
            }
        }

        static void AddTextPaint(ElementSpec spec, XElement element, IDictionary<string, string> theme, bool label)
        {
            var fill = Resolve(ApplyOpacity((string)element.Attribute("fill"), (string)element.Attribute("fill-opacity")), theme);
            var explicitFill = fill != null && Stylesheet.WasSetByAuthor(element, "fill");
            if (!label && fill == null) fill = Resolve("var(--field-text)", theme);
            if (fill != null) spec.Params["font_color"] = fill;
            if (explicitFill) spec.Params["font_color_explicit"] = true;
        }

        static void AddOptionalTextAttributes(ElementSpec spec, XElement element, int fontSize)
        {
            if (element.Attribute("font-size") != null) spec.Params["font_size"] = fontSize.ToString(CultureInfo.InvariantCulture);
            AddOptional(spec.Params, "font_name", (string)element.Attribute("font-family"));
        }

        static IDictionary<string, object> GradientDictionary(Sketch.GradientSpec gradient)
        {
            return new Dictionary<string, object>(StringComparer.Ordinal) { ["color1"] = gradient.Color1,    ["color2"] = gradient.Color2,
                                                                            ["angle"] = gradient.Angle,      ["center_x"] = gradient.CenterX,
                                                                            ["center_y"] = gradient.CenterY, ["type"] = gradient.Type };
        }
    }
}
