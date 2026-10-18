using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // `cts tool [open NAME]` chooses the program `cts open` starts.
    internal static class ToolCommand
    {
        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "tool",
            Arguments = "[open NAME]",
            ArgumentLimit = 2,
            Summary = "Show the compare and merge programs, and choose the program for the sync folder",
            Description = "Without arguments: the program each of compare (cts compare --tool), merge (the side-by-side view of overlapping edits, cts import|export|sync --tool) and open (cts open) uses now, and the ones found installed. Compare and merge follow git: compare is git's diff.tool, else GitHub Desktop when installed, else WinMerge; merge is git's merge.tool when it names kdiff3, winmerge or vscode, else the first of those installed. `cts tool open NAME` chooses desktop, vscode, zed, explorer or a program's full path, which gets the folder as its argument (git config cts.openTool); unchosen it is the first of GitHub Desktop, VS Code and Zed installed, else Explorer. NAME auto drops the choice. Alt+Q digit 8 in CODESYS chooses it too.",
            LocalExecute = (options, host, work) => Execute(options, work),
            Build = Build,
        };

        static readonly string[] Difftools = { "winmerge", "kdiff3" };

        static IDictionary<string, object> Execute(CliOptions options, string work)
        {
            var which = options.Arguments.ElementAtOrDefault(0);
            if (which != null && which != "open") throw Refuse("choose open, not " + which);
            if (which != null) Choose(work, (options.Arguments.ElementAtOrDefault(1) ?? "").Trim());
            var data = new Dictionary<string, object>
            {
                { "compare", Side(null, CompareTool.CompareUses(work),
                    (CompareTool.DesktopExecutable() != null ? new[] { "desktop" } : new string[0]).Concat(Installed(Difftools))) },
                { "merge", Side(null, CompareTool.MergeUses(work), Installed(CompareTool.MergeTools)) },
                { "open", Side(CompareTool.Configured(work, CompareTool.OpenKey), CompareTool.OpenUses(work),
                    CompareTool.OpenTools.Where(name => CompareTool.OpenExecutable(name) != null)) },
            };
            if (which != null) data["changed"] = which;
            return data;
        }

        static IDictionary<string, object> Side(string value, string uses, IEnumerable<string> installed) =>
            new Dictionary<string, object> { { "value", value }, { "uses", uses }, { "installed", installed.ToList() } };

        static IEnumerable<string> Installed(IEnumerable<string> names) => names.Where(name => CompareTool.InstalledExecutable(name) != null);

        static void Choose(string work, string name)
        {
            var key = CompareTool.OpenKey;
            if (name.Length == 0) throw Refuse("name the open tool, or auto");
            if (name == "auto")
            {
                // Exit 5 from git: there was no choice to drop.
                GitRun.In(work, "config --global --unset " + key);
                return;
            }
            var problem = Unusable(name);
            if (problem != null) throw Refuse(problem);
            var set = GitRun.In(work, "config --global " + key + " " + ProcessArgs.Quote(name));
            if (set.ExitCode != 0) throw Refuse("git config failed: " + set.Message);
        }

        // Why *name* cannot be the open program, or null.
        static string Unusable(string name)
        {
            return CompareTool.OpenExecutable(name) != null ? null
                : CompareTool.OpenTools.Contains(name) ? name + " is not installed"
                : "cts does not know the program " + name + ": one of " + string.Join(", ", CompareTool.OpenTools) + ", or a program's full path";
        }

        static Answer Build(IDictionary<string, object> data)
        {
            var sides = new[] { "compare", "merge", "open" }.Select(which => new { which, entry = data[which] as IDictionary<string, object> }).ToList();
            var answer = new Answer();
            foreach (var side in sides) answer.Add(side.which, side.entry["uses"] ?? "none");
            var chosen = string.Join(",", sides.Where(side => side.entry["value"] != null).Select(side => side.which));
            answer.Add("chosen", chosen.Length > 0 ? chosen : "none");
            if (data.ContainsKey("changed")) answer.Add("changed", data["changed"]);
            foreach (var side in sides)
            {
                var installed = ((IEnumerable<object>)side.entry["installed"]).Select(Convert.ToString).ToList();
                answer.Detail(side.which + ": " + (installed.Count > 0 ? string.Join(", ", installed) : "none") + " installed");
            }
            return answer;
        }

        static CliFailure Refuse(string message) => new CliFailure("tool", "refused", message, "cts tool --help", 1);
    }
}
