using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Cts.Agent;

namespace Cts.Visu
{
    // Render CODESYS' captured element fragments as text. Re-serializing these
    // fragments through an XML writer changes details the IDE imports verbatim.
    internal static partial class ElementTemplates
    {
        const string Prefix = "Cts.Visu.Templates.";
        const string ListStart = "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\">";
        const string MemberType = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}";

        internal static (string Xml, IDictionary<string, object> Geometry, string Identifier) Append(
            string xml, IDictionary<string, object> catalog, IDictionary<string, object> parameters, string templateOverride = null,
            IDictionary<string, string> themeColors = null, string scheme = "light")
        {
            var root = ScreenXml.Parse(xml);
            var size = ScreenXml.Size(root);
            var meta = root.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "MetaObject");
            var ownerGuid = meta?.Elements("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "Guid")?.Value.Trim()
                ?? "11111111-1111-1111-1111-111111111111";
            var nextId = IntMember(root, "LastUsedIdForIdentifier") + 1;
            var uniqueId = IntMember(root, "UniqueIdGenerator") + 1;
            var identifier = "GenElemInst_" + nextId.ToString(CultureInfo.InvariantCulture);
            var geometry = Geometry(catalog, parameters);
            var x = (int)geometry["x"];
            var y = (int)geometry["y"];
            var width = (int)geometry["width"];
            var height = (int)geometry["height"];
            if (x < 0 || y < 0 || width <= 0 || height <= 0 || x + width > size.Width || y + height > size.Height)
                throw new VisuException("Element bounds " + x + "," + y + " " + width + "x" + height
                    + " outside screen " + size.Width + "x" + size.Height);
            var templateName = Convert.ToString(JsonMap.Value(catalog, "golden_template"), CultureInfo.InvariantCulture);
            var template = templateOverride ?? Resource(templateName);
            var visualId = ScreenXml.Elements(root).Count;
            var fragment = template.Replace("@@IDENTIFIER@@", Markup.Escape(identifier))
                .Replace("@@IDENTIFICATION_GUID@@", nextId.ToString("x8", CultureInfo.InvariantCulture) + "-0000-4000-8000-000000000000")
                .Replace("@@OWNING_GUID@@", ownerGuid)
                .Replace("@@VISUAL_ELEMENT_ID@@", visualId.ToString(CultureInfo.InvariantCulture))
                .Replace("@@X@@", x.ToString(CultureInfo.InvariantCulture))
                .Replace("@@Y@@", y.ToString(CultureInfo.InvariantCulture))
                .Replace("@@WIDTH@@", width.ToString(CultureInfo.InvariantCulture))
                .Replace("@@HEIGHT@@", height.ToString(CultureInfo.InvariantCulture))
                .Replace("@@CENTER_X@@", (x + width / 2).ToString(CultureInfo.InvariantCulture))
                .Replace("@@CENTER_Y@@", (y + height / 2).ToString(CultureInfo.InvariantCulture));
            var shape = Value(parameters, "shape", "rectangle");
            var variants = JsonMap.Value(catalog, "shape_variants") as IDictionary<string, object>;
            if (variants != null && variants.TryGetValue(shape, out var shapeValue)) fragment = fragment.Replace("@@SHAPE@@", Markup.Escape(Convert.ToString(shapeValue)));
            foreach (var pair in parameters)
            {
                var definition = Parameter(catalog, pair.Key);
                if (definition == null || pair.Key == "x" || pair.Key == "y" || pair.Key == "width" || pair.Key == "height") continue;
                var id = JsonMap.Value(definition, "member_id");
                if (id == null) continue;
                var kind = Convert.ToString(JsonMap.Value(definition, "kind"), CultureInfo.InvariantCulture);
                if (kind == "color")
                {
                    if (!Themeable(catalog, pair.Key))
                        fragment = ReplaceColorStruct(fragment, Convert.ToString(id), ResolveColor(pair.Value, themeColors, null));
                }
                else if (kind != "gradient" && kind != "shape")
                {
                    var value = Convert.ToString(pair.Value, CultureInfo.InvariantCulture);
                    fragment = Equals(JsonMap.Value(definition, "optional"), true)
                        ? SetOrAddMember(fragment, Convert.ToString(id), kind, value)
                        : SetMember(fragment, Convert.ToString(id), value);
                }
            }
            // The IDE clears this flag on an element that shows a text variable; set, it shows none online.
            if (Value(parameters, "text_var", "").Length > 0) fragment = SetMember(fragment, "2597686782", "False");
            fragment = Fill(fragment, "TEXT", Value(parameters, "text", ""));
            fragment = Fill(fragment, "TEXT_ID", Value(parameters, "text_id", ""));
            fragment = Fill(fragment, "TEXT_VAR", Value(parameters, "text_var", ""));
            fragment = Fill(fragment, "TAP_VAR", Value(parameters, "tap_var", ""));
            fragment = Fill(fragment, "FONT_NAME", Value(parameters, "font_name", "Arial"));
            fragment = Fill(fragment, "FONT_SIZE", Value(parameters, "font_size", "12"));
            fragment = Fill(fragment, "H_ALIGN", Value(parameters, "h_align", "HCENTER"));
            fragment = Fill(fragment, "V_ALIGN", Value(parameters, "v_align", "VCENTER"));
            fragment = fragment.Replace("@@CONFIGURED_COMPLEX_INPUTS@@", RenderConfiguredInputs(parameters));
            fragment = fragment.Replace("@@VISUAL_ELEMENT_INPUT_ACTIONS@@", RenderInputActions(parameters));
            fragment = fragment.Replace("@@PARAM_MEMBERS@@", RenderFrameParameters(catalog, parameters));
            var colors = ResolvePreviewColors(catalog, parameters, themeColors, scheme);
            fragment = ResolveColorPlaceholder(fragment, catalog, "fill", "FILL_COLOR_UINT", colors.Item1);
            fragment = ResolveColorPlaceholder(fragment, catalog, "frame", "FRAME_COLOR_UINT", colors.Item2);
            if (colors.Item1 != null) fragment = ReplaceColorStruct(fragment, ThemeableId(catalog, "fill"), colors.Item1);
            if (colors.Item2 != null) fragment = ReplaceColorStruct(fragment, ThemeableId(catalog, "frame"), colors.Item2);
            fragment = fragment.Replace("@@FONT_COLOR_UINT@@", colors.Item3);
            var fontSigned = unchecked((int)uint.Parse(colors.Item3, CultureInfo.InvariantCulture)).ToString(CultureInfo.InvariantCulture);
            fragment = fragment.Replace("@@FONT_COLOR_SIGNED@@", fontSigned)
                .Replace("@@FONT_COLOR_STRUCT@@", FontColorStruct(fontSigned));
            if (Boolean(parameters, "font_color_explicit") || scheme == "dark") fragment = UnlinkFontColor(fragment, fontSigned);
            fragment = fragment.Replace("@@GRADIENT_MEMBERS@@", RenderGradient(parameters, themeColors));
            var templateParameters = JsonMap.Value(catalog, "template_params") as IDictionary<string, object>;
            if (templateParameters != null)
            {
                foreach (var templateParameter in templateParameters)
                {
                    var definition = templateParameter.Value as IDictionary<string, object>;
                    var parameterName = Convert.ToString(JsonMap.Value(definition, "param"), CultureInfo.InvariantCulture)
                        ?? templateParameter.Key.ToLowerInvariant();
                    var value = parameters.TryGetValue(parameterName, out var parameterValue)
                        ? Convert.ToString(parameterValue, CultureInfo.InvariantCulture)
                        : Convert.ToString(JsonMap.Value(definition, "default"), CultureInfo.InvariantCulture) ?? "";
                    fragment = fragment.Replace("@@" + templateParameter.Key + "@@", Markup.Escape(value));
                }
            }
            xml = OpenEmptyList(xml, "VisualElementList");
            var marker = xml.IndexOf(ListStart, StringComparison.Ordinal);
            if (marker < 0) throw new VisuException("Screen file has no VisualElementList");
            var close = ClosingList(xml, marker + ListStart.Length);
            xml = xml.Insert(close, fragment);
            xml = ReplaceMember(xml, "LastUsedIdForIdentifier", nextId.ToString(CultureInfo.InvariantCulture), "int");
            xml = ReplaceMember(xml, "UniqueIdGenerator", uniqueId.ToString(CultureInfo.InvariantCulture), "string");
            return (xml, geometry, identifier);
        }

