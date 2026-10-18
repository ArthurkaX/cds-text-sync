using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;
using Xunit;
using Cts.Visu;

namespace Cts.Agent.Tests
{
    public class VisuThemesTests
    {
        static readonly (string Text, string Surface)[] TextSurfaces = {
            ("text", "screen"),
            ("text", "panel"),
            ("text", "card"),
            ("text.muted", "panel"),
            ("text.muted", "card"),
            ("panel.header.text", "panel.header"),
            ("custom.text", "custom.fill"),
            ("field.text", "field.fill"),
            ("button.text", "button.fill"),
        };

        public static IEnumerable<object[]> ContrastCases()
        {
            foreach (var scheme in new[] { "light", "dark" })
            {
                foreach (var pair in TextSurfaces)
                {
                    yield return new object[] { scheme, pair.Text, pair.Surface };
                }
            }
        }

        [Theory]
        [MemberData(nameof(ContrastCases))]
        public void Text_roles_meet_wcag_aa_against_their_surfaces(string scheme, string textRole, string surfaceRole)
        {
            var palette = StyleRoles.Palette(scheme);
            Assert.True(Contrast(palette[textRole], palette[surfaceRole]) >= 4.5,
                scheme + " " + textRole + " on " + surfaceRole);
        }

        [Theory]
        [InlineData("light")]
        [InlineData("dark")]
        public void Textfield_fill_member_is_encoded_once_with_the_scheme_palette(string scheme)
        {
            var screen = "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"SizeX\" Type=\"int\">800</Single>"
                + "<Single Name=\"SizeY\" Type=\"int\">480</Single>"
                + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\"></List></Single>";
            var parameters = new Dictionary<string, object> {
                ["x"] = "20", ["y"] = "20", ["width"] = "120", ["height"] = "24",
                ["text"] = "%.1f", ["text_var"] = "PLC.speed",
            };
            var catalog = VisuCatalog.Load("textfield");
            var colors = (IDictionary<string, object>)catalog["themeable_colors"];
            var fill = (IDictionary<string, object>)colors["fill"];
            var memberId = Convert.ToString(fill["member_id"]);
            var output = ElementTemplates.Append(screen, catalog, parameters, null, Themes.Palette(scheme, null), scheme).Xml;
            var marker = "<Single Name=\"Id\" Type=\"long\">" + memberId + "</Single>";
            Assert.Equal(1, Count(output, marker));
            if (scheme == "dark")
            {
                Assert.Contains("<Single Name=\"Value\" Type=\"uint\">", output.Substring(output.IndexOf(marker, StringComparison.Ordinal)));
                Assert.DoesNotContain("Element-Fill-Color", output);
            }
            else
            {
                Assert.Contains("Element-Fill-Color", output);
            }
        }

        [Theory]
        [InlineData("light", "button")]
        [InlineData("dark", "button")]
        [InlineData("light", "textfield")]
        [InlineData("dark", "textfield")]
        public void Native_control_font_color_link_follows_the_scheme(string scheme, string type)
        {
            var screen = "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"SizeX\" Type=\"int\">800</Single>"
                + "<Single Name=\"SizeY\" Type=\"int\">480</Single>"
                + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\"></List></Single>";
            var parameters = new Dictionary<string, object> {
                ["x"] = "20", ["y"] = "20", ["width"] = "120", ["height"] = "30",
                ["text"] = "Start", ["text_var"] = "PLC.speed",
            };
            var output = ElementTemplates.Append(screen, VisuCatalog.Load(type), parameters, null,
                Themes.Palette(scheme, null), scheme).Xml;
            var descriptor = XDocument.Parse(output).Descendants("Single").First(node =>
                node.Elements("Single").Any(child => (string)child.Attribute("Name") == "Id"
                    && child.Value == "3729828405")).ToString();
            if (scheme == "dark")
            {
                Assert.Contains("<Null Name=\"NamedColor\" />", descriptor);
                Assert.DoesNotContain("Font-Default-Color", descriptor);
            }
            else
            {
                Assert.Contains("Font-Default-Color", descriptor);
                Assert.DoesNotContain("<Null Name=\"NamedColor\" />", descriptor);
            }
        }

        [Theory]
        [InlineData("light")]
        [InlineData("dark")]
        public void Button_fill_member_uses_a_single_style_or_literal_value(string scheme)
        {
            var screen = "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"SizeX\" Type=\"int\">800</Single>"
                + "<Single Name=\"SizeY\" Type=\"int\">480</Single>"
                + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\"></List></Single>";
            var catalog = VisuCatalog.Load("button");
            var colors = (IDictionary<string, object>)catalog["themeable_colors"];
            var fill = (IDictionary<string, object>)colors["fill"];
            var role = Convert.ToString(fill["role"]);
            var parameters = new Dictionary<string, object> {
                ["x"] = "20", ["y"] = "20", ["width"] = "120", ["height"] = "30", ["text"] = "Start",
            };
            var output = ElementTemplates.Append(screen, catalog, parameters, null, Themes.Palette(scheme, null), scheme).Xml;
            if (scheme == "dark")
            {
                var palette = Themes.Palette(scheme, null);
                Assert.Contains(ColorValue(palette[role.Replace('-', '.')]), output);
            }
            else
            {
                Assert.Contains("CanonicalName", output);
            }
        }

        static string ColorValue(string color)
        {
            var raw = color.TrimStart('#');
            var value = Convert.ToUInt32(raw, 16);
            if (raw.Length <= 6) value |= 0xff000000;
            return value.ToString();
        }

        static int Count(string text, string value)
        {
            var count = 0;
            var offset = 0;
            while ((offset = text.IndexOf(value, offset, StringComparison.Ordinal)) >= 0)
            {
                count++;
                offset += value.Length;
            }
            return count;
        }

        static double Contrast(string foreground, string background)
        {
            var first = Luminance(foreground);
            var second = Luminance(background);
            return (Math.Max(first, second) + 0.05) / (Math.Min(first, second) + 0.05);
        }

        static double Luminance(string color)
        {
            var channels = new double[3];
            for (var index = 0; index < channels.Length; index++)
            {
                var value = Convert.ToInt32(color.Substring(1 + index * 2, 2), 16) / 255.0;
                channels[index] = value <= 0.03928 ? value / 12.92 : Math.Pow((value + 0.055) / 1.055, 2.4);
            }
            return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
        }
    }
}
