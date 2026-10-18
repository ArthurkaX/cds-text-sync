using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // What the quick window's Copy puts on the clipboard after a failure.
    public class WidgetReportTests
    {
        static readonly DateTime Now = new DateTime(2026, 10, 15, 19, 40, 12);

        static WidgetRun Run(string command, int exit, string line, string output = "", string errors = "")
        {
            return new WidgetRun { Started = Now.AddSeconds(-5), CommandLine = command, ExitCode = exit, Milliseconds = 2300, Output = output, Errors = errors, Line = line };
        }

        static List<KeyValuePair<string, string>> Facts()
        {
            return new List<KeyValuePair<string, string>>
            {
                new KeyValuePair<string, string>("project", "P:\\work\\demo.project"),
                new KeyValuePair<string, string>("state", ""),
                new KeyValuePair<string, string>("branch", "master  fix scaling · 14.10 16:50"),
            };
        }

        [Fact]
        public void TheFailedRunIsWholeAndTheEarlierRunsOneLineEach()
        {
            var runs = new List<WidgetRun>
            {
                Run("compare", 0, "ok compare unchanged=46"),
                Run("tool --json", 0, "cts exited 0"),
                Run("checkout feature --disk-only", 1, "error checkout cause=refused — no such branch",
                    "error checkout cause=refused\nNext: cts checkout --help\n", "progress: reading\n[ERROR] no such branch\n"),
                Run("compare", 0, "ok compare unchanged=46 again"),
            };
            var report = WidgetReport.Build(Now, Facts(), new[] { "5 Branches", "2 feature" }, runs, "error checkout cause=refused — no such branch");
            var lines = report.Replace("\r\n", "\n").Split('\n').ToList();
            Assert.Equal("cds-text-sync quick window, 2026-10-15 19:40:12", lines[0]);
            Assert.Contains("project: P:\\work\\demo.project", lines);
            Assert.DoesNotContain(lines, line => line.StartsWith("state:", StringComparison.Ordinal));
            Assert.Contains("chosen: 5 Branches > 2 feature", lines);
            Assert.Contains("command: cts checkout feature --disk-only  (exit 1, 2.3 s, at 19:40:07)", lines);
            var output = lines.IndexOf("--- output ---");
            Assert.Equal("Next: cts checkout --help", lines[output + 2]);
            var errors = lines.IndexOf("--- errors ---");
            Assert.Equal("[ERROR] no such branch", lines[errors + 1]);
            Assert.DoesNotContain(lines, line => line.StartsWith("progress:", StringComparison.Ordinal));
            var earlier = lines.IndexOf("--- earlier in this window ---");
            Assert.Equal("19:40:07 cts compare: ok compare unchanged=46", lines[earlier + 1]);
            Assert.Equal("19:40:07 cts tool --json: ok", lines[earlier + 2]);
            Assert.Equal("19:40:07 cts compare: ok compare unchanged=46 again", lines[earlier + 3]);
        }

        [Fact]
        public void AFailureNoRunShowedHasNoCommandAndEmptySectionsAreLeftOut()
        {
            var report = WidgetReport.Build(Now, Facts(), new string[0], new List<WidgetRun>(), "cds-text-sync.json is unreadable: fix the file");
            Assert.Contains("shown: cds-text-sync.json is unreadable: fix the file", report);
            Assert.DoesNotContain("command:", report);
            Assert.DoesNotContain("---", report);
            Assert.DoesNotContain("chosen:", report);
        }

        [Fact]
        public void WithoutAMatchingLineTheLatestFailedRunIsTheOne()
        {
            var runs = new List<WidgetRun> { Run("merge x --preview", 1, "error merge cause=refused"), Run("compare", 0, "ok compare") };
            var report = WidgetReport.Build(Now, Facts(), null, runs, "merge preview failed");
            Assert.Contains("command: cts merge x --preview  (exit 1", report);
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