        static IDictionary<string, object> Geometry(IDictionary<string, object> catalog, IDictionary<string, object> parameters)
        {
            var roles = new Dictionary<string, string>(StringComparer.Ordinal)
            {
                ["x"] = "x",
                ["y"] = "y",
                ["width"] = "width",
                ["height"] = "height",
            };
            var result = new Dictionary<string, object>(StringComparer.Ordinal);
            var members = (IList<object>)catalog["base_members"];
            foreach (var role in roles)
            {
                var item = members.Cast<IDictionary<string, object>>().FirstOrDefault(member => Equals(JsonMap.Value(member, "role"), role.Key));
                var fallback = item == null ? (role.Key == "width" || role.Key == "height" ? 100 : 0)
                    : int.Parse(Convert.ToString(JsonMap.Value(item, "value"), CultureInfo.InvariantCulture), CultureInfo.InvariantCulture);
                result[role.Value] = parameters.TryGetValue(role.Key, out var value)
                    ? Convert.ToInt32(value, CultureInfo.InvariantCulture) : fallback;
            }
            result["center_x"] = (int)result["x"] + (int)result["width"] / 2;
            result["center_y"] = (int)result["y"] + (int)result["height"] / 2;
            return result;
        }

        static IDictionary<string, object> Parameter(IDictionary<string, object> catalog, string name)
        {
            if (catalog["params"] is IDictionary<string, object> parameters)
            {
                if (parameters.TryGetValue(name, out var value)) return value as IDictionary<string, object>;
                return JsonMap.Value(catalog, "optional_bindings") is IDictionary<string, object> bindings
                    && bindings.TryGetValue(name, out var binding) ? binding as IDictionary<string, object> : null;
            }
            if (catalog["params"] is IList<object> list)
                return list.Cast<IDictionary<string, object>>().FirstOrDefault(parameter => Equals(JsonMap.Value(parameter, "name"), name));
            return null;
        }

