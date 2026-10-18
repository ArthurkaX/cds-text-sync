using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // git merges an object's view XML by element through `cts hook
    // merge-driver` (XmlMerge): a branch from a colleague that added a
    // program to a task, or a library, joins this branch's own additions
    // instead of stopping the merge.  The repository's .gitattributes keeps
    // *.xml out of git's line merge; this PC's .git/info/attributes, which
    // git reads first, names the driver, so a PC without cts keeps the plain
    // rule.  Every git on this PC uses it: a pull, the git program's merge.
    internal static class MergeDriver
    {
        const string Attribute = "*.xml merge=cts";

        // Merges *theirs* into *ours* in place (git's %A), from *baseline*;
        // a refusal (exit 1) leaves *ours* as it was and git reports the
        // conflict.
        internal static IDictionary<string, object> Run(IList<string> arguments)
        {
            if (arguments.Count < 4) throw Refuse("usage: cts hook merge-driver BASE OURS THEIRS [PATH]");
            var path = arguments.Count > 4 ? arguments[4] : arguments[2];
            var merged = XmlMerge.Merge(File.ReadAllBytes(arguments[1]), File.ReadAllBytes(arguments[2]), File.ReadAllBytes(arguments[3]), out var conflict);
            if (merged == null) throw Refuse(path + ": " + conflict + "; take a side in your git program");
            File.WriteAllBytes(arguments[2], merged);
            return new Dictionary<string, object> { { "merged", path } };
        }

        // The driver in *folder*'s git config, run as *cts*, and named for
        // the XML files in .git/info/attributes: "installed" or "current".
        internal static string Register(string folder, string cts)
        {
            var command = "\"" + cts.Replace('\\', '/') + "\" hook merge-driver %O %A %B %P >/dev/null";
            var current = GitRun.In(folder, "config --get merge.cts.driver");
            var registered = current.ExitCode == 0 && current.Output.Trim() == command;
            if (!registered)
            {
                GitRepository.Run(folder, "config merge.cts.name " + ProcessArgs.Quote("cts: CODESYS objects merged element by element"));
                GitRepository.Run(folder, "config merge.cts.driver " + ProcessArgs.Quote(command));
            }
            var attributes = Path.GetFullPath(Path.Combine(folder, GitRepository.Run(folder, "rev-parse --git-path info/attributes").Trim()));
            var existing = File.Exists(attributes) ? File.ReadAllText(attributes) : "";
            var named = existing.Split('\n').Any(line => line.Trim() == Attribute);
            if (!named)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(attributes));
                File.WriteAllText(attributes, existing + (existing.Length == 0 || existing.EndsWith("\n", StringComparison.Ordinal) ? "" : "\n") + Attribute + "\n", new UTF8Encoding(false));
            }
            return registered && named ? "current" : "installed";
        }

        static CliFailure Refuse(string message) => new CliFailure("hook", "conflict", message, "cts hook --help", 1);
    }
}
