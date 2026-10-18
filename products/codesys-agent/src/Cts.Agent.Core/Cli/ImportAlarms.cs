using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // An alarm group's .csv carries its alarms and their messages; only the
    // messages go back to the IDE, as the TextDefault and language texts of
    // the rows of the group's message list (TextID = AlarmID).  An alarm added,
    // removed or changed otherwise is the IDE's to make.
    internal static partial class ImportCommand
    {
        const string AlarmsInIde = ": only the Message columns of an alarm group's csv go to the IDE; change its alarms in the IDE";

        // *disk* against *ide*, the csv the IDE's group renders now;
        // *messageLeaves*, the message list's fields.
        internal static TextListPlan PlanAlarmMessages(string disk, byte[] ide, IDictionary<string, object> messageLeaves)
        {
            var plan = new TextListPlan();
            var mine = Csv.Parse(disk).Where(row => row.Any(cell => cell.Length > 0)).ToList();
            var theirs = Csv.Parse(new UTF8Encoding(false).GetString(ide ?? new byte[0])).Where(row => row.Any(cell => cell.Length > 0)).ToList();
            if (mine.Count == 0 || theirs.Count == 0 || !mine[0].SequenceEqual(theirs[0], StringComparer.Ordinal))
            {
                plan.Error = "its columns are not the IDE's" + AlarmsInIde;
                return plan;
            }
            var headers = mine[0];
            var languages = IndexedValues(messageLeaves, "Languages[{0}]");
            var columns = ViewExport.AlarmMessageColumns(languages).ToList();
            if (!headers.Skip(1).Take(columns.Count).SequenceEqual(columns, StringComparer.Ordinal))
            {
                plan.Error = "its Message columns are not the message list's languages" + AlarmsInIde;
                return plan;
            }
            if (mine.Count != theirs.Count)
            {
                plan.Error = "it has other alarms than the IDE" + AlarmsInIde;
                return plan;
            }
            var ids = IndexedValues(messageLeaves, "TextList[{0}].TextID");
            for (var index = 1; index < mine.Count; index++)
            {
                var row = Cells(mine[index], headers.Count);
                var known = Cells(theirs[index], headers.Count);
                var outside = Enumerable.Range(0, headers.Count).Where(column => column == 0 || column > columns.Count);
                if (outside.Any(column => !string.Equals(row[column], known[column], StringComparison.Ordinal)))
                {
                    plan.Error = "alarm " + known[0] + " differs outside its message" + AlarmsInIde;
                    return plan;
                }
                if (Enumerable.Range(1, columns.Count).All(column => string.Equals(row[column], known[column], StringComparison.Ordinal))) continue;
                var at = ids.IndexOf(row[0]);
                if (at < 0)
                {
                    plan.Error = "alarm " + row[0] + " has no message row in the IDE: write its first message there";
                    return plan;
                }
                plan.DiskLeaves["TextList[" + at + "].TextDefault"] = row[1];
                for (var language = 0; language < languages.Count; language++)
                    plan.DiskLeaves["TextList[" + at + "].LanguageTexts[" + language + "]"] = row[2 + language];
            }
            return plan;
        }

        static List<string> Cells(IList<string> row, int count) => row.Concat(Enumerable.Repeat("", count)).Take(count).ToList();
    }
}
