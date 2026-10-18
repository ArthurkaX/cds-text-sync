using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class AnalysisReportTests
    {
        static string Folder()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-analysis-" + Path.GetRandomFileName());
            Directory.CreateDirectory(Path.Combine(folder, "project-view", "POUs"));
            File.WriteAllText(Path.Combine(folder, "project-view", "POUs", "PRG_Main.st"),
                "// Main program documentation.\nPROGRAM PRG_Main\nVAR\n    nUnused : INT;\nEND_VAR\n// --- implementation ---\n// n := 0;\n");
            return folder;
        }

        [Fact]
        public void The_window_reads_what_cts_analyze_answers_and_files_its_decisions_through_triage()
        {
            var folder = Folder();
            try
            {
                var (code, output, _) = CliTests.RunLocal("analyze", "--workspace", folder, "--json", "--fail-on", "never");
                Assert.Equal(0, code);
                var run = AnalysisReport.Parse(output);
                Assert.Equal(Path.GetFullPath(folder), run.Workspace);
                Assert.Equal(Path.Combine(Path.GetFullPath(folder), "project-view"), run.View);
                Assert.True(run.Complete);
                var unused = run.Findings.Single(f => f.RuleId == "CTS0013");
                Assert.Equal("POUs/PRG_Main.st", unused.Path.Replace('\\', '/'));
                Assert.Equal(4, unused.Line);
                Assert.Equal(new List<int> { 4 }, unused.Lines);
                Assert.StartsWith("POUs", unused.Where);
                Assert.EndsWith(":4", unused.Where);
                Assert.Contains(run.Findings.Count + " finding(s): ", run.Summary);

                var rules = AnalysisReport.Rules(CliTests.RunLocal("analyze", "rules", "--workspace", folder, "--doc", "--json").output);
                Assert.True(rules.Single(r => r.Id == "CTS0013").Enabled);
                Assert.Contains("```st bad", rules.Single(r => r.Id == "CTS0013").Doc);
                Assert.DoesNotContain("since:", rules.Single(r => r.Id == "CTS0013").Doc);
                Assert.StartsWith("#", rules.Single(r => r.Id == "CTS0013").Doc);

                var decisions = Path.Combine(folder, "decisions.json");
                File.WriteAllText(decisions, AnalysisReport.Decisions(new[] { unused }, "suppress", " kept for the HMI "));
                Assert.Equal(0, CliTests.RunLocal("analyze", "triage", "--workspace", folder, "--apply", decisions).code);
                var after = AnalysisReport.Parse(CliTests.RunLocal("analyze", "--workspace", folder, "--json", "--fail-on", "never").output);
                Assert.DoesNotContain(after.Findings, f => f.RuleId == "CTS0013");
                Assert.Equal(1, after.Suppressed);
                Assert.Contains(", 1 suppressed", after.Summary);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Shown_keeps_the_severity_and_the_text_asked_for()
        {
            var findings = AnalysisReport.Parse(@"{""findings"": [
                {""rule_id"": ""CTS0001"", ""rule_title"": ""Commented-out code"", ""severity"": ""suspicious"", ""message"": ""code in a comment"", ""location"": {""path"": ""POUs/A.st"", ""line"": 3}},
                {""rule_id"": ""CTS0013"", ""rule_title"": ""Declared symbol not referenced"", ""severity"": ""style"", ""message"": ""nUnused"", ""location"": {""path"": ""POUs/B.st"", ""line"": 5, ""end_line"": 7}},
                {""rule_id"": ""CTS0020"", ""rule_title"": ""Repeated"", ""severity"": ""danger"", ""message"": ""twice"", ""location"": {""path"": ""POUs/C.st"", ""line"": 2}, ""member_lines"": [2, 9]}
            ], ""diagnostics"": [{}], ""complete"": false}").Findings;
            Assert.Equal(new[] { "CTS0020", "CTS0001", "CTS0013" }, AnalysisReport.Shown(findings, null, null).Select(f => f.RuleId));
            Assert.Equal(new[] { "CTS0013" }, AnalysisReport.Shown(findings, "style", null).Select(f => f.RuleId));
            Assert.Equal(new[] { "CTS0001" }, AnalysisReport.Shown(findings, null, "a.st").Select(f => f.RuleId));
            Assert.Equal(new[] { "CTS0013" }, AnalysisReport.Shown(findings, null, "NUNUSED").Select(f => f.RuleId));
            Assert.Equal(3, AnalysisReport.Shown(findings, null, " ").Count);
            Assert.Equal("POUs/B.st:5-7", findings[1].Where);
            Assert.Equal("POUs/C.st:2 (x2)", findings[2].Where);
            Assert.Equal(new List<int> { 2, 9 }, findings[2].Lines);
        }

        [Fact]
        public void An_excerpt_numbers_the_lines_marks_the_finding_and_merges_the_windows_that_touch()
        {
            var lines = Enumerable.Range(1, 30).Select(i => "line" + i).ToList();
            var text = AnalysisReport.Excerpt(lines, new[] { 3, 6, 20, 99 }, 2);
            Assert.Equal(
                "   1  line1\n   2  line2\n>  3  line3\n   4  line4\n   5  line5\n>  6  line6\n   7  line7\n   8  line8\n...\n  18  line18\n  19  line19\n> 20  line20\n  21  line21\n  22  line22\n",
                text);
            Assert.Equal("", AnalysisReport.Excerpt(lines, new[] { 0, 31 }, 2));
        }
    }
}
