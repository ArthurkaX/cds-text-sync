using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    // The widget's words for what ran: a command's outcome, its stage, the branch's place and the last commit.
    public static partial class WidgetMenu
    {
        // The command a row that asks runs with *answer*: its Args and the
        // answer, trimmed; null when nothing was typed.
        public static string[] Answered(WidgetItem item, string answer)
        {
            var text = (answer ?? "").Trim();
            return text.Length == 0 ? null : item.Args.Concat(new[] { text }).ToArray();
        }

        // What a run is timed as: the command and its flags, not their
        // values (a commit message, a branch name), so the next run of the
        // same kind is measured against it.
        public static string Kind(IEnumerable<string> args)
        {
            var all = args.ToList();
            return string.Join(" ", all.Take(1).Concat(all.Skip(1).Where(arg => arg.StartsWith("--", StringComparison.Ordinal))));
        }

        // The running command's seconds, against the last run of its kind
        // when there was one ("12 s of ~40 s"); *share* is how much of the
        // bar to fill, null without a last run.  A run past the last one's
        // time waits near the end of the bar.
        public static string Elapsed(long elapsedMs, long? lastMs, out double? share)
        {
            var seconds = (elapsedMs / 1000).ToString(CultureInfo.InvariantCulture) + " s";
            if (lastMs == null || lastMs <= 0)
            {
                share = null;
                return seconds;
            }
            share = Math.Min(0.97, (double)elapsedMs / lastMs.Value);
            var last = Math.Max(1, (lastMs.Value + 500) / 1000);
            return seconds + " of ~" + last.ToString(CultureInfo.InvariantCulture) + " s";
        }

        public static WidgetItem ForKey(IEnumerable<WidgetItem> items, char key)
        {
            return key == '\0' ? null : items.FirstOrDefault(item => item.Key == key);
        }

        // The header of a project with no sync folder on this machine: one
        // with an id (*known*) has its repository somewhere, cloned by the
        // team's own means, and the window asks for that clone.
        public static string Unconnected(bool known)
        {
            return known ? "repository not connected on this machine" : "no sync folder yet";
        }

        // Where the IDE's work is: the branch, or the commit a detached HEAD
        // is at.  *counts* is how far the branch is from its upstream as last
        // fetched (`git rev-list --left-right --count HEAD...@{upstream}`,
        // "ahead<TAB>behind"; null without one): "↑2 ↓1" after the name,
        // nothing for a side at 0.
        public static string Where(string branch, string detachedAt, string counts)
        {
            if (branch == null) return detachedAt != null ? "detached at " + detachedAt : "no git repository";
            int ahead, behind;
            if (!Distance(counts, out ahead, out behind)) return branch;
            return branch + (ahead > 0 ? " ↑" + ahead.ToString(CultureInfo.InvariantCulture) : "")
                + (behind > 0 ? " ↓" + behind.ToString(CultureInfo.InvariantCulture) : "");
        }

        // The header's last commit, from `git log -1 --format=%s%x09%ct`
        // (*line*): its subject and when, by the time alone when it is of
        // today (*now*, local); null without a commit.
        public static string LastCommit(string line, DateTime now)
        {
            if (string.IsNullOrEmpty(line)) return null;
            var tab = line.LastIndexOf('\t');
            long seconds;
            if (tab < 0 || !long.TryParse(line.Substring(tab + 1), NumberStyles.None, CultureInfo.InvariantCulture, out seconds)) return null;
            var when = DateTimeOffset.FromUnixTimeSeconds(seconds).LocalDateTime;
            var stamp = when.ToString(when.Date == now.Date ? "HH:mm" : "yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
            return line.Substring(0, tab).Trim() + " · " + stamp;
        }

        // The commits the branch has and its upstream lacks, by *counts* as
        // `Where` reads them; 0 without an upstream.
        public static int Ahead(string counts)
        {
            int ahead;
            return Distance(counts, out ahead, out _) ? ahead : 0;
        }

        // `git rev-list --left-right --count HEAD...@{upstream}`'s "ahead behind".
        static bool Distance(string counts, out int ahead, out int behind)
        {
            behind = 0;
            var parts = (counts ?? "").Split(new[] { '\t', ' ' }, StringSplitOptions.RemoveEmptyEntries);
            return int.TryParse(parts.Length == 2 ? parts[0] : "", NumberStyles.None, CultureInfo.InvariantCulture, out ahead)
                && int.TryParse(parts[1], NumberStyles.None, CultureInfo.InvariantCulture, out behind);
        }

        // What one cts run comes to, in one line: its verdict, else the last
        // thing it said on stderr, else its exit code.
        public static string Outcome(string stdout, string stderr, int exitCode)
        {
            var verdict = Lines(stdout).FirstOrDefault(line => line.StartsWith("ok ", StringComparison.Ordinal)
                || line.StartsWith("partial ", StringComparison.Ordinal) || line.StartsWith("error ", StringComparison.Ordinal));
            var said = Lines(stderr).LastOrDefault(line => Stage(line) == null);
            var reason = said != null && said.StartsWith("[ERROR] ", StringComparison.Ordinal) ? said.Substring("[ERROR] ".Length) : said;
            // An error verdict names a cause; what went wrong is the line cts wrote to stderr.
            if (verdict != null && verdict.StartsWith("error ", StringComparison.Ordinal) && said != null
                && said.StartsWith("[ERROR] ", StringComparison.Ordinal) && !verdict.Contains(reason))
                return verdict + " — " + reason;
            return verdict ?? reason ?? "cts exited " + exitCode;
        }

        // The stage a line of cts's stderr names ("reading native objects
        // 120/412"): cts writes one as it reaches it when CTS_PROGRESS=1 is
        // set, as the widget sets it.  Null for another line.
        public static string Stage(string line)
        {
            const string prefix = "progress: ";
            return line != null && line.StartsWith(prefix, StringComparison.Ordinal) ? line.Substring(prefix.Length).TrimEnd('\r') : null;
        }

        static IEnumerable<string> Lines(string text)
        {
            return (text ?? "").Split('\n').Select(line => line.TrimEnd('\r')).Where(line => line.Trim().Length > 0);
        }
    }
}
