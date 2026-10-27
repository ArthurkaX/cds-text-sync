using System;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class CliDiagramTests : IDisposable
    {
        readonly string folder = Path.Combine(Path.GetTempPath(), "cts-diagram-" + Path.GetRandomFileName());
        readonly string view;

        public CliDiagramTests()
        {
            view = Path.Combine(folder, "project-view");
            Directory.CreateDirectory(Path.Combine(view, "App", "Task Configuration"));
            File.WriteAllText(Path.Combine(view, "App", "Task Configuration", "MainTask.xml"),
                "<Single><List Name=\"PouList\"><Single><Single Name=\"Name\" Type=\"string\">MAIN</Single></Single><Single><Single Name=\"Name\" Type=\"string\">CFC_Main</Single></Single></List></Single>");
            Source("App/MAIN.st", "PROGRAM MAIN\nVAR\n    fbLine : FB_Line;\nEND_VAR\n// --- implementation ---\nfbLine(xStart := TRUE);\nF_Scale(1.0);\n");
            Source("App/FB_Base.st", "FUNCTION_BLOCK FB_Base\nVAR_INPUT\n    xStart : BOOL;\nEND_VAR\nVAR_OUTPUT\n    sError : STRING(80);\nEND_VAR\n// --- implementation ---\nM_Clear();\nEND_FUNCTION_BLOCK\n\n"
                + "METHOD M_Clear : BOOL\n// --- implementation ---\nM_Clear := TRUE;\nEND_METHOD\n");
            Source("App/FB_Motor.st", "FUNCTION_BLOCK FB_Motor EXTENDS FB_Base IMPLEMENTS I_Drive\nVAR_IN_OUT\n    stCell : ST_Cell;\nEND_VAR\n// --- implementation ---\nEND_FUNCTION_BLOCK\n");
            Source("App/I_Drive.st", "INTERFACE I_Drive\nEND_INTERFACE\n");
            Source("App/ST_Cell.st", "TYPE ST_Cell :\nSTRUCT\n    rLevel : REAL;\nEND_STRUCT\nEND_TYPE\n");
            Source("App/FB_Line.st", "FUNCTION_BLOCK FB_Line\nVAR_INPUT\n    xStart : BOOL;\nEND_VAR\nVAR\n    aMotors : ARRAY[1..2] OF FB_Motor;\n    fbFirst : FB_Base;\n    fbSecond : FB_Base;\n    fbThird : FB_Base;\n    fbFourth : FB_Base;\n    pDrive : POINTER TO FB_Base;\n    itfDrive : I_Drive;\n    tonWait : TON;\nEND_VAR\n"
                + "// --- implementation ---\nfbFirst(xStart := xStart);\nEND_FUNCTION_BLOCK\n");
            // Nine valves a program runs and that each hold a cell.
            for (var valve = 1; valve <= 9; valve++)
                Source("App/FB_Valve" + valve + ".st", "FUNCTION_BLOCK FB_Valve" + valve + "\nVAR\n    stCell : ST_Cell;\nEND_VAR\n// --- implementation ---\nEND_FUNCTION_BLOCK\n");
            Source("App/PRG_Valves.st", "PROGRAM PRG_Valves\nVAR\n" + string.Concat(Enumerable.Range(1, 9).Select(valve => "    fbValve" + valve + " : FB_Valve" + valve + ";\n"))
                + "END_VAR\n// --- implementation ---\n" + string.Concat(Enumerable.Range(1, 9).Select(valve => "fbValve" + valve + "();\n")));
            Source("App/F_Scale.st", "FUNCTION F_Scale : REAL\nVAR_INPUT\n    rIn : REAL;\nEND_VAR\n// --- implementation ---\nF_Scale := rIn;\nEND_FUNCTION\n");
        }

        public void Dispose()
        {
            if (Directory.Exists(folder)) Directory.Delete(folder, true);
        }

        void Source(string path, string text) => File.WriteAllText(Path.Combine(view, path), text);

        [Fact]
        public void A_class_diagram_shows_what_a_block_extends_implements_holds_and_refers_to()
        {
            var (code, output, _) = CliTests.RunLocal("diagram", "classes", "FB_Line", "--workspace", folder);
            Assert.True(code == 0, output);
            Assert.Contains("classDiagram", output);
            Assert.Contains("    FB_Line *-- FB_Motor : aMotors[1..2]", output);
            Assert.Contains("    FB_Line --> FB_Base : pDrive", output);
            Assert.Contains("    FB_Line --> I_Drive : itfDrive", output);
            Assert.Contains("    MAIN *-- FB_Line : fbLine", output);
            // Four blocks of one type: one line, three names and the count of the rest.
            Assert.Contains("    FB_Line *-- FB_Base : fbFirst, fbSecond, fbThird +1", output);
            // Two relations away: not drawn at depth 1.
            Assert.DoesNotContain("class ST_Cell", output);
            // Two of its neighbours: no line between them.
            Assert.DoesNotContain("FB_Base <|-- FB_Motor", output);
            (_, output, _) = CliTests.RunLocal("diagram", "classes", "FB_Motor", "--workspace", folder);
            Assert.Contains("    FB_Base <|-- FB_Motor", output);
            Assert.Contains("    I_Drive <|.. FB_Motor", output);
            Assert.Contains("    FB_Motor --> ST_Cell : stCell", output);
            // A type with parentheses would read as a method.
            Assert.Contains("        +out sError : STRING[80]", output);
            Assert.Contains("        +M_Clear() BOOL", output);
            Assert.Contains("        <<interface>>", output);
            // Nine blocks that hold a cell and nothing else drawn: one list.
            (_, output, _) = CliTests.RunLocal("diagram", "classes", "ST_Cell", "--workspace", folder);
            Assert.Contains("classes=11 relations=10", output);
            Assert.Contains("    class list__1[\"9 function blocks\"] {\n        FB_Valve1 : stCell\n", output);
            Assert.Contains("    list__1 *-- ST_Cell", output);
            Assert.Contains("    FB_Motor --> ST_Cell : stCell", output);
            Assert.DoesNotContain("class FB_Valve1", output);
            // The whole project: inheritance only, no members.
            (_, output, _) = CliTests.RunLocal("diagram", "classes", "--workspace", folder);
            Assert.Contains("classes=3 relations=2", output);
            Assert.DoesNotContain("aMotors", output);
            (code, _, var error) = CliTests.RunLocal("diagram", "classes", "F_Scale", "--workspace", folder);
            Assert.Equal(1, code);
            Assert.Contains("no function block, interface, structure or program is named F_Scale", error);
        }

        [Fact]
        public void A_call_diagram_runs_from_the_tasks_down_and_says_what_it_leaves_out()
        {
            var (code, output, _) = CliTests.RunLocal("diagram", "calls", "--workspace", folder);
            Assert.True(code == 0, output);
            Assert.Contains("ok diagram-calls tasks=1 objects=5 calls=5 cut=1", output);
            Assert.Contains("    n1{{\"task MainTask\"}}", output);
            Assert.Contains("    n2[[\"MAIN\"]]", output);
            // A program the task calls that has no text in the folder.
            Assert.Contains("    n3[\"CFC_Main (no text)\"]", output);
            Assert.Contains("    n5(\"F_Scale\")", output);
            // Three calls down from the task: the method FB_Base calls is left out.
            Assert.Contains("    n6[\"FB_Base +1\"]", output);
            (_, output, _) = CliTests.RunLocal("diagram", "calls", "--depth", "4", "--workspace", folder);
            Assert.Contains("([\"FB_Base.M_Clear\"])", output);
            (_, output, _) = CliTests.RunLocal("diagram", "calls", "--from", "MAIN", "--depth", "1", "--workspace", folder);
            Assert.Contains("ok diagram-calls tasks=0 objects=3 calls=2 cut=1", output);
            Assert.Contains("    n2[\"FB_Line +1\"]", output);
            // Nine blocks the program runs that call nothing: one list.
            (_, output, _) = CliTests.RunLocal("diagram", "calls", "--from", "PRG_Valves", "--workspace", folder);
            Assert.Contains("ok diagram-calls tasks=0 objects=10 calls=9 cut=0", output);
            Assert.Contains("    n2[\"9 function blocks<br>FB_Valve1<br>FB_Valve2", output);
            Assert.Contains("    n1 --> n2\n", output + "\n");
            Assert.DoesNotContain("n3", output);
            (code, _, var error) = CliTests.RunLocal("diagram", "calls", "--from", "Nothing", "--workspace", folder);
            Assert.Equal(1, code);
            Assert.Contains("no task or object is named Nothing", error);
        }

        [Fact]
        public void The_view_is_one_page_with_mermaid_and_every_drawing_in_it()
        {
            var page = Path.Combine(folder, "page.html");
            var (code, output, _) = CliTests.RunLocal("diagram", "view", "--out", page, "--no-open", "--workspace", folder);
            Assert.True(code == 0, output);
            Assert.Contains("ok diagram-view classes=", output);
            Assert.Contains("open " + page + " in a browser", output);
            var html = File.ReadAllText(page);
            Assert.Contains("mermaid", html);
            Assert.DoesNotContain("/*cts:", html);
            Assert.Contains("\"calls|MainTask|3\":\"flowchart TD", html);
            Assert.Contains("\"classes|FB_Line|1\":\"classDiagram", html);
            // A caller counts the project's objects it calls.
            Assert.Contains("{\"name\":\"MAIN\",\"kind\":\"PROGRAM\",\"calls\":2}", html);
            // Every "<" escaped: no text in the data can close the script it sits in.
            Assert.Contains("9 function blocks\\u003cbr>FB_Valve1", html);
        }
    }
}
