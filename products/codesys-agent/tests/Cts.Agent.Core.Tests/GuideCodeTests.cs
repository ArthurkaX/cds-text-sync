using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Analysis;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // An agent copies the ST a guide shows: cts analyze finds no danger in
    // it.
    public sealed class GuideCodeTests
    {
        static readonly Regex Block = new Regex(@"```iecst\s*\n(.*?)```", RegexOptions.Singleline);
        static readonly Regex LastEndVar = new Regex(@"^\s*END_VAR\b.*$", RegexOptions.Multiline | RegexOptions.RightToLeft);
        static readonly Regex Header = new Regex(@"^\s*(?:PROGRAM|FUNCTION_BLOCK|FUNCTION)\s+([A-Za-z_]\w*)", RegexOptions.Multiline);

        [Fact]
        public void The_guides_show_no_dangerous_ST()
        {
            var assembly = typeof(CliCommands).Assembly;
            var files = new Dictionary<string, string>();
            foreach (var resource in assembly.GetManifestResourceNames().Where(n => n.StartsWith("Cts.Agent.Guides.", StringComparison.Ordinal) && n.EndsWith(".md", StringComparison.Ordinal)))
            {
                string text;
                using (var reader = new StreamReader(assembly.GetManifestResourceStream(resource))) text = reader.ReadToEnd();
                foreach (Match block in Block.Matches(text))
                {
                    var code = block.Groups[1].Value;
                    var header = Header.Match(code);
                    // The IDE's two panes: the body starts after the last END_VAR.
                    var end = LastEndVar.Match(code);
                    if (header.Success && end.Success) code = code.Insert(end.Index + end.Length, "\n// --- implementation ---");
                    files[(header.Success ? header.Groups[1].Value : resource + files.Count) + ".st"] = code;
                }
            }
            Assert.True(files.Count >= 8, "only " + files.Count + " ST examples found: the guides moved?");
            var config = AnalyzeConfig.Load(Path.GetTempPath());
            var findings = Runner.Run(Snapshot.Build(".", files), config, Runner.Select(config, null), (number, count, rule) => { }).Findings;
            var dangers = findings.Where(finding => finding.Severity == Severity.Danger).Select(finding => finding.RuleId + " " + finding.Location?.Path + ":" + finding.Location?.Line + " " + finding.Message).ToList();
            Assert.True(dangers.Count == 0, string.Join("\n", dangers));
        }
    }
}
