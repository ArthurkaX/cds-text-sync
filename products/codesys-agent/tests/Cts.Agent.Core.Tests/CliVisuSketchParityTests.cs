using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class CliVisuSketchParityTests
    {
        static readonly string[] ThemeNames = {
            "basic-style",
            "default",
            "flat-style",
            "style-6-gradient-axial-2",
            "flat-style",
            "basic-style",
            "default",
            "example-for-a-style",
            "white-style",
            "style-2",
            "style-3-gradient-linear-1",
            "style-4-gradient-linear-2",
            "style-5-gradient-axial-1",
            "style-6-gradient-axial-2",
            "style-7-gradient-double-linear-1",
            "style-8-gradient-double-linear-2",
        };

        [Theory]
        [MemberData(nameof(AllThemeSchemes))]
        public void Every_embedded_and_builtin_theme_resolves_in_both_schemes(string themeName, string scheme)
        {
            var colors = Cts.Visu.Themes.Palette(scheme, themeName);

            Assert.Equal(scheme == "dark" ? "#10141A" : "#F4F5F7", colors["screen"]);
            if (scheme == "dark")
                Assert.Equal("#E6E9ED", colors["text"]);
            else
                Assert.False(string.IsNullOrWhiteSpace(colors["text"]));
            Assert.True(colors.ContainsKey("water.dim"));
            Assert.True(colors.ContainsKey("button.text"));
        }

        public static IEnumerable<object[]> AllThemeSchemes()
        {
            foreach (var name in ThemeNames.Distinct(StringComparer.Ordinal))
            {
                yield return new object[] { name, "light" };
                yield return new object[] { name, "dark" };
            }
        }

        [Fact]
        public void Sketch_parser_returns_specs_for_every_supported_element_form()
        {
            const string svg
                = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                  + "<rect x=\"8\" y=\"8\" width=\"80\" height=\"40\" rx=\"4\" fill=\"#112233\"/>" + "<circle cx=\"100\" cy=\"40\" r=\"12\"/>"
                  + "<ellipse cx=\"150\" cy=\"40\" rx=\"20\" ry=\"10\"/>" + "<line x1=\"8\" y1=\"80\" x2=\"100\" y2=\"80\" stroke=\"#334455\"/>"
                  + "<text x=\"8\" y=\"120\" font-size=\"16\" fill=\"#223344\">Title</text>"
                  + "<rect data-cds-type=\"button\" x=\"8\" y=\"160\" width=\"120\" height=\"40\" data-text=\"Start\" "
                    + "data-cds-action=\"toggle:PLC.xRun\" data-open-dialog=\"Settings\"/>"
                  + "<text data-cds-type=\"textfield\" x=\"160\" y=\"180\" data-width=\"80\" data-height=\"24\" "
                    + "data-text-var=\"PLC.sValue\">%s</text>"
                  + "<rect data-cds-type=\"lamp\" x=\"8\" y=\"220\" data-color=\"red\" data-var=\"PLC.xAlarm\"/>"
                  + "<rect data-cds-type=\"image-switcher\" x=\"64\" y=\"220\" data-image-on=\"On\" data-image-off=\"Off\" data-var=\"PLC.xOn\"/>"
                  + "<rect data-cds-type=\"combobox\" x=\"144\" y=\"220\" data-items=\"GVL.Texts\" data-var=\"PLC.iMode\"/>"
                  + "<rect data-cds-type=\"alarm-banner\" x=\"280\" y=\"220\"/>"
                  + "<rect data-cds-type=\"frame\" x=\"8\" y=\"280\" data-visu=\"Faceplate\" data-param-Mode=\"3\"/>" + "</svg>";

            var sketch = Cts.Visu.Sketch.Parse(svg);
            var elements = sketch.Elements;

            Assert.Equal(new[] { "rectangle", "rectangle", "rectangle", "line", "label", "button", "textfield", "lamp", "image-switcher", "combobox",
                                 "alarm-banner", "frame" },
                         System.Linq.Enumerable.Select(elements, element => element.Type));
            Assert.Equal("rounded", elements[0].SpecParams["shape"]);
            Assert.Equal("ellipse", elements[1].SpecParams["shape"]);
            Assert.Equal("4279312947", elements[0].SpecParams["fill"]);
            Assert.Equal("PLC.sValue", elements[6].SpecParams["text_var"]);
            Assert.Equal("Element-Lamp-Lamp1-Red", elements[7].SpecParams["style_role"]);
            Assert.Equal("GVL.Texts", elements[9].SpecParams["items"]);
            Assert.Equal("Faceplate", elements[11].SpecParams["visu"]);
            Assert.IsType<Dictionary<string, string>>(elements[11].SpecParams["params"]);
            Assert.True(elements[5].SpecParams.ContainsKey("configured_inputs"));
            Assert.True(elements[5].SpecParams.ContainsKey("input_actions"));
        }

        [Fact]
        public void Text_anchor_sets_alignment_and_moves_the_box_from_the_baseline()
        {
            const string svg
                = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                  + "<text x=\"100\" y=\"50\" font-size=\"16\" data-width=\"80\" data-height=\"24\" text-anchor=\"middle\">Mid</text>"
                  + "<text data-cds-type=\"textfield\" x=\"100\" y=\"50\" font-size=\"16\" data-width=\"80\" data-height=\"24\" "
                    + "text-anchor=\"end\">%s</text>" + "</svg>";

            var elements = Cts.Visu.Sketch.Parse(svg).Elements;

            Assert.Equal(new[] { "38", "HCENTER", "VCENTER" }, new[] { "y", "h_align", "v_align" }.Select(key => elements[0].SpecParams[key]));
            Assert.Equal(new[] { "34", "RIGHT", "TOP", "16" }, new[] { "y", "h_align", "v_align", "font_size" }.Select(key => elements[1].SpecParams[key]));
        }

        [Fact]
        public void Theme_roles_inline_variables_and_css_overrides_follow_the_layer_order()
        {
            var directory = Path.Combine(Path.GetTempPath(), "cts-visu-css-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                File.WriteAllText(Path.Combine(directory, "visu.css"), ".project { fill: var(--accent); }");
                const string svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" data-cds-scheme=\"DARK\"><defs><style>:root { --accent: #123456; "
                                   + "}</style></defs><rect class=\"project\" x=\"8\" y=\"8\" width=\"40\" height=\"40\"/></svg>";
                var sketch = Cts.Visu.Sketch.Parse(svg, directory, "style", null, "flat-style");

                Assert.Equal("dark", sketch.Scheme);
                Assert.Equal("#171C24", sketch.Background);
                Assert.Equal("#123456", sketch.Theme["accent"]);
                Assert.Equal("4279383126", sketch.Elements[0].SpecParams["fill"]);
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        }

        [Fact]
        public void Read_scheme_uses_override_and_falls_back_on_malformed_xml()
        {
            Assert.Equal("dark", Cts.Visu.Sketch.ReadScheme("<svg data-cds-scheme='light'/>", "DARK"));
            Assert.Equal("light", Cts.Visu.Sketch.ReadScheme("<svg broken"));
        }
    }
}
