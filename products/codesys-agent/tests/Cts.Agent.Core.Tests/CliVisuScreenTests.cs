using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;
using Cts.Visu;

namespace Cts.Agent.Tests
{
    public class CliVisuScreenTests : IDisposable
    {
        const string Member = "{c694e3a2-5c0b-4177-ab35-cb06bd5a6a02}";
        readonly string root = Path.Combine(Path.GetTempPath(), "cts-visu-" + Guid.NewGuid().ToString("N"));
        readonly string view;

        public CliVisuScreenTests()
        {
            view = Path.Combine(root, "project-view");
            Directory.CreateDirectory(view);
        }

        public void Dispose()
        {
            Directory.Delete(root, true);
        }

        static string Scalar(long id, object value, string type = "int")
        {
            return "<Single Type=\"" + Member + "\" Method=\"IArchivable\"><Single Name=\"Id\" Type=\"long\">" + id + "</Single>"
                + "<Single Name=\"Value\" Type=\"" + type + "\">" + value + "</Single></Single>";
        }

        static string Color(long id, int color, string canonical)
        {
            return "<Single Type=\"" + Member + "\" Method=\"IArchivable\"><Single Name=\"Id\" Type=\"long\">" + id + "</Single>"
                + "<List Name=\"Value\" Type=\"System.Collections.ArrayList\"><Single Type=\"{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}\" Method=\"IArchivable\">"
                + "<Single Name=\"Color\" Type=\"int\">" + color + "</Single><Single Name=\"CanonicalName\" Type=\"string\">" + canonical + "</Single></Single></List></Single>";
        }

        static string Geometry(int x, int y, int width, int height)
        {
            return Scalar(1649127785, x) + Scalar(357335551, y) + Scalar(2422045748, width) + Scalar(2134141914, height)
                + Scalar(550940142, x + width / 2) + Scalar(1473355128, y + height / 2);
        }

        static string Element(string type, string identifier, string members, string extra = "")
        {
            return "<Single Type=\"{f86c2928-8614-4cca-824b-e819ac4d58c4}\" Method=\"IArchivable\">"
                + "<Single Name=\"VisualElemMemberList\" Type=\"{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}\" Method=\"IArchivable\">"
                + "<List Name=\"VisualElemMemberList\" Type=\"{a4b83bea-3742-489c-9fe8-d96d68dba7ab}\">" + members + "</List></Single>"
                + "<Single Name=\"VisualElementTypeName\" Type=\"string\">" + type + "</Single>"
                + "<Single Name=\"VisualElementIdentifier\" Type=\"string\">" + identifier + "</Single>" + extra + "</Single>";
        }

        static string ScreenXml(int width, int height, params string[] elements)
        {
            return "<?xml version='1.0' encoding='utf-8'?>\n<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\" Method=\"IArchivable\">"
                + "<Single Name=\"SizeX\" Type=\"int\">" + width + "</Single><Single Name=\"SizeY\" Type=\"int\">" + height + "</Single>"
                + "<Single Name=\"UniqueIdGenerator\" Type=\"string\">0</Single>"
                + "<Single Name=\"LastUsedIdForIdentifier\" Type=\"int\">0</Single>"
                + "<List Name=\"VisualElementList\" Type=\"{ef9d0b20-c96e-48db-b361-2ded4063150e}\">" + string.Concat(elements) + "</List></Single>";
        }

        string Write(string relative, string text)
        {
            var path = Path.Combine(view, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, text);
            return path;
        }

        (int, string, string) Visu(params string[] args)
        {
            return CliTests.RunLocal(new[] { "visu" }.Concat(args).Concat(new[] { "--sync-folder", view }).ToArray());
        }

