using System;
using System.IO;
using Xunit;
using Cts.Visu;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        const string EmptyScreen = "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
            + "<Single Name=\"SizeX\" Type=\"int\">800</Single><Single Name=\"SizeY\" Type=\"int\">480</Single>"
            + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\"></List></Single>";

        [Fact]
        public void To_svg_writes_an_svg_for_a_screen_path()
        {
            var directory = Path.Combine(Path.GetTempPath(), "cts-visu-render-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var view = Path.Combine(directory, "project-view");
            Directory.CreateDirectory(view);
            var screen = Path.Combine(view, "Main.xml");
            try
            {
                File.WriteAllText(screen, EmptyScreen);
                var (code, output, error) = RunLocal("visu", "to-svg", "--screen", screen, "--sync-folder", directory);
                Assert.True(code == 0, output + "\n" + error);
                Assert.Empty(error);
                Assert.StartsWith("ok visu-to-svg out=", output);
                Assert.Contains("width=\"800\"", File.ReadAllText(Path.ChangeExtension(screen, ".svg")));
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        }

        [Fact]
        public void Preview_writes_resolved_svg_and_grid_when_png_is_disabled()
        {
            var directory = Path.Combine(Path.GetTempPath(), "cts-visu-preview-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var sketch = Path.Combine(directory, "Main.svg");
            try
            {
                File.WriteAllText(sketch, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"48\"><rect x=\"8\" y=\"8\" width=\"16\" height=\"16\"/></svg>");
                var (code, output, error) = RunLocal("visu", "preview", "--svg", sketch, "--grid", "8", "--no-png");
                Assert.True(code == 0, output);
                Assert.Empty(error);
                Assert.Contains("Preview SVG", output);
                var rendered = File.ReadAllText(Path.Combine(directory, "Main.preview.svg"));
                Assert.Contains("stroke-opacity=\"0.06\"", rendered);
                Assert.Contains("<rect", rendered);
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        }

        [Fact]
        public void From_svg_renders_preview_by_default_and_no_preview_skips_it()
        {
            var directory = Path.Combine(Path.GetTempPath(), "cts-visu-from-svg-preview-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var view = Path.Combine(directory, "project-view");
            Directory.CreateDirectory(view);
            File.WriteAllText(Path.Combine(view, "Existing.xml"), "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\"><Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single><Array Name=\"Path\"></Array></Single>");
            try
            {
                var sketch = Path.Combine(directory, "Sketch.svg");
                File.WriteAllText(sketch, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\"></svg>");
                var (code, output, error) = RunLocal("visu", "from-svg", "--svg", sketch, "--create-screen", "--screen-name", "Main",
                    "--sync-folder", view);
                Assert.True(code == 0, output + "\n" + error);
                Assert.Contains("Preview SVG", output);
                Assert.True(File.Exists(Path.Combine(directory, "Sketch.preview.svg")));

                var second = Path.Combine(directory, "second.svg");
                File.WriteAllText(second, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\"></svg>");
                var (noPreviewCode, noPreviewOutput, _) = RunLocal("visu", "from-svg", "--svg", second, "--create-screen", "--screen-name", "Other",
                    "--sync-folder", view, "--no-preview");
                Assert.Equal(0, noPreviewCode);
                Assert.DoesNotContain("Preview SVG", noPreviewOutput);
                Assert.False(File.Exists(Path.Combine(directory, "second.preview.svg")));
            }
            finally
            {
                Directory.Delete(directory, true);
            }
        }

        [Fact]
        public void Svg_export_rejects_unknown_screen_element_types()
        {
            const string xml = "<Single><Single Name=\"SizeX\">800</Single><Single Name=\"SizeY\">480</Single>"
                + "<List Name=\"VisualElementList\"><Single><Single Name=\"VisualElementTypeName\">Alien</Single>"
                + "<Single Name=\"VisualElemMemberList\"><List Name=\"VisualElemMemberList\"></List></Single></Single></List></Single>";
            Assert.Throws<VisuException>(() => SvgExport.ScreenToSvg(xml));
        }
    }
}
