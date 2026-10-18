// What the quick window's Copy puts on the clipboard after a failure: the
// line shown and enough around it for someone else to see what happened --
// where the work was, the keys that led there, the whole output of the cts
// run that failed and the runs before it.
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
        public string CommandLine { get; set; }
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

        // The report: *facts* are the known (label, value) pairs of where the
        // work was (empty values left out), *trail* the rows chosen to get to
        // the failure, *runs* the window's runs oldest first. The failed run is
        // the latest one that showed *shown*, else the latest that failed.
        public static string Build(DateTime now, IEnumerable<KeyValuePair<string, string>> facts, IList<string> trail, IList<WidgetRun> runs, string shown)
        {
            var text = new StringBuilder();
            text.AppendLine("cds-text-sync quick window, " + now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture));
            foreach (var fact in facts.Where(fact => !string.IsNullOrWhiteSpace(fact.Value)))
                text.AppendLine(fact.Key + ": " + fact.Value.Trim());
            if (trail != null && trail.Count > 0) text.AppendLine("chosen: " + string.Join(" > ", trail));
            text.AppendLine("shown: " + (shown ?? "").Trim());
            var failed = runs.LastOrDefault(run => run.ExitCode != 0 && run.Line == shown) ?? runs.LastOrDefault(run => run.ExitCode != 0);
            if (failed != null)
            {
                text.AppendLine("command: cts " + failed.CommandLine + "  (exit " + failed.ExitCode + ", "
                    + (failed.Milliseconds / 1000.0).ToString("0.0", CultureInfo.InvariantCulture) + " s, at " + Clock(failed.Started) + ")");
                Section(text, "output", failed.Output);
                Section(text, "errors", string.Join("\n", Lines(failed.Errors).Where(line => WidgetMenu.Stage(line) == null)));
            }
            var earlier = runs.Where(run => run != failed).Reverse().Take(Listed).Reverse().ToList();
            if (earlier.Count == 0) return text.ToString();
            text.AppendLine("--- earlier in this window ---");
            foreach (var run in earlier)
                text.AppendLine(Clock(run.Started) + " cts " + run.CommandLine + ": " + Said(run));
            return text.ToString();
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