        [Fact]
        public void Check_names_a_colour_whose_explicit_value_a_named_colour_hides()
        {
            var colour = System.Xml.Linq.XElement.Parse("<Root>\n<Single Type=\"" + Member + "\" Method=\"IArchivable\">\n"
                + "<Single Name=\"ExplicitColor\" Type=\"int\">-1</Single>\n"
                + "<Single Name=\"NamedColor\" Type=\"{fa491db2-51ff-4bc1-9cd0-ce8c94ff6216}\" Method=\"IArchivable\">"
                + "<Single Name=\"CanonicalName\" Type=\"string\">Element-Button-FontColor</Single></Single>\n</Single>\n</Root>",
                System.Xml.Linq.LoadOptions.SetLineInfo);
            Assert.Equal(new[] { "ExplicitColor -1 is ignored: a live NamedColor (Element-Button-FontColor) takes precedence (line 3)" },
                ScreenCheck.ColorConflicts(colour).ToArray());
            var golden = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "expected", "PLC_Stabur", "Plc Logic", "Application", "Visualization.xml");
            Assert.Empty(ScreenCheck.ColorConflicts(System.Xml.Linq.XElement.Load(golden)));
        }

        [Fact]
        public void Types_lists_the_element_types_and_not_the_input_actions()
        {
            var (code, output, _) = CliTests.RunLocal("visu", "types");
            Assert.Equal(0, code);
            Assert.Contains("button -- ", output);
            Assert.DoesNotContain("input_actions", output);
        }

        [Fact]
        public void Add_appends_a_catalog_element_and_updates_identifiers()
        {
            Write("Main.xml", ScreenXml(800, 480));
            var (code, output, error) = CliTests.RunLocal("visu", "add", "--screen", "Main", "--type", "rectangle",
                "--x", "20", "--y", "24", "--w", "120", "--h", "48", "--sync-folder", view);
            Assert.True(code == 0, error);
            Assert.Empty(error);
            Assert.Contains("GenElemInst_1", output);
            var xml = File.ReadAllText(Path.Combine(view, "Main.xml"));
            Assert.Contains("<Single Name=\"VisualElementIdentifier\" Type=\"string\">GenElemInst_1</Single>", xml);
            Assert.Contains("<Single Name=\"Id\" Type=\"long\">1649127785</Single>\n                    <Single Name=\"Value\" Type=\"int\">20</Single>", xml);
        }

        [Fact]
        public void Add_increments_identifier_and_visual_element_counters()
        {
            Write("Main.xml", ScreenXml(800, 480));
            foreach (var offset in new[] { "20", "80" })
            {
                var (code, _, error) = CliTests.RunLocal("visu", "add", "--screen", "Main", "--type", "rectangle",
                    "--x", offset, "--y", "24", "--w", "30", "--h", "20", "--sync-folder", view);
                Assert.True(code == 0, error);
            }
            var xml = File.ReadAllText(Path.Combine(view, "Main.xml"));
            Assert.Contains("GenElemInst_1", xml);
            Assert.Contains("GenElemInst_2", xml);
            Assert.Contains("<Single Name=\"VisualElementId\" Type=\"int\">0</Single>", xml);
            Assert.Contains("<Single Name=\"VisualElementId\" Type=\"int\">1</Single>", xml);
        }

        [Fact]
        public void From_svg_honors_explicit_gvl_file()
        {
            Write("Main.xml", ScreenXml(800, 480));
            var svg = Path.Combine(root, "gvl-file.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<rect data-cds-type=\"lamp\" data-lamp-color=\"green\" data-var=\"PLC.ready\" "
                + "x=\"20\" y=\"20\" width=\"20\" height=\"20\"/></svg>");
            var target = Path.Combine(root, "custom", "Declared.st");
            Directory.CreateDirectory(Path.GetDirectoryName(target));
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--gvl-file", target, "--no-preview");
            Assert.True(code == 0, error);
            Assert.Contains("ready : BOOL", File.ReadAllText(target));
            Assert.False(File.Exists(Path.Combine(view, "POUs", "VisuVars.st")));
        }

