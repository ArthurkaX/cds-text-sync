using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Theory]
        [InlineData("--var", "PLC.xRunning", "data-var=\"PLC.xRunning\"")]
        [InlineData("--color", "blue", "data-color=\"blue\"")]
        [InlineData("--text-var", "PLC.rSpeed", "data-text-var=\"PLC.rSpeed\"")]
        [InlineData("--tap", "PLC.xStart", "data-cds-tap=\"tap:PLC.xStart\"")]
        [InlineData("--toggle", "PLC.xEnable", "data-cds-tap=\"toggle:PLC.xEnable\"")]
        public void Visu_bind_sets_each_typed_binding_on_the_selected_control(string flag, string value, string expected)
        {
            var type = flag == "--text-var" ? "textfield" : flag == "--tap" || flag == "--toggle" ? "button" : "lamp";
            var tag = type == "textfield"
                          ? "<text data-cds-type=\"textfield\" x=\"40\" y=\"80\" data-width=\"80\" data-height=\"24\">0</text>"
                          : "<rect data-cds-type=\"" + type + "\" x=\"40\" y=\"40\" width=\"40\" height=\"40\" fill=\"#ff0000\" stroke=\"#000000\"/>";
            var path = WriteSketch(tag);
            try
            {
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", flag, value);

                Assert.Equal(0, code);
                Assert.Empty(error);
                Assert.Contains(expected, File.ReadAllText(path));
                if (type == "textfield")
                    Assert.Contains(">0</text>", File.ReadAllText(path));
                else
                    Assert.Contains("fill=\"#ff0000\" stroke=\"#000000\"", File.ReadAllText(path));
            }
            finally
            {
                File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_appends_actions_and_keeps_the_existing_clause()
        {
            var path = WriteSketch(
                "<rect data-cds-type=\"button\" data-text=\"Go\" data-cds-action=\"TAP PLC.xA\" x=\"40\" y=\"40\" width=\"80\" height=\"40\"/>");
            try
            {
                var (code, _, _) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--action", "TAP PLC.xB");

                Assert.Equal(0, code);
                Assert.Contains("data-cds-action=\"TAP PLC.xA || TAP PLC.xB\"", File.ReadAllText(path));
            }
            finally
            {
                File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_updates_single_quoted_attribute_without_adding_a_duplicate()
        {
            var path = WriteSketch("<rect data-cds-type=\"lamp\" data-var='Old' x=\"40\" y=\"40\" width=\"40\" height=\"40\"/>");
            try
            {
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--var", "New");
                var after = File.ReadAllText(path);
                Assert.Equal(0, code);
                Assert.Empty(error);
                Assert.Equal(1, after.Split(new[] { "data-var=" }, StringSplitOptions.None).Length - 1);
                Assert.Contains("data-var='New'", after);
            }
            finally { File.Delete(path); }
        }

        [Fact]
        public void Visu_bind_clear_removes_single_quoted_bindings()
        {
            var path = WriteSketch("<rect data-cds-type=\"lamp\" data-var='Old' data-color='red' x=\"40\" y=\"40\" width=\"40\" height=\"40\"/>");
            try
            {
                var (code, _, _) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--clear");
                Assert.Equal(0, code);
                Assert.DoesNotContain("data-var=", File.ReadAllText(path));
                Assert.DoesNotContain("data-color=", File.ReadAllText(path));
            }
            finally { File.Delete(path); }
        }

        [Fact]
        public void Visu_bind_action_merge_escapes_an_existing_action_once()
        {
            var path = WriteSketch(
                "<rect data-cds-type=\"button\" data-text=\"Go\" data-cds-action=\"OnMouseClick: ST PLC.x := PLC.a &lt; 3;\" x=\"40\" y=\"40\" width=\"80\" height=\"40\"/>");
            try
            {
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--action", "TAP PLC.xB");
                Assert.Equal(0, code);
                Assert.Empty(error);
                Assert.Contains("data-cds-action=\"OnMouseClick: ST PLC.x := PLC.a &lt; 3; || TAP PLC.xB\"", File.ReadAllText(path));
            }
            finally { File.Delete(path); }
        }

        [Fact]
        public void Visu_bind_does_not_match_attribute_name_prefixes()
        {
            var path = WriteSketch("<rect data-cds-type=\"lamp\" data-var-x='Keep' x=\"40\" y=\"40\" width=\"40\" height=\"40\"/>");
            try
            {
                var (code, _, _) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--var", "New");
                var after = File.ReadAllText(path);
                Assert.Equal(0, code);
                Assert.Contains("data-var-x='Keep'", after);
                Assert.Contains("data-var=\"New\"", after);
            }
            finally { File.Delete(path); }
        }

        [Fact]
        public void Visu_bind_action_can_be_added_to_a_plain_rectangle()
        {
            var path = WriteSketch("<rect x=\"40\" y=\"40\" width=\"80\" height=\"40\" fill=\"#123456\"/>");
            try
            {
                var (code, _, _) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--action", "OnMouseClick: ST PLC.x := TRUE;");

                Assert.Equal(0, code);
                Assert.Contains("data-cds-action=\"OnMouseClick: ST PLC.x := TRUE;\"", File.ReadAllText(path));
                Assert.Contains("fill=\"#123456\"", File.ReadAllText(path));
            }
            finally
            {
                File.Delete(path);
            }
        }

        [Theory]
        [InlineData("--tap", "PLC.xGo", "lamp")]
        [InlineData("--var", "PLC.xGo", "button")]
        public void Visu_bind_refuses_type_mismatches_without_writing(string flag, string value, string type)
        {
            var tag = "<rect data-cds-type=\"" + type + "\" data-text=\"Go\" x=\"40\" y=\"40\" width=\"80\" height=\"40\"/>";
            var path = WriteSketch(tag);
            try
            {
                var before = File.ReadAllText(path);
                var (code, _, error) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", flag, value);

                Assert.Equal(1, code);
                Assert.Contains("applies to", error);
                Assert.Equal(before, File.ReadAllText(path));
            }
            finally
            {
                File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_clear_removes_bindings_without_touching_paint_or_other_elements()
        {
            var path = WriteSketch("<rect data-cds-type=\"lamp\" x=\"40\" y=\"40\" width=\"40\" height=\"40\" data-var=\"PLC.xRun\" "
                                   + "data-color=\"green\" fill=\"#ff0000\"/><rect x=\"200\" y=\"40\" width=\"40\" height=\"40\"/>");
            try
            {
                var before = File.ReadAllText(path);
                var secondRect = before.IndexOf("<rect", before.IndexOf("<rect", StringComparison.Ordinal) + 1, StringComparison.Ordinal);
                var secondTag = before.Substring(secondRect, before.IndexOf('>', secondRect) - secondRect + 1);
                var (code, _, _) = RunLocal("visu", "bind", "--svg", path, "--elem", "0", "--clear");
                var after = File.ReadAllText(path);

                Assert.Equal(0, code);
                Assert.DoesNotContain("data-var", after);
                Assert.DoesNotContain("data-color", after);
                Assert.Contains("fill=\"#ff0000\"", after);
                Assert.Contains(secondTag, after);
            }
            finally
            {
                File.Delete(path);
            }
        }

        [Fact]
        public void Visu_bind_rejects_missing_flags_and_out_of_range_indices()
        {
            var path = WriteSketch("<rect data-cds-type=\"lamp\" x=\"40\" y=\"40\" width=\"40\" height=\"40\"/>");
            try
            {
                var (emptyCode, _, emptyError) = RunLocal("visu", "bind", "--svg", path, "--elem", "0");
                var (rangeCode, _, rangeError) = RunLocal("visu", "bind", "--svg", path, "--elem", "5", "--var", "PLC.xRun");

                Assert.Equal(1, emptyCode);
                Assert.Contains("nothing to do", emptyError);
                Assert.Equal(1, rangeCode);
                Assert.Contains("out of range", rangeError);
            }
            finally
            {
                File.Delete(path);
            }
        }

        static string WriteSketch(string element)
        {
            var path = Path.Combine(Path.GetTempPath(), "cts-visu-bind-" + Guid.NewGuid().ToString("N") + ".svg");
            File.WriteAllText(path, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">" + element + "</svg>");
            return path;
        }
    }
}