        internal static Tuple<string, string, string> ResolvePreviewColors(IDictionary<string, object> catalog, IDictionary<string, object> parameters,
                                                           IDictionary<string, string> themeColors, string scheme)
        {
            var type = Convert.ToString(JsonMap.Value(catalog, "type"), CultureInfo.InvariantCulture);
            var native = type == "button" || type == "textfield";
            var font = ResolveColor(parameters.TryGetValue("font_color", out var fontExpr) ? fontExpr : null, themeColors, "4294967295");
            var themeable = JsonMap.Value(catalog, "themeable_colors") as IDictionary<string, object>;
            var fill = ResolveThemeable(themeable, "fill", parameters, themeColors, native, scheme);
            var frame = ResolveThemeable(themeable, "frame", parameters, themeColors, native, scheme);
            return Tuple.Create(fill, frame, font);
        }

        static string ResolveThemeable(IDictionary<string, object> colors, string key, IDictionary<string, object> parameters,
                                       IDictionary<string, string> themeColors, bool native, string scheme)
        {
            if (colors == null || !colors.TryGetValue(key, out var item)) return null;
            var definition = item as IDictionary<string, object>;
            if (parameters.TryGetValue(key, out var expression))
                return ResolveColor(expression, themeColors, null);
            var role = Convert.ToString(JsonMap.Value(definition, "role"), CultureInfo.InvariantCulture) ?? "";
            var normalizedRole = role.Replace('-', '.');
            var curated = StyleRoles.Curated.Contains(normalizedRole)
                || scheme == "dark" && StyleRoles.Dark.ContainsKey(normalizedRole);
            var deferred = native && !curated;
            if (deferred) return null;
            var fallback = Convert.ToString(JsonMap.Value(definition, "default_signed"), CultureInfo.InvariantCulture) ?? "-1";
            if (themeColors != null && themeColors.TryGetValue(role.Replace('-', '.'), out var color))
                return ResolveColor(color, themeColors, fallback);
            if (themeColors != null && themeColors.TryGetValue(role, out color)) return ResolveColor(color, themeColors, fallback);
            return unchecked((uint)int.Parse(fallback, CultureInfo.InvariantCulture)).ToString(CultureInfo.InvariantCulture);
        }

