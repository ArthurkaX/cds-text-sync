using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace Cts.Visu
{
    // The stable sketch model shared by lint, binding and later SVG consumers.
    internal sealed class Sketch
    {
        internal sealed class Element
        {
            internal string Type { get; set; }
            internal IDictionary<string, string> Params { get; } = new Dictionary<string, string>(StringComparer.Ordinal);
            internal IDictionary<string, object> SpecParams { get; } = new Dictionary<string, object>(StringComparer.Ordinal);
            internal XElement Source { get; set; }
            internal GradientSpec Gradient { get; set; }
        }

        internal sealed class GradientSpec
        {
            internal string Color1 { get; set; }
            internal string Color2 { get; set; }
            internal int Angle { get; set; }
            internal int CenterX { get; set; }
            internal int CenterY { get; set; }
            internal string Type { get; set; }
        }

        internal int Width { get; private set; }
        internal int Height { get; private set; }
        internal string Scheme { get; private set; }
        internal XDocument Document { get; private set; }
        internal IList<Element> Elements { get; } = new List<Element>();
        internal IDictionary<string, string> Theme { get; private set; }
        internal string Background { get; private set; }

        internal static Sketch Parse(string text, string projectDir = null, string background = null, string schemeOverride = null,
                                     string themeName = null)
        {
            if (string.IsNullOrWhiteSpace(text)) throw new VisuException("SVG file is empty");
            var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
            XDocument document;
            try
            {
                using (var reader = XmlReader.Create(new StringReader(text), settings)) document
                    = XDocument.Load(reader, LoadOptions.PreserveWhitespace);
            }
            catch (XmlException error)
            {
                throw new VisuException(ParseError(text, error));
            }
            var root = document.Root;
            if (root == null || root.Name.LocalName != "svg") throw new VisuException("document root must be <svg>");
            var sketch = new Sketch {
                Document = document,
                Width = Dimension(root.Attribute("width")?.Value, 800),
                Height = Dimension(root.Attribute("height")?.Value, 480),
                Scheme = ReadScheme(text, schemeOverride),
            };
            sketch.Theme = Themes.Palette(sketch.Scheme, themeName);
            foreach (var style in root.Descendants().Where(node => node.Name.LocalName == "style"))
            {
                foreach (Match block in Regex.Matches(style.Value, @":root\s*\{([^}]*)\}", RegexOptions.IgnoreCase))
                {
                    foreach (Match match in Regex.Matches(block.Groups[1].Value, @"--([a-zA-Z0-9_-]+)\s*:\s*([^;]+);"))
                    {
                        sketch.Theme[match.Groups[1].Value.Replace('-', '.')] = match.Groups[2].Value.Trim();
                    }
                }
            }
            sketch.Background = ResolveBackground(background, sketch.Theme);
            var sheet = Stylesheet.Load(projectDir);
            foreach (var element in root.Elements())
            {
                if (element.Name.LocalName == "defs") continue;
                if (!IsSketchElement(element))
                    throw new VisuException("Unsupported SVG element: <" + element.Name.LocalName
                                            + ">. Supported: circle, ellipse, line, rect, text");
                Stylesheet.ApplyClass(element, sheet);
                sketch.Elements.Add(ParseElement(element, sketch.Theme));
            }
            return sketch;
        }

        static string ParseError(string text, XmlException error)
        {
            var lines = (text ?? "").Split(new[] { "\r\n", "\n", "\r" }, StringSplitOptions.None);
            var message = "malformed SVG: " + error.Message;
            if (error.LineNumber <= 0 || error.LineNumber > lines.Length) return message;
            var source = lines[error.LineNumber - 1].Trim();
            message += Environment.NewLine + "  " + source;
            var comment = source.StartsWith("<!--", StringComparison.Ordinal) ? source.Substring(4) : source;
            comment = comment.EndsWith("-->", StringComparison.Ordinal) ? comment.Substring(0, comment.Length - 3) : comment;
            if (comment.Contains("--"))
                message
                    += Environment.NewLine
                       + "XML reserves \"--\" for the comment delimiter, so it cannot appear inside a comment. Rule a separator off with \"====\".";
            return message;
        }

        internal static string ReadScheme(string text, string schemeOverride = null)
        {
            if (schemeOverride != null) return StyleRoles.NormalizeScheme(schemeOverride);
            try
            {
                var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
                using (var reader = XmlReader.Create(new StringReader(text ?? ""), settings))
                {
                    var root = XDocument.Load(reader).Root;
                    return StyleRoles.NormalizeScheme((string)root?.Attribute("data-cds-scheme"));
                }
            }
            catch
            {
                return "light";
            }
        }

        static string ResolveBackground(string background, IDictionary<string, string> theme)
        {
            var mode = (background ?? "auto").Trim().ToLowerInvariant();
            if (mode.StartsWith("#", StringComparison.Ordinal)) return background.Trim();
            var key = mode == "style" ? "surface" : "screen";
            if (theme.TryGetValue(key, out var color)) return color;
            if (theme.TryGetValue("background", out color)) return color;
            return null;
        }

        static bool IsSketchElement(XElement element)
        {
            var tag = element.Name.LocalName;
            return tag == "rect" || tag == "circle" || tag == "ellipse" || tag == "line" || tag == "text";
        }

        static int Dimension(string value, int fallback)
        {
            if (int.TryParse(value ?? "", NumberStyles.Integer, CultureInfo.InvariantCulture, out var result)) return result;
            return fallback;
        }

        static Element ParseElement(XElement node, IDictionary<string, string> theme)
        {
            var spec = SvgSketch.Parse(node, theme);
            var result = new Element { Type = spec.Type, Source = node, Gradient = spec.Gradient };
            foreach (var parameter in spec.Params)
            {
                result.SpecParams[parameter.Key] = parameter.Value;
                if (parameter.Value is string textValue) result.Params[parameter.Key] = textValue;
            }
            result.Params["text"] = result.Params.TryGetValue("text", out var text) ? text : "";
            result.Params["text_var"] = result.Params.TryGetValue("text_var", out var textVar) ? textVar : "";
            result.Params["var"] = result.Params.TryGetValue("var", out var variable) ? variable : "";
            result.Params["tap_var"] = result.Params.TryGetValue("tap_var", out var tap) ? tap : "";
            result.Params["action"] = (string)node.Attribute("data-cds-action") ?? "";
            result.Params["font_size"] = result.Params.TryGetValue("font_size", out var fontSize) ? fontSize : "12";
            result.Params["text_id"] = result.Params.TryGetValue("text_id", out var textId) ? textId : "";
            result.Params["items"] = result.Params.TryGetValue("items", out var items) ? items : "";
            result.Params["image_on"] = result.Params.TryGetValue("image_on", out var imageOn) ? imageOn : "";
            result.Params["image_off"] = result.Params.TryGetValue("image_off", out var imageOff) ? imageOff : "";
            result.Params["visu"] = result.Params.TryGetValue("visu", out var visu) ? visu : "";
            return result;
        }

        internal static int TextWidth(string text, int size)
        {
            const string narrow = " .,:;'`|!ijlI";
            const string thin = "ft()[]{}/\\-\"J";
            const string wide = "ABCDEFGHKLNOPQRSTUVXYZ&$#";
            const string widest = "mwMW%@";
            var em = text.Sum(character => narrow.Contains(character)   ? 280
                                           : thin.Contains(character)   ? 333
                                           : wide.Contains(character)   ? 667
                                           : widest.Contains(character) ? 833
                                                                        : 556);
            var raw = Math.Max(20, (int)(em * size / 1000.0) + 8);
            return (raw + 3) / 4 * 4;
        }
    }
}
