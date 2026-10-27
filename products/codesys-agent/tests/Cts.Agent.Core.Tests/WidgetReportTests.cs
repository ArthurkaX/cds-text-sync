using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // The problem report the quick window makes, and what it leaves out.
    public class WidgetReportTests
    {
        static readonly DateTime Now = new DateTime(2026, 10, 15, 19, 40, 12);

        static WidgetRun Run(string[] args, int exit, string line, string output = "", string errors = "")
        {
            return new WidgetRun { Started = Now.AddSeconds(-5), Args = args, ExitCode = exit, Milliseconds = 2300, Output = output, Errors = errors, Line = line };
        }

        static Redaction Known() => new Redaction(new Dictionary<string, string>
        {
            { "PumpStation", "project" }, { "Pump_FB", "object" }, { "feature-valves", "branch" }, { "jdoe", "user" }, { "Application", "object" },
        });

        [Fact]
        public void TheReportNamesNoObjectBranchPathOrTyped()
        {
            var runs = new List<WidgetRun>
            {
                Run(new[] { "compare" }, 0, "ok compare unchanged=46"),
                Run(new[] { "commit", "-m", "fix Pump_FB scaling for the client" }, 0, "ok commit files=2"),
                Run(new[] { "checkout", "feature-valves", "--disk-only" }, 1, "error checkout cause=refused — 'feature-valves' has local changes",
                    "error checkout cause=refused\nNext: cts checkout --help\n",
                    "progress: reading\n[ERROR] Pump_FB.st in C:\\Users\\jdoe\\Projects\\PumpStation differs\n"),
                Run(new[] { "project", "update" }, 0, "ok project-update"),
            };
            var log = new[]
            {
                "2026-10-15 19:39:00.000 widget: Alt+Q opens it",
                "2026-10-15 19:39:00.500 widget: cts branch Valve..Secret: error branch cause=refused",
                "2026-10-15 19:39:01.000 handler object.text failed: System.InvalidOperationException: no object 'Pump_FB' at \\\\server\\share\\x\n   at Cts.Agent.Ide.Read()",
            };
            var diag = "ok diag cts=\"4.0.0 (commit 7ae86e8e)\"\nagent: ide=CODESYS 3.5.22.40  project_open=yes\nfolder tracked: 56";
            var report = WidgetReport.Build(Now, diag, new[] { "4 Switch branch", "2 feature-valves" },
                "error checkout cause=refused — 'feature-valves' has local changes", runs, log, Known());
            foreach (var secret in new[] { "Pump", "Secret", "feature-valves", "jdoe", "Users", "client", "server", "share" })
                Assert.DoesNotContain(secret, report);
            var lines = report.Replace("\r\n", "\n").Split('\n').ToList();
            Assert.Equal("cds-text-sync problem report, 2026-10-15 19:40:12", lines[0]);
            Assert.Contains("ok diag cts=\"4.0.0 (commit 7ae86e8e)\"", lines);
            Assert.Contains("agent: ide=CODESYS 3.5.22.40  project_open=yes", lines);
            Assert.Contains("chosen: 4 Switch branch > 2 <branch>", lines);
            Assert.Contains("shown: error checkout cause=refused — '<branch>' has local changes", lines);
            Assert.Contains("command: cts checkout <arg> --disk-only  (exit 1, 2.3 s, at 19:40:07)", lines);
            Assert.Contains("[ERROR] <file> in <path> differs", lines);
            Assert.DoesNotContain(lines, line => line.StartsWith("progress:", StringComparison.Ordinal));
            var earlier = lines.IndexOf("--- runs of this IDE session ---");
            Assert.Equal("19:40:07 cts compare: ok compare unchanged=46", lines[earlier + 1]);
            Assert.Equal("19:40:07 cts commit -m <arg>: ok commit files=2", lines[earlier + 2]);
            Assert.Equal("19:40:07 cts project update: ok project-update", lines[earlier + 3]);
            var faults = lines.IndexOf("--- agent errors of this IDE session ---");
            Assert.StartsWith("2026-10-15 19:39:01.000 handler object.text failed: System.InvalidOperationException: no object '<object>' at <path>", lines[faults + 1]);
            Assert.Equal("   at Cts.Agent.Ide.Read()", lines[faults + 2]);
            Assert.DoesNotContain("Alt+Q", report);
        }

        [Fact]
        public void FromTheMenuTheLastFailedRunIsTheOneAndEmptySectionsAreLeftOut()
        {
            var runs = new List<WidgetRun> { Run(new[] { "merge", "x", "--preview" }, 1, "error merge cause=refused"), Run(new[] { "compare" }, 0, "ok compare") };
            var report = WidgetReport.Build(Now, "ok diag", null, null, runs, new string[0], Known());
            Assert.Contains("command: cts merge <arg> --preview  (exit 1", report);
            Assert.DoesNotContain("shown:", report);
            Assert.DoesNotContain("agent errors", report);
            var none = WidgetReport.Build(Now, "", null, null, new List<WidgetRun>(), null, Known());
            Assert.DoesNotContain("---", none);
        }

        [Fact]
        public void RedactionReplacesPathsAddressesAndQuotedTextAndKeepsCommonNames()
        {
            var redaction = Known();
            Assert.Equal("open \"<path>\" and <path> then <url>", redaction.Text("open \"C:\\My Projects\\a b\" and D:\\x\\y.txt then https://git.example.com/acme/plant.git"));
            Assert.Equal("push to <url> from <address>, mail <email>", redaction.Text("push to git@host:acme/plant.git from 192.168.1.9:11740, mail a.b@acme.com"));
            Assert.Equal("CODESYS 3.5.22.40 at <address>", redaction.Text("CODESYS 3.5.22.40 at 10.0.0.5"));
            Assert.Equal("set '…', cause=\"no sync base\", kept '<object>' '--force'", redaction.Text("set 'Motor speed', cause=\"no sync base\", kept 'Pump_FB' '--force'"));
            Assert.Equal("<object>.Application stays, Pump_FBX too", redaction.Text("Pump_FB.Application stays, Pump_FBX too"));
            Assert.Equal("<file> and <file>", redaction.Text("POUs/Pump.st and Main.xml"));
            Assert.Equal("analyze rules --json --since=<arg> <arg>", Redaction.Command(new[] { "analyze", "rules", "--json", "--since=main", "x" }));
            Assert.Equal("write <arg> <arg>", Redaction.Command(new[] { "write", "GVL.speed", "-5" }));
        }

#if DEBUG
        [Fact]
        public void DriveStepsParseIntoKindsAndRefuseUnknownOnes()
        {
            var steps = WidgetDrive.Parse(new object[] { "open", "5", "+", "enter", "type:new branch", "wait:200", "idle", "copy", "ctrl+c", "close" });
            Assert.Equal(new[] { DriveKind.Open, DriveKind.Char, DriveKind.Char, DriveKind.Key, DriveKind.Type, DriveKind.Wait, DriveKind.Idle, DriveKind.Copy, DriveKind.Key, DriveKind.Close },
                steps.Select(step => step.Kind));
            Assert.Equal("new branch", steps[4].Text);
            Assert.Equal(200, steps[5].Milliseconds);
            Assert.Throws<ArgumentException>(() => WidgetDrive.Parse(new object[] { "jump" }));
            Assert.Throws<ArgumentException>(() => WidgetDrive.Parse(new object[] { "wait:soon" }));
            Assert.Throws<ArgumentException>(() => WidgetDrive.Parse(null));
        }
#endif
    }
}