        [Fact]
        public void From_svg_writes_combobox_items_and_int_variable_type()
        {
            Write("Main.xml", ScreenXml(800, 480));
            var svg = Path.Combine(root, "combo.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<rect data-cds-type=\"combobox\" data-items=\"&apos;RECIPES&apos;\" data-var=\"HMI.Recipe\" "
                + "x=\"66\" y=\"55\" width=\"120\" height=\"25\"/></svg>");
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--gvl", "VisuVars", "--no-preview");
            Assert.True(code == 0, error);
            var xml = File.ReadAllText(Path.Combine(view, "Main.xml"));
            Assert.Contains("VisuFbComboBoxInteger", xml);
            Assert.Contains("RECIPES", xml);
            Assert.Contains("Recipe : INT", File.ReadAllText(Path.Combine(view, "POUs", "VisuVars.st")));
        }

        [Fact]
        public void From_svg_refuses_out_of_bounds_geometry()
        {
            Write("Main.xml", ScreenXml(100, 100));
            var svg = Path.Combine(root, "outside.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\">"
                + "<rect x=\"90\" y=\"10\" width=\"20\" height=\"20\"/></svg>");
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--no-preview");
            Assert.Equal(1, code);
            Assert.Contains("Sketch has errors", error);
        }

        [Fact]
        public void Strict_mode_refuses_an_info_finding_while_default_mode_compiles()
        {
            Write("Main.xml", ScreenXml(100, 100));
            var svg = Path.Combine(root, "margin.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"100\" height=\"100\">"
                + "<rect x=\"2\" y=\"20\" width=\"20\" height=\"20\"/></svg>");
            var (normal, _, normalError) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--no-preview");
            Assert.True(normal == 0, normalError);
            var (strict, _, strictError) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--strict", "--no-preview");
            Assert.Equal(1, strict);
            Assert.Contains("Refusing to compile (--strict)", strictError);
        }

