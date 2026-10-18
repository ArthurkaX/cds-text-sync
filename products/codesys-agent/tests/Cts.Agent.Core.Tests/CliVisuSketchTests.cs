using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Fact]
        public void Sketch_parser_resolves_linear_gradient_stops_and_direction()
        {
            const string svg = "<svg xmlns=\"http://www.w3.org/2000/svg\"><defs><linearGradient id=\"g\" x1=\"0%\" y1=\"0%\" x2=\"0%\" "
                               + "y2=\"100%\"><stop offset=\"0%\" stop-color=\"#112233\"/><stop offset=\"100%\" "
                               + "stop-color=\"#AABBCC\"/></linearGradient></defs><rect fill=\"url(#g)\"/></svg>";
            var sketch = Cts.Visu.Sketch.Parse(svg);
            var gradient = sketch.Elements[0].Gradient;
            Assert.NotNull(gradient);
            Assert.Equal("4279312947", gradient.Color1);
            Assert.Equal("4289379276", gradient.Color2);
            Assert.Equal(90, gradient.Angle);
            Assert.Equal("linear", gradient.Type);
        }

        [Fact]
        public void Sketch_parser_resolves_radial_gradient_and_axial_marker()
        {
            const string svg
                = "<svg xmlns=\"http://www.w3.org/2000/svg\"><defs><radialGradient id=\"g\" cx=\"25%\" cy=\"75%\"><stop offset=\"0\" "
                  + "stop-color=\"#FFFFFF\"/><stop offset=\"1\" stop-color=\"#000000\"/></radialGradient></defs><rect fill=\"url(#g)\"/></svg>";
            var sketch = Cts.Visu.Sketch.Parse(svg);
            var gradient = sketch.Elements[0].Gradient;
            Assert.NotNull(gradient);
            Assert.Equal("radial", gradient.Type);
            Assert.Equal(25, gradient.CenterX);
            Assert.Equal(75, gradient.CenterY);
        }

        [Theory]
        [InlineData(800, 480, "light")]
        [InlineData(800, 480, "dark")]
        [InlineData(480, 320, "light")]
        [InlineData(480, 320, "dark")]
        public void Visu_new_writes_a_sketch_that_lints_clean(int width, int height, string scheme)
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                var (newCode, _, _)
                    = RunLocal("visu", "new", "--name", "Demo", "--w", width.ToString(), "--h", height.ToString(), "--scheme", scheme, "--out", path);
                Assert.Equal(0, newCode);
                var (lintCode, output, error) = RunLocal("visu", "lint", "--svg", path);
                Assert.Equal(0, lintCode);
                Assert.Empty(error);
                Assert.DoesNotContain("[FAIL]", output);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void Visu_new_warns_when_canvas_is_below_the_layout_minimum_or_off_grid()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                var (code, output, error) = RunLocal("visu", "new", "--w", "479", "--h", "319", "--out", path);

                Assert.Equal(0, code);
                Assert.Empty(error);
                Assert.Contains("below 480x320", output);
                Assert.Contains("--w and --h are not multiples of 4", output);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_changes_only_the_selected_element_bindings()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N") + ".svg");
            const string svg = "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">\n"
                               + "  <rect data-cds-type=\"lamp\" x=\"8\" y=\"8\" width=\"20\" height=\"20\" fill=\"red\"/>\n" + "</svg>\n";
            try
            {
                File.WriteAllText(path, svg);
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--var", "VisuVars.xRunning");
                Assert.Equal(0, code);
                Assert.Empty(error);
                var updated = File.ReadAllText(path);
                Assert.Contains("fill=\"red\"", updated);
                Assert.Contains("data-var=\"VisuVars.xRunning\"", updated);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_refuses_a_binding_for_the_wrong_control_type()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                File.WriteAllText(path, "<svg width=\"800\" height=\"480\"><rect x=\"8\" y=\"8\" width=\"80\" height=\"40\"/></svg>");
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--tap", "HMI.xGo");
                Assert.Equal(1, code);
                Assert.Contains("applies to button", error);
                Assert.DoesNotContain("data-cds-tap", File.ReadAllText(path));
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }

        [Fact]
        public void Visu_lint_fix_snaps_source_geometry_and_strict_rejects_warnings()
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N") + ".svg");
            try
            {
                File.WriteAllText(path, "<svg width=\"800\" height=\"480\"><rect x=\"10\" y=\"8\" width=\"80\" height=\"24\"/></svg>");
                var (fixCode, fixedOutput, _) = RunLocal("visu", "lint", "--svg", path, "--fix");
                Assert.Equal(0, fixCode);
                Assert.Contains("Fixed 1 attribute", fixedOutput);
                Assert.Contains("x=\"8\"", File.ReadAllText(path));

                File.WriteAllText(path, "<svg width=\"800\" height=\"480\"><rect data-cds-type=\"button\" x=\"8\" y=\"8\" width=\"40\" height=\"20\" "
                                        + "data-text=\"Go\" data-cds-tap=\"HMI.xGo\"/></svg>");
                var (strictCode, strictOutput, _) = RunLocal("visu", "lint", "--svg", path, "--strict");
                Assert.Equal(1, strictCode);
                Assert.Contains("touch-size", strictOutput);
            }
            finally
            {
                if (File.Exists(path)) File.Delete(path);
            }
        }
    }
}
