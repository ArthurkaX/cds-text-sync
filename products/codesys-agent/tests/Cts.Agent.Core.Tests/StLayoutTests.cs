using System;
using System.Linq;
using System.IO;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public class StLayoutTests
    {
        [Fact]
        public void Part_lines_are_placed_inside_their_st_block()
        {
            var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            var path = Path.Combine(directory, "FB_Motor.st");
            try
            {
                File.WriteAllText(path, "(* cds-text-sync: LinkAlways *)\nFUNCTION_BLOCK FB_Motor\nVAR\n xRun : BOOL;\nEND_VAR\n// --- implementation ---\nxRun := FALSE;\nEND_IF\nEND_FUNCTION_BLOCK\n\nMETHOD M_Run : BOOL\nVAR\n xRun : BOOL;\nEND_VAR\n// --- implementation ---\nxRun := FALSE;\nEND_METHOD\n\nACTION Reset:\nxRun := FALSE;\nEND_ACTION\n\nPROPERTY IsReady : BOOL\nGET\n// --- implementation ---\nxRun := FALSE;\nEND_GET\nEND_PROPERTY\n\nPROPERTY IsIdle : BOOL\nGET\n// --- implementation ---\nxRun := FALSE;\nEND_GET\nEND_PROPERTY\n");
                var view = StViewReader.Read(directory);
                Assert.Empty(view.Errors);
                var owner = view.Objects.First(o => o.Kind == "FUNCTION_BLOCK");
                var method = view.Objects.First(o => o.Path.Last() == "M_Run");
                var action = view.Objects.First(o => o.Kind == "ACTION");
                var ready = view.Objects.First(o => o.Path.Last() == "Get" && o.Path[o.Path.Length - 2] == "IsReady");
                var idle = view.Objects.First(o => o.Path.Last() == "Get" && o.Path[o.Path.Length - 2] == "IsIdle");
                Assert.Equal(7, StViewReader.FindLine(owner, "implementation", "xRun := FALSE;", 1));
                Assert.Equal(16, StViewReader.FindLine(method, "implementation", "xRun := FALSE;", 1));
                Assert.Equal(0, StViewReader.FindLine(method, "implementation", "missing", 1));
                Assert.Equal(2, StViewReader.FindLine(owner, "declaration", "FUNCTION_BLOCK FB_Motor", 1));
                Assert.Equal(20, StViewReader.FindLine(action, "implementation", "xRun := FALSE;", 1));
                Assert.Equal(26, StViewReader.FindLine(ready, "implementation", "xRun := FALSE;", 1));
                Assert.Equal(33, StViewReader.FindLine(idle, "implementation", "xRun := FALSE;", 1));
                Assert.Equal("LinkAlways", owner.Settings.Keys.Single());
                File.WriteAllText(path, "extra\n" + File.ReadAllText(path));
                Assert.Empty(StViewReader.Read(directory).Errors);
            }
            finally { Directory.Delete(directory, true); }
        }

        [Fact]
        public void Reader_names_members_after_their_access_modifiers()
        {
            var text = "FUNCTION_BLOCK FB_Link\n// --- implementation ---\n;\nEND_FUNCTION_BLOCK\n\nMETHOD PRIVATE Cleanup : BOOL\n// --- implementation ---\n;\nEND_METHOD\n\nMETHOD PUBLIC FINAL Send : BOOL\n// --- implementation ---\n;\nEND_METHOD\n\nPROPERTY PROTECTED Ready : BOOL\nGET\n// --- implementation ---\n;\nEND_GET\nEND_PROPERTY\n";
            var view = StViewReader.ReadFile("FB_Link.st", System.Text.Encoding.UTF8.GetBytes(text));
            Assert.Empty(view.Errors);
            Assert.Equal(new[] { "FB_Link", "FB_Link/Cleanup", "FB_Link/Send", "FB_Link/Ready", "FB_Link/Ready/Get" }, view.Objects.Select(item => item.Key).ToArray());
        }

        [Fact]
        public void Reader_normalizes_bom_and_crlf_and_reports_malformed_files_atomically()
        {
            var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                var valid = "PROGRAM P\r\n// --- implementation ---\r\nx := TRUE;\r\nEND_PROGRAM\r\n";
                File.WriteAllText(Path.Combine(directory, "P.st"), valid, new System.Text.UTF8Encoding(true));
                Directory.CreateDirectory(Path.Combine(directory, ".hidden"));
                File.WriteAllText(Path.Combine(directory, ".hidden", "Ignored.st"), "not ST");
                File.WriteAllText(Path.Combine(directory, "Broken.st"), "FUNCTION_BLOCK Broken\nEND_FUNCTION_BLOCK\n\nMETHOD M\nx := 1;\n");
                File.WriteAllText(Path.Combine(directory, "Missing.st"), "PROGRAM Missing\n");
                var result = StViewReader.Read(directory);
                Assert.Equal(2, result.Errors.Count);
                Assert.Contains(result.Errors, error => error.File == "Broken.st");
                Assert.Contains(result.Errors, error => error.File == "Missing.st"
                    && error.Reason.Contains("cts guide commands --section \"Files on disk\""));
                Assert.DoesNotContain(result.Objects, item => item.Path.Last() == "Broken");
                var program = Assert.Single(result.Objects);
                Assert.Equal("PROGRAM", program.Kind);
                Assert.Equal("x := TRUE;", program.Implementation);
                Assert.Equal(3, program.ImplementationLine);
                Assert.Equal("P.st", program.File);
            }
            finally { Directory.Delete(directory, true); }
        }

        [Fact]
        public void Reader_takes_the_old_member_file_layout()
        {
            var directory = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                File.WriteAllText(Path.Combine(directory, "FB_Valve.P_Open.Get.st"), "GET\n// --- implementation ---\nP_Open := TRUE;\n");
                var result = StViewReader.Read(directory);
                Assert.Empty(result.Errors);
                var item = Assert.Single(result.Objects);
                Assert.Equal(new[] { "FB_Valve", "P_Open", "Get" }, item.Path);
                Assert.Equal("GET", item.Kind);
                Assert.Equal("P_Open := TRUE;", item.Implementation);
            }
            finally { Directory.Delete(directory, true); }
        }
    }
}
