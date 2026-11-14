using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        static readonly string EmptyCanvas = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\"></svg>";

        static readonly object[][] LintRuleData = {
            new object[] { "bounds", "<rect x=\"-4\" y=\"80\" width=\"20\" height=\"20\"/>", "<rect x=\"80\" y=\"80\" width=\"20\" height=\"20\"/>" },
            new object[] { "margin", "<rect x=\"2\" y=\"100\" width=\"20\" height=\"20\"/>",
                           "<rect x=\"80\" y=\"100\" width=\"20\" height=\"20\"/>" },
            new object[] { "grid", "<rect x=\"9\" y=\"100\" width=\"20\" height=\"20\"/>", "<rect x=\"8\" y=\"100\" width=\"20\" height=\"20\"/>" },
            new object[] { "font-scale", "<text x=\"80\" y=\"120\" font-size=\"13\">Ready</text>",
                           "<text x=\"80\" y=\"120\" font-size=\"12\">Ready</text>" },
            new object[] {
                "touch-size",
                "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"30\" height=\"20\" data-text=\"Go\" data-cds-tap=\"PLC.xGo\"/>",
                "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\" data-cds-tap=\"PLC.xGo\"/>"
            },
            new object[] { "text-overflow", "<text x=\"80\" y=\"120\" data-width=\"20\">MMMMMMMM</text>",
                           "<text x=\"80\" y=\"120\" data-width=\"160\">MMMMMMMM</text>" },
            new object[] { "text-anchor", "<text x=\"80\" y=\"120\" text-anchor=\"middle\">Ready</text>",
                           "<text x=\"80\" y=\"120\" text-anchor=\"middle\" data-width=\"120\">Ready</text>" },
            new object[] { "unsized-field", "<text data-cds-type=\"textfield\" x=\"80\" y=\"120\">%d</text>",
                           "<text data-cds-type=\"textfield\" x=\"80\" y=\"120\" data-width=\"120\" data-height=\"24\">%d</text>" },
            new object[] { "scaffold", "", "" },
            new object[] { "empty-panel", "<rect class=\"panel\" x=\"80\" y=\"80\" width=\"200\" height=\"160\"/>",
                           "<rect class=\"panel\" x=\"80\" y=\"80\" width=\"200\" height=\"160\"/><text x=\"104\" y=\"120\">Inside</text>" },
            new object[] { "lonely-card", "<rect class=\"card\" x=\"80\" y=\"80\" width=\"200\" height=\"160\"/>",
                           "<rect class=\"panel\" x=\"80\" y=\"80\" width=\"240\" height=\"200\"/><rect class=\"card\" x=\"100\" y=\"100\" "
                           + "width=\"200\" height=\"160\"/>" },
            new object[] {
                "unbound-field", "<text data-cds-type=\"textfield\" x=\"80\" y=\"120\" data-width=\"120\" data-height=\"24\">%d</text>",
                "<text data-cds-type=\"textfield\" x=\"80\" y=\"120\" data-width=\"120\" data-height=\"24\" data-text-var=\"PLC.iCount\">%d</text>"
            },
            new object[] { "static-state", "<text x=\"80\" y=\"120\">Motor = Running</text>", "<text x=\"80\" y=\"120\">Motor Running</text>" },
            new object[] {
                "empty-button", "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-cds-tap=\"PLC.xGo\"/>",
                "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\" data-cds-tap=\"PLC.xGo\"/>"
            },
            new object[] {
                "inert-button", "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\"/>",
                "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\" data-cds-tap=\"PLC.xGo\"/>"
            },
            new object[] { "control-tag", "<circle data-cds-type=\"lamp\" cx=\"100\" cy=\"100\" r=\"12\"/>",
                           "<rect data-cds-type=\"lamp\" x=\"80\" y=\"80\" width=\"24\" height=\"24\" data-var=\"PLC.xRun\"/>" },
            new object[] {
                "inert-class",
                "<rect data-cds-type=\"button\" class=\"h1\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\" "
                + "data-cds-tap=\"PLC.xGo\"/>",
                "<rect data-cds-type=\"button\" x=\"80\" y=\"100\" width=\"80\" height=\"40\" data-text=\"Go\" data-cds-tap=\"PLC.xGo\"/>"
            },
            new object[] { "unbound-lamp", "<rect data-cds-type=\"lamp\" x=\"80\" y=\"100\" width=\"24\" height=\"24\"/>",
                           "<rect data-cds-type=\"lamp\" x=\"80\" y=\"100\" width=\"24\" height=\"24\" data-var=\"PLC.xRun\"/>" },
            new object[] { "overlap", "<rect x=\"80\" y=\"80\" width=\"100\" height=\"100\"/><circle cx=\"160\" cy=\"160\" r=\"60\"/>",
                           "<rect x=\"80\" y=\"80\" width=\"100\" height=\"100\"/><circle cx=\"240\" cy=\"160\" r=\"40\"/>" },
            new object[] { "overflow",
                           "<rect x=\"80\" y=\"80\" width=\"100\" height=\"100\"/><text x=\"160\" y=\"120\" data-width=\"80\">Too far</text>",
                           "<rect x=\"80\" y=\"80\" width=\"100\" height=\"100\"/><text x=\"100\" y=\"120\" data-width=\"60\">Inside</text>" },
            new object[] { "padding", "<rect class=\"panel\" x=\"80\" y=\"80\" width=\"200\" height=\"160\"/><text x=\"84\" y=\"120\">Close</text>",
                           "<rect class=\"panel\" x=\"80\" y=\"80\" width=\"200\" height=\"160\"/><text x=\"104\" y=\"120\">Padded</text>" },
            new object[] { "list-fit",
                           "<rect data-cds-type=\"combobox\" x=\"80\" y=\"200\" width=\"160\" height=\"32\" data-var=\"G.iMode\" "
                           + "data-list-rows=\"10\" data-row-height=\"32\"/>",
                           "<rect data-cds-type=\"combobox\" x=\"80\" y=\"200\" width=\"160\" height=\"32\" data-var=\"G.iMode\" "
                           + "data-list-rows=\"7\" data-row-height=\"32\"/>" },
            new object[] { "crowding", "<rect x=\"80\" y=\"100\" width=\"40\" height=\"40\"/><rect x=\"124\" y=\"100\" width=\"40\" height=\"40\"/>",
                           "<rect x=\"80\" y=\"100\" width=\"40\" height=\"40\"/><rect x=\"136\" y=\"100\" width=\"40\" height=\"40\"/>" },
        };

        [Theory]
        [MemberData(nameof(LintRuleFixtures))]
        public void Every_lint_rule_has_a_firing_and_non_firing_case(string rule, string negativeElement, string positiveElement)
        {
            var negative = Lint(rule == "scaffold" ? StarterSketch() : Svg(negativeElement));
            var positive = Lint(Svg(positiveElement));

            Assert.Contains(rule, negative);
            Assert.DoesNotContain(rule, positive);
        }

        [Fact]
        public void A_lamp_centred_in_a_row_is_on_the_grid_and_one_nudged_off_centre_is_not()
        {
            // A 20px lamp in a 32px row starting at y=100: centred at y=106, its centre is on the grid, its top cannot be.
            var centred = Cts.Visu.SketchLinter.Find(Cts.Visu.Sketch.Parse(Svg(
                "<rect data-cds-type=\"lamp\" data-var=\"G.xOn\" x=\"86\" y=\"106\" width=\"20\" height=\"20\"/>")));
            var nudged = Cts.Visu.SketchLinter.Find(Cts.Visu.Sketch.Parse(Svg(
                "<rect data-cds-type=\"lamp\" data-var=\"G.xOn\" x=\"80\" y=\"107\" width=\"20\" height=\"20\"/>")));

            Assert.DoesNotContain(centred, finding => finding.Rule == "grid");
            Assert.Equal("108", Assert.Single(nudged, finding => finding.Rule == "grid").Fixes["y"]);
        }

        [Fact]
        public void A_combobox_list_with_a_size_from_the_style_is_not_checked()
        {
            // The style's row height is not known offline, so a long explicit row count alone is no finding.
            var findings = Cts.Visu.SketchLinter.Find(Cts.Visu.Sketch.Parse(Svg(
                "<rect data-cds-type=\"combobox\" x=\"80\" y=\"200\" width=\"160\" height=\"32\" data-var=\"G.iMode\" data-list-rows=\"40\"/>")));

            Assert.DoesNotContain(findings, finding => finding.Rule == "list-fit");
        }

        [Fact]
        public void A_dense_table_is_one_crowding_line_per_gap_and_a_lone_pair_keeps_its_own()
        {
            var cells = "";
            for (var row = 0; row < 8; row++)
                for (var column = 0; column < 2; column++)
                    cells += "<rect x=\"" + (80 + column * 164) + "\" y=\"" + (80 + row * 36) + "\" width=\"160\" height=\"32\"/>";
            var lone = "<rect x=\"600\" y=\"80\" width=\"40\" height=\"40\"/><rect x=\"646\" y=\"80\" width=\"40\" height=\"40\"/>";

            var crowding = Cts.Visu.SketchLinter.Find(Cts.Visu.Sketch.Parse(Svg(cells + lone))).Where(finding => finding.Rule == "crowding")
                               .Select(finding => finding.Message).ToList();

            Assert.Equal(3, crowding.Count);
            Assert.Contains(crowding, message => message.StartsWith("14 pairs of elements are 4px apart vertically", StringComparison.Ordinal));
            Assert.Contains(crowding, message => message.StartsWith("8 pairs of elements are 4px apart horizontally", StringComparison.Ordinal));
            Assert.Contains(crowding, message => message.EndsWith("are 6px apart horizontally", StringComparison.Ordinal));
        }

        public static IEnumerable<object[]> LintRuleFixtures => LintRuleFixturesData();

        static IEnumerable<object[]> LintRuleFixturesData()
        {
            foreach (var fixture in LintRuleData)
            {
                yield return fixture;
            }
        }

        static string Lint(string svg)
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-lint-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                File.WriteAllText(path, svg);
                var (_, output, error) = RunLocal("visu", "lint", "--svg", path);
                return output + error;
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        static string Svg(string element)
        {
            return EmptyCanvas.Replace("</svg>", element + "</svg>");
        }

        static string StarterSketch()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-start-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                var (code, _, _) = RunLocal("visu", "new", "--name", "Demo", "--out", path);
                Assert.Equal(0, code);
                return File.ReadAllText(path);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }
    }
}
