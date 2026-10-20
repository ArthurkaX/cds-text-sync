using System.Collections.Generic;
using System.IO;
using Cts.Agent;
using Cts.Analysis;
using Cts.Docs;

namespace Cts.Cli
{
    // `cts docs`: the documentation bundle of the sync folder's project and
    // its libraries, offline; --check says whether it is still current.
    internal static class DocsCommand
    {
        internal static CliCommand Command => new CliCommand
        {
            Name = "docs", Summary = "Write the project and library documentation an AI agent reads (offline)",
            Description = "Writes .cts-docs/ beside the project view: index.md (start here), project/<Name>.md per object with its interface, members, "
                + "calls, callers, tasks and globals read/written, libraries/<Name>-<Version>.md per referenced library from its installed LibDoc, "
                + "symbols.jsonl (one JSON line per symbol) and manifest.json. A library without LibDoc of the referenced version is listed as missing, "
                + "never documented from another version. Exit 0 written; with --check 0 fresh, 1 stale, 2 no readable bundle.",
            Options = new[]
            {
                CliOption.Text("--workspace", "workspace", "DIR", "The sync folder or its project-view (default: the one around the current folder)"),
                CliOption.Text("--libraries", "libraries", "DIR", @"The CODESYS library root (default: C:\ProgramData\CODESYS)"),
                CliOption.Text("--out", "out", "DIR", "Where to write the bundle (default: .cts-docs beside the project view)"),
                CliOption.Switch("--check", "check", "Only say whether the bundle matches the sources and installed LibDoc"),
                CliOption.Text("--show", "show", "NAME", "Print one library symbol's documentation instead of writing the bundle: TON, Standard.TON, "
                    + "a namespace's or library's name for all of it"),
            },
            LocalExecute = Execute, Build = Build,
        };

        static IDictionary<string, object> Execute(CliOptions options, IAgentHost host, string work)
        {
            AnalyzeWorkspace workspace;
            try
            {
                workspace = AnalyzeWorkspace.Resolve(options.Text("workspace"), null, work);
            }
            catch (AnalyzeException error)
            {
                throw new CliFailure("docs", "refused", error.Message, "cts docs --help", 2);
            }
            var output = Path.GetFullPath(options.Text("out") ?? Path.Combine(workspace.Root, ".cts-docs"));
            var libraries = options.Text("libraries");
            if (options.Params.ContainsKey("check")) return DocsBundle.Check(workspace.View, libraries, output);
            if (options.Text("show") is string show) return DocsBundle.Show(workspace.View, libraries ?? DocsBundle.DefaultLibraries, show);
            return DocsBundle.Generate(workspace.View, libraries ?? DocsBundle.DefaultLibraries, output);
        }

        static Answer Build(IDictionary<string, object> data)
        {
            if (data.TryGetValue("show", out var show))
            {
                var found = (IList<object>)data["found"];
                var shown = new Answer().Add("show", show).Add("found", found.Count);
                foreach (IDictionary<string, object> symbol in found) shown.Detail("# " + symbol["library"] + "\n" + symbol["text"]);
                if (found.Count > 0) return shown;
                var near = (IList<object>)data["near"];
                return shown.Failed().Detail("no referenced library documents " + show + (near.Count > 0 ? "; names that hold it: " + string.Join(", ", near) : "")
                    + ". cts docs writes every referenced library's page, and its index.md names the libraries with no LibDoc on this PC");
            }
            if (data.TryGetValue("state", out var state))
            {
                var check = new Answer().Add("state", state).Add("out", data["output"]);
                if (data.TryGetValue("error", out var error)) check.Detail(error);
                else if (Equals(state, "stale")) check.Detail("The sources or the installed LibDoc changed since the bundle was written: run cts docs.");
                return Equals(state, "fresh") ? check : check.Failed().WithExitCode(Equals(state, "stale") ? 1 : 2);
            }
            var manifest = (IDictionary<string, object>)data["manifest"];
            var counts = (IDictionary<string, object>)manifest["counts"];
            var answer = new Answer().Add("out", data["output"]).Add("objects", counts["objects"])
                .Add("libraries", counts["libraries_referenced"]).Add("documented", counts["libraries_documented"]).Add("missing", counts["libraries_missing"]);
            answer.Detail("index.md lists the files; the folder is generated and git ignores it.");
            if (JsonMap.Int(counts, "libraries_missing") > 0)
                answer.Detail(counts["libraries_missing"] + " referenced libraries have no LibDoc of that version on this machine; index.md names them and why.");
            foreach (var gap in (IList<object>)manifest["gaps"]) answer.Detail("gap: " + gap);
            return answer;
        }
    }
}