        [Fact]
        public void From_svg_encodes_a_gradient_as_gradient_members()
        {
            Write("Main.xml", ScreenXml(800, 480));
            var svg = Path.Combine(root, "gradient.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<defs><linearGradient id=\"g\" x1=\"50%\" y1=\"0%\" x2=\"50%\" y2=\"100%\">"
                + "<stop offset=\"0%\" stop-color=\"#DCE0E5\"/><stop offset=\"100%\" stop-color=\"#A9AFB7\"/>"
                + "</linearGradient></defs><rect x=\"20\" y=\"20\" width=\"100\" height=\"50\" fill=\"url(#g)\"/></svg>");
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Main",
                "--sync-folder", view, "--no-preview");
            Assert.True(code == 0, error);
            var xml = File.ReadAllText(Path.Combine(view, "Main.xml"));
            Assert.Contains("1375557818", xml);
            Assert.Contains("494542316", xml);
            Assert.Contains("4292665573", xml);
            Assert.Contains("4289310647", xml);
        }

        [Fact]
        public void Create_screen_copies_placement_and_writes_requested_dimensions()
        {
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single>"
                + "<Array Name=\"Path\"><Single Type=\"string\">Application</Single></Array></Single>");
            var (code, output, error) = CliTests.RunLocal("visu", "create-screen", "--name", "Overview", "--width", "1024",
                "--height", "768", "--folder", "HMI", "--sync-folder", view);
            Assert.Equal(0, code);
            Assert.Empty(error);
            Assert.Contains("Overview (1024x768)", output);
            var xml = File.ReadAllText(Path.Combine(view, "HMI", "Overview.xml"));
            Assert.Contains("<Single Name=\"ParentGuid\" Type=\"System.Guid\">parent-guid</Single>", xml);
            Assert.Contains("<Single Name=\"ParentSVNodeGuid\" Type=\"System.Guid\">parent-node</Single>", xml);
            Assert.Contains("<Single Name=\"SizeX\" Type=\"int\">1024</Single>", xml);
            Assert.Contains("<Single Name=\"SizeY\" Type=\"int\">768</Single>", xml);
        }

        [Fact]
        public void From_svg_create_screen_without_folder_names_the_folders_it_can_go_to()
        {
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single></Single>");
            var svg = Path.Combine(root, "screen.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\"><rect x=\"20\" y=\"20\" width=\"60\" height=\"40\"/></svg>");
            var (code, output, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--create-screen",
                "--screen-name", "Overview", "--sync-folder", view, "--no-preview");
            Assert.NotEqual(0, code);
            Assert.Contains("Pass --folder, one of: HMI", output + error);
            Assert.False(File.Exists(Path.Combine(view, "Overview.xml")));
        }

        [Fact]
        public void From_svg_creates_a_screen_and_compiles_rectangle()
        {
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single>"
                + "<Array Name=\"Path\"><Single Type=\"string\">Application</Single></Array></Single>");
            var svg = Path.Combine(root, "screen.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\"><rect x=\"20\" y=\"20\" width=\"60\" height=\"40\"/></svg>");
            var (code, output, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--create-screen",
                "--screen-name", "Overview", "--folder", "HMI", "--sync-folder", view, "--no-preview");
            Assert.Equal(0, code);
            Assert.Empty(error);
            Assert.Contains("Compiled 1 element(s)", output);
            var xml = File.ReadAllText(Path.Combine(view, "HMI", "Overview.xml"));
            Assert.Contains("GenElemInst_2", xml);
            Assert.DoesNotContain("@@", xml);
        }

        [Fact]
        public void From_svg_renders_button_actions_and_writes_gvl_declarations()
        {
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single>"
                + "<Array Name=\"Path\"><Single Type=\"string\">Application</Single></Array></Single>");
            Write("HMI/Overview.xml", ScreenXml(800, 480));
            Write("POUs/GlobalTextList.csv", "TextID,TextDefault\n");
            var svg = Path.Combine(root, "actions.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<rect data-cds-type=\"button\" "
                + "data-cds-action=\"toggle:HMI.run || OnMouseClick: ST HMI.reset := TRUE;\" "
                + "x=\"20\" y=\"20\" width=\"100\" height=\"40\" />"
                + "<text x=\"20\" y=\"100\">Hello</text>"
                + "</svg>");
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Overview",
                "--folder", "HMI", "--sync-folder", view, "--gvl", "VisuVars", "--no-preview");
            Assert.True(code == 0, error);
            Assert.Empty(error);
            var xml = File.ReadAllText(Path.Combine(view, "HMI", "Overview.xml"));
            Assert.Contains("Visu_ToggleInput", xml);
            Assert.Contains("STSnippet", xml);
            Assert.Contains("VisualElementInputActions", xml);
            Assert.Contains("1,Hello", File.ReadAllText(Path.Combine(view, "POUs", "GlobalTextList.csv")));
            var gvl = File.ReadAllText(Path.Combine(view, "POUs", "VisuVars.st"));
            Assert.Contains("reset : BOOL", gvl);
            Assert.Contains("run   : BOOL", gvl);
        }

        [Fact]
        public void From_svg_makes_a_plain_rectangle_a_bound_clickable_tile()
        {
            // The member ids are the ones the IDE writes for a rectangle given a text variable,
            // a toggle colour and fill and frame colour variables in its property grid.
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single>"
                + "<Array Name=\"Path\"><Single Type=\"string\">Application</Single></Array></Single>");
            Write("HMI/Rack.xml", ScreenXml(800, 480));
            Write("POUs/GlobalTextList.csv", "TextID,TextDefault\n");
            var svg = Path.Combine(root, "tile.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<rect x=\"20\" y=\"20\" width=\"80\" height=\"40\" fill=\"#334455\" data-text=\"%s\" data-text-var=\"HMI.sCell\" "
                + "data-color-var=\"HMI.xBusy\" data-on-fill=\"#FFCC00\" data-fill-var=\"HMI.dwFrame\" "
                + "data-cds-action=\"OnMouseClick: ST HMI.iPick := 1;\" />"
                + "</svg>");
            var (code, _, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Rack",
                "--folder", "HMI", "--sync-folder", view, "--gvl", "VisuVars", "--no-preview");
            Assert.True(code == 0, error);
            var xml = File.ReadAllText(Path.Combine(view, "HMI", "Rack.xml"));
            string Member(long id) => @"<Single Name=""Id"" Type=""long"">" + id + @"</Single>\s*<Single Name=""Value"" Type=""[a-z]+"">";
            Assert.Matches(Member(390574330) + "%s<", xml);
            Assert.Matches(Member(823443203) + "1<", xml);
            Assert.Matches(Member(2477733581) + "HMI.sCell<", xml);
            Assert.Matches(Member(2597686782) + "False<", xml);
            Assert.Matches(Member(1999528970) + "HMI.xBusy<", xml);
            Assert.Matches(Member(493260384) + "4294953984<", xml);
            Assert.Matches(Member(401380312) + "HMI.dwFrame<", xml);
            Assert.Contains("STSnippet", xml);
            var gvl = File.ReadAllText(Path.Combine(view, "POUs", "VisuVars.st"));
            Assert.Matches(@"sCell\s*: STRING", gvl);
            Assert.Matches(@"xBusy\s*: BOOL", gvl);
            Assert.Matches(@"dwFrame\s*: DWORD", gvl);

            (code, _, error) = CliTests.RunLocal("visu", "to-svg", "--screen", Path.Combine(view, "HMI", "Rack.xml"), "--sync-folder", view);
            Assert.True(code == 0, error);
            var back = File.ReadAllText(Path.Combine(view, "HMI", "Rack.svg"));
            foreach (var attribute in new[] { "data-text=\"%s\"", "data-text-var=\"HMI.sCell\"", "data-color-var=\"HMI.xBusy\"",
                                              "data-on-fill=\"#ffcc00\"", "data-fill-var=\"HMI.dwFrame\"",
                                              "data-cds-action=\"OnMouseClick: ST HMI.iPick := 1;\"" })
                Assert.Contains(attribute, back);
        }

        [Fact]
        public void From_svg_replace_keeps_the_existing_screen_guid()
        {
            Write("HMI/Existing.xml", "<Single Type=\"{6198ad31-4b98-445c-927f-3258a0e82fe3}\">"
                + "<Single Name=\"MetaObject\"><Single Name=\"ParentGuid\">parent-guid</Single></Single>"
                + "<Single Name=\"ParentSVNodeGuid\">parent-node</Single>"
                + "<Array Name=\"Path\"><Single Type=\"string\">Application</Single></Array></Single>");
            Write("HMI/Overview.xml", ScreenXml(800, 480).Replace("<List Name=\"VisualElementList\"",
                "<Single Name=\"MetaObject\"><Single Name=\"Guid\" Type=\"System.Guid\">aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa</Single></Single>"
                + "<List Name=\"VisualElementList\""));
            var svg = Path.Combine(root, "replace.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\" />");
            var (code, output, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--create-screen", "--replace",
                "--screen-name", "Overview", "--folder", "HMI", "--sync-folder", view, "--no-preview");
            Assert.Equal(0, code);
            Assert.Empty(error);
            Assert.Contains("Replaced screen Overview", output);
            Assert.Contains("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", File.ReadAllText(Path.Combine(view, "HMI", "Overview.xml")));
        }

        [Fact]
        public void From_svg_compiles_a_captured_frame_and_its_parameters()
        {
            Write("HMI/Overview.xml", ScreenXml(800, 480));
            Write(".cds-visu/frames/FrameSample.json", "{\"type\":\"frame\",\"golden_template\":\"FrameSample.xml.tmpl\","
                + "\"base_members\":[{\"role\":\"x\",\"value\":\"0\"},{\"role\":\"y\",\"value\":\"0\"},"
                + "{\"role\":\"width\",\"value\":\"100\"},{\"role\":\"height\",\"value\":\"100\"}],"
                + "\"params\":[{\"name\":\"speed\",\"member_id\":111,\"default\":\"10\"}]}");
            Write(".cds-visu/frames/FrameSample.xml.tmpl", "<Single Name=\"VisualElementIdentifier\" Type=\"string\">@@IDENTIFIER@@</Single>\n"
                + "<Single Name=\"X\" Type=\"int\">@@X@@</Single>\n@@PARAM_MEMBERS@@\n");
            var svg = Path.Combine(root, "frame.svg");
            File.WriteAllText(svg, "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"800\" height=\"480\">"
                + "<rect data-cds-type=\"frame\" data-visu=\"FrameSample\" data-param-speed=\"42\" "
                + "x=\"20\" y=\"20\" width=\"100\" height=\"40\" />"
                + "</svg>");
            var (code, output, error) = CliTests.RunLocal("visu", "from-svg", "--svg", svg, "--screen", "Overview",
                "--sync-folder", view, "--folder", "HMI", "--no-preview");
            Assert.True(code == 0, error);
            Assert.Contains("Compiled 1 element(s)", output);
            var xml = File.ReadAllText(Path.Combine(view, "HMI", "Overview.xml"));
            Assert.Contains("GenElemInst_1", xml);
            Assert.Contains("<Single Name=\"Value\" Type=\"string\">42</Single>", xml);
        }

        [Fact]
        public void Add_renders_every_embedded_catalog_type()
        {
            foreach (var type in new[] { "alarm-banner", "button", "combobox", "image-switcher", "label", "lamp", "line", "rectangle", "textfield" })
            {
                Write(type + ".xml", ScreenXml(800, 480));
                var (code, output, error) = CliTests.RunLocal("visu", "add", "--screen", type, "--type", type,
                    "--x", "20", "--y", "20", "--w", "100", "--h", "40", "--sync-folder", view);
                Assert.True(code == 0, type + ": " + error);
                Assert.Contains("GenElemInst_1", output);
                var xml = File.ReadAllText(Path.Combine(view, type + ".xml"));
                var catalog = VisuCatalog.Load(type);
                Assert.Contains("<Single Name=\"VisualElementTypeName\" Type=\"string\">"
                    + catalog["visualElementTypeName"] + "</Single>", xml);
                Assert.Contains("<List Name=\"VisualElemMemberList\"", xml);
            }
        }

        [Fact]
        public void A_textfield_clears_the_flag_that_hides_it_online()
        {
            // CODESYS draws its own text fields with member 2597686782 False; with True the
            // field stays blank in the online visualization, though the editor shows it.
            Write("Field.xml", ScreenXml(800, 480));
            var (code, _, error) = CliTests.RunLocal("visu", "add", "--screen", "Field", "--type", "textfield",
                "--x", "20", "--y", "20", "--w", "100", "--h", "40", "--sync-folder", view);
            Assert.True(code == 0, error);
            var xml = File.ReadAllText(Path.Combine(view, "Field.xml"));
            Assert.Matches(@"<Single Name=""Id"" Type=""long"">2597686782</Single>\s*<Single Name=""Value"" Type=""bool"">False</Single>", xml);
        }

        [Fact]
        public void Describe_shows_the_properties_with_defaults_and_flags()
        {
            var (code, output, _) = CliTests.RunLocal("visu", "describe", "--type", "rectangle");
            Assert.Equal(0, code);
            Assert.Contains("element=VisuFbElemSimple", output);
            Assert.Contains("Settable properties:", output);
            Assert.Matches(@"x kind=\S+ default=\S+ .*\[geometry\]", output);
        }

        [Fact]
        public void Describe_an_unknown_type_names_the_known_ones()
        {
            var (code, _, error) = CliTests.RunLocal("visu", "describe", "--type", "nope");
            Assert.Equal(1, code);
            Assert.Contains("Unknown element type 'nope'. Available: ", error);
            Assert.Contains("button", error);
        }

        [Fact]
        public void Describe_an_element_shows_its_members()
        {
            Write("HMI/Main.xml", ScreenXml(800, 480,
                Element("VisuFbElemSimple", "GenElemInst_1", Geometry(0, 0, 10, 10)),
                Element("VisuFbElemButton", "GenElemInst_2", Geometry(20, 20, 40, 20) + Color(2341735680, -11513776, "Element-Control-Color"))));
            var (code, output, _) = Visu("describe", "--type", "button", "--screen", "Main", "--elem", "1");
            Assert.Equal(0, code);
            Assert.Contains("Element #1: GenElemInst_2 (VisuFbElemButton)", output);
            Assert.Contains("1649127785 20", output);
            Assert.Contains("2341735680 color=-11513776 canonical=Element-Control-Color", output);

            var (outOfRange, _, error) = Visu("describe", "--type", "button", "--screen", "Main", "--elem", "2");
            Assert.Equal(1, outOfRange);
            Assert.Contains("Element index 2 out of range (0..1)", error);
        }

        [Fact]
        public void List_shows_each_element_with_its_geometry()
        {
            Write("HMI/Main.xml", ScreenXml(800, 480,
                Element("VisuFbElemButton", "GenElemInst_1", Geometry(8, 16, 120, 40)),
                Element("VisuFbElemLamp", "GenElemInst_2", "")));
            var (code, output, _) = Visu("list", "--screen", "Main");
            Assert.Equal(0, code);
            Assert.Contains("elements=2", output);
            Assert.Contains("0   VisuFbElemButton GenElemInst_1         8     16    120     40", output);
            Assert.Contains("1   VisuFbElemLamp   GenElemInst_2         -      -      -      -", output);
        }

        [Fact]
        public void Check_passes_a_clean_screen()
        {
            Write("Main.xml", ScreenXml(800, 480,
                Element("VisuFbElemButton", "GenElemInst_1", Geometry(8, 8, 100, 40)),
                Element("VisuFbElemButton", "GenElemInst_2", Geometry(200, 8, 100, 40)),
                // Inside the first one: a composition, not a collision.
                Element("VisuFbElemLamp", "GenElemInst_3", Geometry(12, 12, 20, 20)),
                Element("VisuFbElemLine", "GenElemInst_4", Geometry(0, 0, 800, 480))));
            var (code, output, _) = Visu("check", "--screen", "Main");
            Assert.Equal(0, code);
            Assert.Contains("elements=4 problems=0", output);
        }

        [Fact]
        public void Check_names_every_problem_and_exits_1()
        {
            Write("Main.xml", ScreenXml(200, 100,
                Element("VisuFbElemButton", "Outside", Geometry(150, 80, 100, 40)),
                Element("VisuFbElemButton", "OffCenter", Scalar(1649127785, 0) + Scalar(357335551, 0) + Scalar(2422045748, 40)
                    + Scalar(2134141914, 20) + Scalar(550940142, 99) + Color(2341735680, 0, "")),
                Element("VisuFbElemButton", "NoTextId", Geometry(10, 10, 30, 20) + Scalar(390574330, "Start", "string")),
                Element("VisuFbElemButton", "Bad", Scalar(1649127785, "x", "string"))));
            var (code, output, _) = Visu("check", "--screen", "Main");
            Assert.Equal(1, code);
            Assert.Contains("Outside: X+Width (250) exceeds screen SizeX (200)", output);
            Assert.Contains("Outside: Y+Height (120) exceeds screen SizeY (100)", output);
            Assert.Contains("OffCenter: CenterX 99 != X+W/2 (20)", output);
            Assert.Contains("OffCenter: color member 2341735680 has empty CanonicalName", output);
            Assert.Contains("NoTextId: has non-empty text but no Text ID (823443203)", output);
            Assert.Contains("overlap: OffCenter overlaps NoTextId", output);
            Assert.Contains("Bad: non-numeric geometry", output);
        }

        [Fact]
        public void A_screen_name_in_two_folders_needs_the_folder()
        {
            Write("A/Main.xml", ScreenXml(800, 480));
            Write("B/Main.xml", ScreenXml(800, 480, Element("VisuFbElemButton", "GenElemInst_1", Geometry(0, 0, 10, 10))));
            var (ambiguous, _, error) = Visu("list", "--screen", "Main");
            Assert.Equal(1, ambiguous);
            Assert.Contains("Screen name 'Main' is ambiguous (2 matches); pass --folder", error);

            var (code, output, _) = Visu("list", "--screen", "Main", "--folder", "B");
            Assert.Equal(0, code);
            Assert.Contains("elements=1", output);
        }

        [Fact]
        public void A_missing_screen_is_named()
        {
            var (code, _, error) = Visu("check", "--screen", "Nowhere");
            Assert.Equal(1, code);
            Assert.Contains("Screen file not found: ", error);
        }

        static string Frame(string identifier, string visu, string parameterMembers)
        {
            var node = "<Single Type=\"{node}\" Method=\"IArchivable\">"
                + "<Single Name=\"VisNodeRefs33\" Type=\"string\">" + visu + "</Single>"
                + "<List Name=\"TypeNodeChildren\" Type=\"System.Collections.ArrayList\">"
                + "<Single Type=\"{child}\" Method=\"IArchivable\"><Single Name=\"TypeNodeName\" Type=\"string\">speed</Single>"
                + "<Single Name=\"TypeNodeIdLong\" Type=\"long\">4000000001</Single>"
                + "<Single Name=\"TypeNodeType\" Type=\"{type}\" Method=\"IArchivable\"><Single Name=\"QualifiedName\" Type=\"string\">REAL</Single></Single></Single>"
                + "<Single Type=\"{child}\" Method=\"IArchivable\"><Single Name=\"TypeNodeName\" Type=\"string\">running</Single>"
                + "<Single Name=\"TypeNodeIdLong\" Type=\"long\">4000000002</Single></Single>"
                + "</List></Single>";
            return Element("VisuFbFrame", identifier, Geometry(10, 20, 100, 60) + parameterMembers,
                "<Single Name=\"VisualElementId\" Type=\"int\">7</Single>" + node);
        }

        [Fact]
        public void Capture_frame_writes_a_template_and_the_parameters()
        {
            Write("HMI/Main.xml", ScreenXml(800, 480,
                Frame("GenElemInst_1", "MotorFace", Scalar(4000000001, "GVL.speed", "string") + Scalar(4000000002, "GVL.run", "string")),
                Frame("GenElemInst_2", "MotorFace", Scalar(4000000001, "GVL.speed2", "string")),
                Frame("GenElemInst_3", "PumpFace", "")));
            Write("Broken.xml", "<Single>");
            var (code, output, _) = Visu("capture-frame", "--visu", "MotorFace");
            Assert.Equal(0, code);
            Assert.Contains("params=2", output);
            Assert.Contains("params: speed, running", output);
            Assert.Contains("Broken.xml: Could not parse screen XML", output);

            var frames = Path.Combine(view, ".cds-visu", "frames");
            var template = File.ReadAllText(Path.Combine(frames, "MotorFace.xml.tmpl"));
            Assert.Contains(">@@X@@<", template);
            Assert.Contains(">@@CENTER_Y@@<", template);
            Assert.Contains(">@@IDENTIFIER@@<", template);
            Assert.Contains(">@@VISUAL_ELEMENT_ID@@<", template);
            Assert.Contains("\n                @@PARAM_MEMBERS@@\n            </List>", template);
            // The instance that sets fewer parameters is the template, and its
            // parameter members leave it whole.
            Assert.DoesNotContain("GVL.speed", template);
            Assert.DoesNotContain("4000000001</Single><Single Name=\"Value\"", template);

            var catalog = (IDictionary<string, object>)Json.Parse(File.ReadAllText(Path.Combine(frames, "MotorFace.json")));
            Assert.Equal("MotorFace.xml.tmpl", catalog["golden_template"]);
            var parameters = ((IList<object>)catalog["params"]).Cast<IDictionary<string, object>>().ToList();
            Assert.Equal("speed", parameters[0]["name"]);
            Assert.Equal("REAL", parameters[0]["iec_type"]);
            Assert.Equal("GVL.speed2", parameters[0]["default"]);
            Assert.Equal("", parameters[1]["default"]);
        }

        [Fact]
        public void Capture_frame_of_an_unused_visu_says_so()
        {
            Write("Main.xml", ScreenXml(800, 480, Frame("GenElemInst_1", "PumpFace", "")));
            var (code, _, error) = Visu("capture-frame", "--visu", "MotorFace", "--screen", "Main");
            Assert.Equal(1, code);
            Assert.Contains("No frame showing 'MotorFace' found in ", error);
        }
    }
}
