using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

namespace Cts.Cli
{
    // One object both sides changed in the same lines, side by side in the
    // user's merge program (`git merge.tool`): the side the command would
    // overwrite on the left, read-only, the side it carries on the right.
    // What is saved on the right becomes the object's text on both sides;
    // closed without saving, nothing changes for it.
    internal static class ConflictTool
    {
        internal static Action<IList<string>> StartAndWait = Start;

        // Saved or not is the right file's write time, not its text: keeping
        // the carried side as it is is a choice too.
        static readonly DateTime Unsaved = new DateTime(2000, 1, 1, 0, 0, 0, DateTimeKind.Utc);

        // The program and its arguments: the user's choice when it can show
        // two files with the right one editable, else the first such one
        // installed.
        internal static IList<string> Arguments(string folder, string left, string leftLabel, string right, string rightLabel)
        {
            var chosen = CompareTool.Configured(folder, "merge.tool");
            var order = CompareTool.MergeTools.OrderBy(name => string.Equals(name, chosen, StringComparison.OrdinalIgnoreCase) ? 0 : 1);
            foreach (var known in order)
            {
                var executable = CompareTool.Configured(folder, "mergetool." + known + ".path") ?? CompareTool.InstalledExecutable(known);
                if (executable == null) continue;
                if (known == "kdiff3") return new[] { executable, left, right, "-o", right, "--L1", leftLabel, "--L2", rightLabel };
                if (known == "winmerge") return new[] { executable, "/e", "/u", "/wl", "/dl", leftLabel, "/dr", rightLabel, left, right };
                return new[] { executable, "--wait", "--diff", left, right };
            }
            throw new InvalidOperationException("no program to show it side by side: install WinMerge, KDiff3 or VS Code");
        }

        // The right side's text once saved there, else null.
        internal static string Resolve(string folder, string name, string leftLabel, string leftText, string rightLabel, string rightText)
        {
            var directory = Path.Combine(Path.GetTempPath(), "cts-conflict-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(directory);
            try
            {
                var left = Path.Combine(directory, "left", name + ".st");
                var right = Path.Combine(directory, name + ".st");
                Directory.CreateDirectory(Path.GetDirectoryName(left));
                File.WriteAllText(left, leftText + "\n", new UTF8Encoding(false));
                File.WriteAllText(right, rightText + "\n", new UTF8Encoding(false));
                File.SetLastWriteTimeUtc(right, Unsaved);
                StartAndWait(Arguments(folder, left, leftLabel, right, rightLabel));
                if (File.GetLastWriteTimeUtc(right) == Unsaved) return null;
                return File.ReadAllText(right, new UTF8Encoding(false, true)).TrimStart('﻿');
            }
            finally { if (Directory.Exists(directory)) Directory.Delete(directory, true); }
        }

        static void Start(IList<string> arguments)
        {
            var info = new ProcessStartInfo(arguments[0], Cts.Agent.ProcessArgs.Join(arguments.Skip(1))) { UseShellExecute = false, CreateNoWindow = true };
            using (var process = Process.Start(info)) process.WaitForExit();
        }
    }
}
