// The problem report the quick window makes (More > Report a problem, or the
// Report link under a failure), for a GitHub issue or Discord: this PC's
// setup as `cts diag` prints it (which names nothing), the rows that led to
// the failure shown, the cts runs of this IDE session and the agent's own
// errors, those through a Redaction, so it names no object, file, branch,
// folder or path.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace Cts.Agent
{
    // One cts run of the quick window, kept whole for the report.
    public sealed class WidgetRun
    {
        public DateTime Started { get; set; }
        public string[] Args { get; set; }
        public int ExitCode { get; set; }
        public long Milliseconds { get; set; }
        public string Output { get; set; }
        public string Errors { get; set; }
        //: The line the window showed for it (WidgetMenu.Outcome).
        public string Line { get; set; }
    }

    public static class WidgetReport
    {
        //: How many runs the window keeps, and how many of them the report lists.
        public const int Kept = 20;
        const int Listed = 10;
        //: How many of the agent's errors the report lists, and how many lines of each.
        const int Faults = 10;
        const int FaultLines = 8;

        public const string IssuesUrl = "https://github.com/ArthurkaX/cds-text-sync/issues/new?template=bug.md";
        public const string DiscordUrl = "https://discord.gg/TYJTeW64Kv";

        // *diag* is what `cts diag` printed, *trail* the rows chosen to get to
        // the failure *shown* (null from the menu), *runs* the window's runs
        // oldest first, *log* the agent's recent log entries.  The failed run
        // is the latest one that showed *shown*, else the latest that failed.
        public static string Build(DateTime now, string diag, IList<string> trail, string shown, IList<WidgetRun> runs,
            IEnumerable<string> log, Redaction redaction)
        {
            var text = new StringBuilder();
            text.AppendLine("cds-text-sync problem report, " + now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture));
            text.AppendLine("Names, paths and quoted text the agent knew are replaced (<object>, <path>, '…'). Read it all before sending.");
            Section(text, "this PC (cts diag)", diag);
            if (!string.IsNullOrWhiteSpace(shown))
            {
                text.AppendLine("--- the failure shown ---");
                if (trail != null && trail.Count > 0) text.AppendLine("chosen: " + redaction.Text(string.Join(" > ", trail)));
                text.AppendLine("shown: " + redaction.Text(shown.Trim()));
            }
            var failed = runs.LastOrDefault(run => run.ExitCode != 0 && shown != null && run.Line == shown) ?? runs.LastOrDefault(run => run.ExitCode != 0);
            if (failed != null)
            {
                text.AppendLine("--- the last failed run ---");
                text.AppendLine("command: cts " + Redaction.Command(failed.Args) + "  (exit " + failed.ExitCode + ", "
                    + (failed.Milliseconds / 1000.0).ToString("0.0", CultureInfo.InvariantCulture) + " s, at " + Clock(failed.Started) + ")");
                Section(text, "output", redaction.Text(failed.Output));
                Section(text, "errors", redaction.Text(string.Join("\n", Lines(failed.Errors).Where(line => WidgetMenu.Stage(line) == null))));
            }
            var earlier = runs.Where(run => run != failed).Reverse().Take(Listed).Reverse().ToList();
            if (earlier.Count > 0)
            {
                text.AppendLine("--- runs of this IDE session ---");
                foreach (var run in earlier)
                    text.AppendLine(Clock(run.Started) + " cts " + Redaction.Command(run.Args) + ": " + redaction.Text(Said(run)));
            }
            var faults = (log ?? Enumerable.Empty<string>()).Where(Fault).Reverse().Take(Faults).Reverse()
                .Select(entry => string.Join("\n", Lines(entry).Take(FaultLines))).ToList();
            if (faults.Count > 0) Section(text, "agent errors of this IDE session", redaction.Text(string.Join("\n", faults)));
            return text.ToString();
        }

        // A log entry that tells of something gone wrong; a cts run's own
        // entry is left out: it names the run's arguments, and the runs are listed.
        static bool Fault(string entry)
        {
            var first = Lines(entry).FirstOrDefault() ?? "";
            if (first.IndexOf(" widget: cts ", StringComparison.Ordinal) >= 0) return false;
            return new[] { "failed", "refused", "Exception", "did not" }.Any(word => first.IndexOf(word, StringComparison.Ordinal) >= 0);
        }

        // A run's line in the list: a read for JSON has no verdict, only its exit code.
        static string Said(WidgetRun run)
        {
            if (run.ExitCode == 0) return run.Line == "cts exited 0" ? "ok" : run.Line;
            return "exit " + run.ExitCode + " " + run.Line;
        }

        static void Section(StringBuilder text, string name, string body)
        {
            var lines = Lines(body).ToList();
            if (lines.Count == 0) return;
            text.AppendLine("--- " + name + " ---");
            foreach (var line in lines) text.AppendLine(line);
        }

        static IEnumerable<string> Lines(string text)
        {
            var lines = (text ?? "").Replace("\r\n", "\n").Split('\n').ToList();
            while (lines.Count > 0 && lines[lines.Count - 1].Trim().Length == 0) lines.RemoveAt(lines.Count - 1);
            return lines;
        }

        static string Clock(DateTime time) => time.ToString("HH:mm:ss", CultureInfo.InvariantCulture);
    }
}
