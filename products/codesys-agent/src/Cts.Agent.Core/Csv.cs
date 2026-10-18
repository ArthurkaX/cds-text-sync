using System.Collections.Generic;
using System.Linq;
using System.Text;

namespace Cts.Agent
{
    // The .csv beside a text list or an alarm group: comma-separated, a field
    // with a comma, a quote or a line break in quotes, a quote doubled.
    internal static class Csv
    {
        // The rows of *content*, a leading BOM and blank lines left out.
        internal static List<List<string>> Parse(string content)
        {
            var rows = new List<List<string>>();
            var row = new List<string>();
            var field = new StringBuilder();
            var quoted = false;
            content = (content ?? "").TrimStart('﻿');
            for (var index = 0; index < content.Length; index++)
            {
                var ch = content[index];
                if (quoted)
                {
                    if (ch == '"' && index + 1 < content.Length && content[index + 1] == '"') { field.Append('"'); index++; }
                    else if (ch == '"') quoted = false;
                    else field.Append(ch);
                }
                else if (ch == '"' && field.Length == 0) quoted = true;
                else if (ch == ',') { row.Add(field.ToString()); field.Clear(); }
                else if (ch == '\r' || ch == '\n')
                {
                    if (ch == '\r' && index + 1 < content.Length && content[index + 1] == '\n') index++;
                    row.Add(field.ToString()); field.Clear();
                    if (row.Any(value => value.Length > 0)) rows.Add(row);
                    row = new List<string>();
                }
                else field.Append(ch);
            }
            if (field.Length > 0 || row.Count > 0)
            {
                row.Add(field.ToString());
                if (row.Any(value => value.Length > 0)) rows.Add(row);
            }
            return rows;
        }

        // One row of *values* and its line break onto *output*.
        internal static void AppendRow(StringBuilder output, IEnumerable<string> values)
        {
            output.Append(string.Join(",", values.Select(value =>
            {
                value = value ?? "";
                return value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) < 0 ? value : "\"" + value.Replace("\"", "\"\"") + "\"";
            })));
            output.Append('\n');
        }
    }
}
