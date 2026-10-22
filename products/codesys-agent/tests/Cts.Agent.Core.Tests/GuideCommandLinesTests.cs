using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // An agent learns cts from `cts --help` and `cts guide`: every command
    // line they show (a `cts ...` code span, a code block's line, an example
    // of the top help, a span in a command's own help) names a command cts
    // has, with options it takes.
    public sealed class GuideCommandLinesTests
    {
        static readonly Regex Span = new Regex(@"`cts ([^`]+)`");
        static readonly Regex BlockLine = new Regex(@"^\s*cts (.+)$");
        // Where a command line in prose or a shell line ends.
        static readonly Regex End = new Regex(@"\s(?:->|→|\||&&|;|#)\s.*$|\s+\(.*$");
        static readonly string[] Global = { "--json", "--pretty", "--output", "--target", "--expect-project", "--timeout", "--help" };
        // What the test line's notes name as gone, to say what replaced it.
        static readonly HashSet<string> Removed = new HashSet<string>
        {
            "visu-lint", "install-menu", "where", "ui", "config ui", "daemon start|stop", "snapshot", "last-result",
            "docs --output DIR", "plc-log --output", "plc get --output", "test --output", "analyze --format sarif", "verify --probe-timeout", "merge --merge-tool", "project update --merge-tool",
        };

        [Fact]
        public void EveryCommandLineShownNamesARealCommandWithItsOptions()
        {
            var lines = GuideLines().Concat(HelpLines()).ToList();
            Assert.True(lines.Count > 400, "only " + lines.Count + " command lines found: the guides moved?");
            var problems = lines.Select(line => Problem(line.Item1, line.Item2)).Where(problem => problem != null).ToList();
            Assert.True(problems.Count == 0, string.Join("\n", problems));
        }

        [Fact]
        public void EveryRepositoryDocCommandLineNamesARealCommandWithItsOptions()
        {
            var lines = RepositoryDocLines().Where(line => !line.Item1.StartsWith("docs/upgrade-4.md:", StringComparison.Ordinal) || !Removed.Contains(line.Item2)).ToList();
            var problems = lines.Select(line => Problem(line.Item1, line.Item2)).Where(problem => problem != null).ToList();
            Assert.True(problems.Count == 0, string.Join("\n", problems));
        }

        static IEnumerable<Tuple<string, string>> RepositoryDocLines()
        {
            var root = new DirectoryInfo(AppContext.BaseDirectory);
            while (root != null && !File.Exists(Path.Combine(root.FullName, "irm", "setup.md"))) root = root.Parent;
            if (root == null) throw new DirectoryNotFoundException("repository root not found");
            var paths = Directory.GetFiles(Path.Combine(root.FullName, "docs"), "*.md", SearchOption.AllDirectories)
                .Where(path => Path.GetFileName(path) != "changelog-archive.md")
                .Concat(new[] { "readMe.md", "irm/setup.md", "products/codesys-agent/README.md" }.Select(path => Path.Combine(root.FullName, path)));
            foreach (var path in paths)
            {
                var relative = path.Substring(root.FullName.Length + 1).Replace(Path.DirectorySeparatorChar, '/');
                var inBlock = false;
                var number = 0;
                foreach (var line in File.ReadAllLines(path))
                {
                    number++;
                    if (line.TrimStart().StartsWith("```", StringComparison.Ordinal)) { inBlock = !inBlock; continue; }
                    foreach (Match match in (inBlock ? BlockLine : Span).Matches(line))
                        yield return Tuple.Create(relative + ":" + number, match.Groups[1].Value);
                }
            }
        }

        static IEnumerable<Tuple<string, string>> GuideLines()
        {
            var assembly = typeof(CliCommands).Assembly;
            foreach (var resource in assembly.GetManifestResourceNames().Where(n => n.StartsWith("Cts.Agent.Guides.", StringComparison.Ordinal) && n.EndsWith(".md", StringComparison.Ordinal) || n == "Cts.Cli.TopHelp.txt"))
            {
                string text;
                using (var reader = new StreamReader(assembly.GetManifestResourceStream(resource))) text = reader.ReadToEnd();
                var inBlock = resource.EndsWith(".txt", StringComparison.Ordinal);
                var number = 0;
                foreach (var line in text.Split('\n'))
                {
                    number++;
                    if (line.TrimStart().StartsWith("```", StringComparison.Ordinal)) { inBlock = !inBlock; continue; }
                    foreach (Match match in (inBlock ? BlockLine : Span).Matches(line))
                        yield return Tuple.Create(resource + ":" + number, match.Groups[1].Value);
                }
            }
        }

        static IEnumerable<Tuple<string, string>> HelpLines()
        {
            foreach (var command in CliCommands.All)
                foreach (var text in new[] { command.Description, command.ArgumentHelp }.Concat(command.Options.Select(option => option.Help)).Where(text => text != null))
                    foreach (Match match in Span.Matches(text))
                        yield return Tuple.Create("cts " + command.Words + " --help", match.Groups[1].Value);
        }

        static string Problem(string where, string line)
        {
            var words = End.Replace(line.Trim(), "").Replace("\\|", " ").Replace("|", " ").Replace("[", " ").Replace("]", " ").Replace("\"", "").Replace("'", "")
                .Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries)
                .TakeWhile(word => word != "..." && word != "…")
                .ToList();
            var name = CliOptions.CommandOf(words);
            // `cts <command> --help`: a placeholder, not a command; `cts 3.4.0`: what --version prints.
            if (name == null || name.StartsWith("<", StringComparison.Ordinal) || char.IsDigit(name[0])) return null;
            var command = CliCommands.Find(words);
            // `cts visu` and `cts visu <subcommand> --help` list a group's subcommands.
            var sub = CliOptions.WordAfterCommand(words);
            if (command == null && CliCommands.All.Any(c => c.Name == name && c.Sub != null) && (sub == null || sub.StartsWith("-", StringComparison.Ordinal) || sub.StartsWith("<", StringComparison.Ordinal))) return null;
            if (command == null) return where + ": `cts " + line + "` names no command";
            if (command.Name == "raw") return null;
            var known = new HashSet<string>(command.Options.Select(option => option.Flag).Concat(Global));
            var unknown = words.Where(word => word.StartsWith("--", StringComparison.Ordinal)).Select(word => word.Split('=')[0]).FirstOrDefault(flag => !known.Contains(flag));
            return unknown == null ? null : where + ": `cts " + line + "`: " + command.Words + " has no " + unknown;
        }
    }
}
