using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Agent;

namespace Cts.Cli
{
    // A text list's rows on the import: the .csv's rows against the IDE's, as the
    // rows and fields objects.listadd, listremove and setfield write.
    internal static partial class ImportCommand
    {
        internal sealed class TextListPlan
        {
            internal string Guid;
            internal string Name;
            internal string Path;
            internal string Error;
            internal string UnappliedError;
            internal List<string> Languages = new List<string>();
            internal List<Dictionary<string, string>> Rows = new List<Dictionary<string, string>>();
            internal List<int> Removes = new List<int>();
            internal List<TextListInsert> Inserts = new List<TextListInsert>();
            internal Dictionary<string, string> DiskLeaves = new Dictionary<string, string>();
            //: An alarm group's messages: the group (its .csv), and the .xml of
            //: the message list (Guid) the leaves are set on.
            internal string Group;
            internal string XmlPath;
        }

        internal sealed class TextListInsert
        {
            internal int At;
            internal IDictionary<string, object> Fields;
        }

        static Dictionary<string, object> FlattenFields(object fields)
        {
            var leaves = new Dictionary<string, object>(StringComparer.Ordinal);
            FlattenField(fields, "", leaves);
            return leaves;
        }

        static void FlattenField(object value, string path, IDictionary<string, object> leaves)
        {
            if (value is IDictionary<string, object> map)
            {
                foreach (var pair in map) FlattenField(pair.Value, path.Length == 0 ? pair.Key : path + "." + pair.Key, leaves);
            }
            else if (value is System.Collections.IEnumerable sequence && !(value is string))
            {
                var index = 0;
                foreach (var item in sequence) FlattenField(item, path + "[" + index++ + "]", leaves);
            }
            else if (path.Length > 0)
                leaves[path] = value == null || value is string ? value : Convert.ToString(value);
        }

        static TextListPlan PlanTextList(string content, IDictionary<string, object> ideLeaves)
        {
            var plan = new TextListPlan();
            var table = Csv.Parse(content);
            if (table.Count == 0 || !table[0].Contains("TextID"))
            {
                plan.Error = "the csv has no TextID column: edit the text list in the IDE";
                return plan;
            }
            var headers = table[0];
            plan.Languages = headers.Where(name => name.Length > 0 && name != "TextID" && name != "TextDefault").ToList();
            for (var index = 1; index < table.Count; index++)
            {
                var values = table[index];
                if (values.All(string.IsNullOrEmpty)) continue;
                var row = new Dictionary<string, string>(StringComparer.Ordinal);
                for (var column = 0; column < headers.Count; column++)
                    if (headers[column].Length > 0) row[headers[column]] = column < values.Count ? values[column] : null;
                plan.Rows.Add(row);
            }
            var seen = new HashSet<string>(StringComparer.Ordinal);
            var duplicates = plan.Rows.Select(row => row.ContainsKey("TextID") ? row["TextID"] ?? "" : "")
                .Where(id => !seen.Add(id)).Distinct(StringComparer.Ordinal).ToList();
            if (duplicates.Count > 0)
            {
                plan.Error = "duplicate TextID " + (string.Join(", ", duplicates.OrderBy(item => item, StringComparer.Ordinal)) is var dup && dup.Length > 0 ? dup : "(empty)") + " in the csv: edit the text list in the IDE";
                return plan;
            }
            var ideLanguages = IndexedValues(ideLeaves, "Languages[{0}]");
            if (!plan.Languages.SequenceEqual(ideLanguages, StringComparer.Ordinal))
            {
                plan.Error = "language columns " + FormatList(plan.Languages) + " differ from the IDE's " + FormatList(ideLanguages) + ": edit the text list in the IDE";
                return plan;
            }
            var ideIds = IndexedValues(ideLeaves, "TextList[{0}].TextID");
            var named = ideIds.Where(id => id.Length > 0).ToList();
            if (!ideIds.Take(named.Count).SequenceEqual(named, StringComparer.Ordinal))
            {
                plan.Error = "the IDE text list has an empty row before its last rows: edit the text list in the IDE";
                return plan;
            }
            if (named.Distinct(StringComparer.Ordinal).Count() != named.Count)
            {
                plan.Error = "the IDE text list has a duplicate TextID: edit the text list in the IDE";
                return plan;
            }
            var csvRows = plan.Rows.Where(row => row.ContainsKey("TextID") && !string.IsNullOrEmpty(row["TextID"])).ToList();
            var csvSet = new HashSet<string>(csvRows.Select(row => row["TextID"]), StringComparer.Ordinal);
            var ideSet = new HashSet<string>(named, StringComparer.Ordinal);
            // Rows match by TextID, not by place: the file lists them by TextID and the
            // IDE in its own order, so a new row goes to the end of the IDE's list.
            for (var index = named.Count - 1; index >= 0; index--)
                if (!csvSet.Contains(named[index])) plan.Removes.Add(index);
            var order = named.Where(csvSet.Contains).ToList();
            foreach (var row in csvRows.Where(row => !ideSet.Contains(row["TextID"])))
            {
                plan.Inserts.Add(new TextListInsert { At = order.Count, Fields = TextListRowFields(row, plan.Languages) });
                order.Add(row["TextID"]);
            }
            var positions = order.Select((id, index) => new { id, index }).ToDictionary(item => item.id, item => item.index, StringComparer.Ordinal);
            foreach (var row in csvRows)
            {
                var at = positions[row["TextID"]];
                foreach (var field in TextListRowFields(row, plan.Languages))
                    plan.DiskLeaves["TextList[" + at + "]." + field.Key] = Convert.ToString(field.Value);
            }
            return plan;
        }

        static IDictionary<string, object> TextListRowFields(IDictionary<string, string> row, IList<string> languages)
        {
            var fields = new Dictionary<string, object>
            {
                { "TextID", row.ContainsKey("TextID") ? row["TextID"] ?? "" : "" },
                { "TextDefault", row.ContainsKey("TextDefault") ? row["TextDefault"] ?? "" : "" },
            };
            for (var index = 0; index < languages.Count; index++)
            {
                var language = languages[index];
                fields["LanguageTexts[" + index + "]"] = row.ContainsKey(language) ? row[language] ?? "" : "";
            }
            return fields;
        }

        static List<string> IndexedValues(IDictionary<string, object> values, string pattern)
        {
            var result = new List<string>();
            while (values.ContainsKey(string.Format(System.Globalization.CultureInfo.InvariantCulture, pattern, result.Count)))
                result.Add(Convert.ToString(values[string.Format(System.Globalization.CultureInfo.InvariantCulture, pattern, result.Count)]) ?? "");
            return result;
        }

        static string FormatList(IList<string> values) => "(" + (values.Count == 0 ? "none" : string.Join(", ", values)) + ")";
    }
}
