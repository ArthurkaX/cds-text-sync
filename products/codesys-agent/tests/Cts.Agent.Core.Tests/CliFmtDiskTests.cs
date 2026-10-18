using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Fact]
        public void Fmt_disk_lays_out_the_files_in_place_and_keeps_their_line_ends()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-fmt-" + Path.GetRandomFileName());
            var file = Path.Combine(folder, "project-view", "Application", "FB_Pump.st");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            try
            {
                var text = "(* cds-text-sync: LinkAlways *)\nFUNCTION_BLOCK FB_Pump\nVAR\n    xRun : BOOL;\n    nCount : INT;\nEND_VAR\n// --- implementation ---\nIF xRun THEN\nnCount := nCount + 1; xRun := nCount < 10;\nEND_IF\nEND_FUNCTION_BLOCK\n\n"
                    + "METHOD M_Reset : BOOL\nVAR_INPUT\n    xAll : BOOL;\n    nTo : INT;\nEND_VAR\n// --- implementation ---\nnCount := nTo; M_Reset := TRUE;\nEND_METHOD\n\n"
                    + "ACTION A_Stop:\nxRun := FALSE;\nEND_ACTION\n";
                File.WriteAllText(file, text.Replace("\n", "\r\n"));
                var (code, output, _) = Run(new FakeHost(), "fmt", "--disk", "--sync-folder", folder);
                Assert.True(code == 0, output);
                Assert.StartsWith("ok fmt objects=3 to_fix=2 lines=6", output);
                Assert.Contains("\nFB_Pump: 3 line(s)\n", output);
                Assert.Contains("\nFB_Pump.M_Reset: 3 line(s)", output);
                Assert.Equal(text.Replace("\n", "\r\n"), File.ReadAllText(file));
                Assert.StartsWith("ok fmt objects=1 to_fix=1 lines=3", Run(new FakeHost(), "fmt", "M_Reset", "--disk", "--sync-folder", folder).output);
                (code, output, _) = Run(new FakeHost(), "fmt", "--disk", "--sync-folder", folder, "--write");
                Assert.True(code == 0, output);
                Assert.Contains(" written=2", output);
                Assert.Contains("Next: only the files changed; cts import carries the new layout into the IDE", output);
                Assert.Equal(("(* cds-text-sync: LinkAlways *)\nFUNCTION_BLOCK FB_Pump\nVAR\n    xRun   : BOOL;\n    nCount : INT;\nEND_VAR\n// --- implementation ---\nIF xRun THEN\n    nCount := nCount + 1;\n    xRun := nCount < 10;\nEND_IF\nEND_FUNCTION_BLOCK\n\n"
                    + "METHOD M_Reset : BOOL\nVAR_INPUT\n    xAll : BOOL;\n    nTo  : INT;\nEND_VAR\n// --- implementation ---\nnCount := nTo;\nM_Reset := TRUE;\nEND_METHOD\n\n"
                    + "ACTION A_Stop:\nxRun := FALSE;\nEND_ACTION\n").Replace("\n", "\r\n"), File.ReadAllText(file));
                Assert.StartsWith("ok fmt objects=3 to_fix=0 lines=0", Run(new FakeHost(), "fmt", "--disk", "--sync-folder", folder).output);
                var (refused, _, error) = Run(new FakeHost(), "fmt", "--disk", "--sync-folder", folder, "--guid", "0f6c1c1e-0000-0000-0000-000000000000");
                Assert.Equal(1, refused);
                Assert.Contains("with --disk give NAME", error);
            }
            finally { Directory.Delete(folder, true); }
        }
    }
}
