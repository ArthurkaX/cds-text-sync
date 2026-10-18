using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using Cts.Agent;

namespace Cts.Cli
{
    // `cts open`: the sync folder in the person's own program for what the
    // quick window does not do -- history, branches, merging them, undoing a
    // commit: the one `cts tool open` chose, else GitHub Desktop, VS Code or
    // Zed when installed, else Explorer.
    internal static class OpenCommand
    {
        internal static readonly CliCommand Command = new CliCommand
        {
            Name = "open",
            Summary = "Open the sync folder in your git program",
            Description = "Opens the sync folder's git repository in the program cts tool open chose (GitHub Desktop, VS Code, Zed, Explorer or a program's full path); unchosen, the first of GitHub Desktop, VS Code and Zed installed, else Explorer. There a person sees the history, merges branches and does what the quick window does not; cts import then carries what changed into the IDE. Run from the sync folder (Alt+Q digit 7 in CODESYS does). It changes nothing itself.",
            LocalExecute = (options, host, work) => Execute(work),
            Build = data => new Answer().Add("folder", data["folder"]).Add("in", data["in"]),
        };

        static IDictionary<string, object> Execute(string work)
        {
            var folder = GitRepository.Repository(work);
            var uses = CompareTool.OpenUses(folder);
            var exe = CompareTool.OpenExecutable(uses);
            if (exe == null) throw new CliFailure("open", "refused", uses + " is not installed: cts tool open NAME chooses another", "cts tool open auto", 1);
            try
            {
                if (uses == "desktop") CompareTool.OpenDesktop(exe, folder);
                // The shell starts it: a child of cts would hold the pipe the quick window reads cts' answer from.
                else Process.Start(new ProcessStartInfo(exe, "\"" + folder + "\"") { UseShellExecute = true });
            }
            catch (Win32Exception error) { throw new CliFailure("open", "refused", exe + " could not start: " + error.Message, null, 1); }
            return new Dictionary<string, object> { { "folder", folder }, { "in", uses } };
        }
    }
}