        static string ResolveColor(object expression, IDictionary<string, string> themeColors, string fallback)
        {
            if (expression == null) return fallback;
            var value = Convert.ToString(expression, CultureInfo.InvariantCulture) ?? "";
            if (value.StartsWith("var(--", StringComparison.Ordinal) && value.EndsWith(")", StringComparison.Ordinal))
            {
                var role = value.Substring(6, value.Length - 7).Replace('-', '.');
                if (themeColors != null && themeColors.TryGetValue(role, out var resolved)) value = resolved;
            }
            return ParseColor(value);
        }

        static string ResolveColorPlaceholder(string fragment, IDictionary<string, object> catalog, string key,
                                              string placeholder, string color)
        {
            var token = "@@" + placeholder + "@@";
            if (color != null) return fragment.Replace(token, color);
            if (fragment.IndexOf(token, StringComparison.Ordinal) < 0) return fragment;
            var colors = JsonMap.Value(catalog, "themeable_colors") as IDictionary<string, object>;
            if (colors != null && colors.TryGetValue(key, out var definition))
            {
                var id = Convert.ToString(JsonMap.Value(definition as IDictionary<string, object>, "member_id"), CultureInfo.InvariantCulture);
                var pattern = @"(?m)^[ \t]*<Single Type=""" + Regex.Escape(MemberType) + @""" Method=""IArchivable"">\r?\n[ \t]*<Single Name=""Id"" Type=""long"">"
                    + Regex.Escape(id) + @"</Single>\r?\n[ \t]*<Single Name=""Value"" Type=""uint"">" + Regex.Escape(token)
                    + @"</Single>\r?\n[ \t]*</Single>\r?\n?";
                return Regex.Replace(fragment, pattern, "", RegexOptions.None, TimeSpan.FromSeconds(1));
            }
            return fragment.Replace(token, "4294967295");
        }

        static bool Themeable(IDictionary<string, object> catalog, string key)
        {
            return JsonMap.Value(catalog, "themeable_colors") is IDictionary<string, object> colors && colors.ContainsKey(key);
        }

        static string ThemeableId(IDictionary<string, object> catalog, string key)
        {
            var colors = JsonMap.Value(catalog, "themeable_colors") as IDictionary<string, object>;
            if (colors == null || !colors.TryGetValue(key, out var item)) return null;
            return Convert.ToString(JsonMap.Value(item as IDictionary<string, object>, "member_id"), CultureInfo.InvariantCulture);
        }

        // A colour member written as a named colour struct becomes a plain colour value.
        static string ReplaceColorStruct(string fragment, string id, string color)
        {
            if (id == null) return fragment;
            var pattern = "(^[ \\t]*)<Single Type=\"" + Regex.Escape(MemberType) + "\" Method=\"IArchivable\">\\r?\\n"
                + "[ \\t]*<Single Name=\"Id\" Type=\"long\">" + Regex.Escape(id) + "</Single>\\r?\\n"
                + "[ \\t]*<List Name=\"Value\" Type=\"System\\.Collections\\.ArrayList\">\\r?\\n"
                + "[ \\t]*<Single Type=\"\\{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216\\}\" Method=\"IArchivable\">\\r?\\n"
                + "[ \\t]*<Single Name=\"Color\" Type=\"int\">-?\\d+</Single>\\r?\\n"
                + "[ \\t]*<Single Name=\"CanonicalName\" Type=\"string\">[^<]*</Single>\\r?\\n"
                + "[ \\t]*</Single>\\r?\\n[ \\t]*</List>\\r?\\n[ \\t]*</Single>";
            return Regex.Replace(fragment, pattern, match =>
            {
                var indent = match.Groups[1].Value;
                return indent + "<Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                    + indent + "  <Single Name=\"Id\" Type=\"long\">" + id + "</Single>\n"
                    + indent + "  <Single Name=\"Value\" Type=\"uint\">" + color + "</Single>\n"
                    + indent + "</Single>";
            }, RegexOptions.Multiline, TimeSpan.FromSeconds(1));
        }

        static string FontColorStruct(string color)
        {
            return "                <Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                + "                  <Single Name=\"Id\" Type=\"long\">663104332</Single>\n"
                + "                  <List Name=\"Value\" Type=\"System.Collections.ArrayList\">\n"
                + "                    <Single Type=\"{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}\" Method=\"IArchivable\">\n"
                + "                      <Single Name=\"Color\" Type=\"int\">" + color + "</Single>\n"
                + "                      <Single Name=\"CanonicalName\" Type=\"string\">Font-Default-Color</Single>\n"
                + "                    </Single>\n"
                + "                  </List>\n"
                + "                </Single>\n";
        }

        static string UnlinkFontColor(string fragment, string color)
        {
            fragment = Regex.Replace(fragment, "(<Single Name=\"ExplicitColor\" Type=\"int\">)-?\\d+(</Single>)",
                match => match.Groups[1].Value + color + match.Groups[2].Value);
            const string named = @"<Single Name=""NamedColor"" Type=""{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}"" Method=""IArchivable"">\s*<Single Name=""Color"" Type=""int"">-?\d+</Single>\s*<Single Name=""CanonicalName"" Type=""string"">[^<]*</Single>\s*</Single>";
            return Regex.Replace(fragment, named, "<Null Name=\"NamedColor\" />", RegexOptions.None, TimeSpan.FromSeconds(1));
        }

        static bool Boolean(IDictionary<string, object> parameters, string key)
        {
            return parameters.TryGetValue(key, out var value) && (value is bool boolean ? boolean : Convert.ToString(value) == "True");
        }

        static string RenderGradient(IDictionary<string, object> parameters, IDictionary<string, string> themeColors)
        {
            if (!parameters.TryGetValue("gradient", out var value) || !(value is IDictionary<string, object> gradient)) return "";
            var color1 = ResolveColor(gradient.TryGetValue("color1", out var first) ? first : null, themeColors, "4278190080");
            var color2 = ResolveColor(gradient.TryGetValue("color2", out var second) ? second : null, themeColors, "4294967295");
            var angle = Number(gradient, "angle", 0);
            var centerX = Number(gradient, "center_x", 50);
            var centerY = Number(gradient, "center_y", 50);
            var kind = Value(gradient, "type", "linear");
            var type = kind == "radial" ? 1 : kind == "axial" ? 2 : 0;
            var alpha = ((uint.Parse(color1, CultureInfo.InvariantCulture) >> 24) & 0xff) << 24;
            return "                <Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                + "                  <Single Name=\"Id\" Type=\"long\">1375557818</Single>\n"
                + "                  <Single Name=\"Value\" Type=\"bool\">True</Single>\n"
                + "                </Single>\n"
                + "                <Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                + "                  <Single Name=\"Id\" Type=\"long\">494542316</Single>\n"
                + "                  <List Name=\"Value\" Type=\"System.Collections.ArrayList\">\n"
                + "                    <Single Type=\"uint\">" + color1 + "</Single>\n"
                + "                    <Single Type=\"uint\">" + color2 + "</Single>\n"
                + "                    <Single Type=\"int\">" + angle + "</Single>\n"
                + "                    <Single Type=\"int\">" + centerX + "</Single>\n"
                + "                    <Single Type=\"int\">" + centerY + "</Single>\n"
                + "                    <Single Type=\"int\">" + type + "</Single>\n"
                + "                    <Single Type=\"int\">0</Single>\n"
                + "                    <Single Type=\"int\">0</Single>\n"
                + "                    <Single Type=\"uint\">" + alpha.ToString(CultureInfo.InvariantCulture) + "</Single>\n"
                + "                  </List>\n"
                + "                </Single>\n";
        }

        static int Number(IDictionary<string, object> values, string key, int fallback)
        {
            return values.TryGetValue(key, out var value) && int.TryParse(Convert.ToString(value, CultureInfo.InvariantCulture),
                NumberStyles.Integer, CultureInfo.InvariantCulture, out var parsed) ? parsed : fallback;
        }

        static string RenderFrameParameters(IDictionary<string, object> catalog, IDictionary<string, object> parameters)
        {
            if (!(catalog["params"] is IList<object> definitions)) return "";
            var provided = parameters.TryGetValue("params", out var input) ? input as IDictionary<string, object> : null;
            if (provided == null && input is IDictionary<string, string> strings)
                provided = strings.ToDictionary(pair => pair.Key, pair => (object)pair.Value, StringComparer.Ordinal);
            if (provided == null) return "";
            var output = new StringBuilder();
            foreach (IDictionary<string, object> definition in definitions)
            {
                var name = Convert.ToString(JsonMap.Value(definition, "name"), CultureInfo.InvariantCulture);
                var value = provided.TryGetValue(name, out var explicitValue) ? explicitValue : JsonMap.Value(definition, "default");
                var text = Convert.ToString(value, CultureInfo.InvariantCulture) ?? "";
                if (text.Length == 0) continue;
                output.Append("                <Single Type=\"").Append(MemberType).Append("\" Method=\"IArchivable\">\n")
                    .Append("                 <Single Name=\"Id\" Type=\"long\">").Append(JsonMap.Value(definition, "member_id")).Append("</Single>\n")
                    .Append("                 <Single Name=\"Value\" Type=\"string\">").Append(Markup.Escape(text)).Append("</Single>\n")
                    .Append("                </Single>");
                output.Append('\n');
            }
            return output.ToString().TrimEnd('\n');
        }

        static int IntMember(XElement root, string name)
        {
            var text = root.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == name)?.Value;
            return int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ? value : 0;
        }

        static string Resource(string file)
        {
            using (var stream = typeof(ElementTemplates).Assembly.GetManifestResourceStream(Prefix + file))
            {
                if (stream == null) throw new VisuException("Missing embedded element template " + file);
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        static string Fill(string fragment, string key, string value)
        {
            return fragment.Replace("@@" + key + "@@", Markup.Escape(value));
        }

        static string Value(IDictionary<string, object> values, string key, string fallback)
        {
            return values.TryGetValue(key, out var value) ? Convert.ToString(value, CultureInfo.InvariantCulture) : fallback;
        }

        static string ParseColor(string input)
        {
            var text = (input ?? "").Trim();
            var raw = text;
            var prefixed = false;
            if (raw.StartsWith("#", StringComparison.Ordinal)) raw = raw.Substring(1);
            else if (raw.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            {
                raw = raw.Substring(2);
                prefixed = true;
            }
            else prefixed = false;
            var isHex = prefixed || text.StartsWith("#", StringComparison.Ordinal) || raw.Length == 6 || raw.Length == 8;
            uint color;
            if (isHex)
            {
                if (!uint.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out color))
                    throw new VisuException("Invalid color value: " + input);
                if (raw.Length <= 6) color |= 0xff000000;
            }
            else if (long.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out var number))
                color = unchecked((uint)number);
            else throw new VisuException("Invalid color value: " + input);
            return color.ToString(CultureInfo.InvariantCulture);
        }
    }
}
