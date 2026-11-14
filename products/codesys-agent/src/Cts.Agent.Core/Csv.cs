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

        // Both sides' edits of a .csv whose rows its first column names (a text
        // list's TextID, an alarm's ID), cell by cell from *baseline*: rows both
        // added side by side, the rows ordered as the export writes them; null
        // when both changed one cell (or one changed a row the other removed,
        // or both changed the columns).
        internal static string Merge(string baseline, string disk, string ide)
        {
            var sides = new[] { baseline, disk, ide }.Select(Parse).ToList();
            if (sides.Any(table => table.Count == 0)) return null;
            var headers = sides.Select(table => table[0]).ToList();
            var header = headers[1].SequenceEqual(headers[0]) ? headers[2] : headers[2].SequenceEqual(headers[0]) || headers[2].SequenceEqual(headers[1]) ? headers[1] : null;
            if (header == null) return null;
            // Each side's rows by key, each row its cells by column.
            var rows = sides.Select((table, side) => table.Skip(1).Where(row => row.Count > 0 && row[0].Length > 0)
                .GroupBy(row => row[0], System.StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => headers[side].Select((column, at) => new { column, value = at < group.First().Count ? group.First()[at] : "" })
                    .GroupBy(cell => cell.column).ToDictionary(cell => cell.Key, cell => cell.First().value), System.StringComparer.Ordinal)).ToList();
            string Cell(IDictionary<string, string> row, string column) => row != null && row.TryGetValue(column, out var value) ? value : "";
            bool Same(IDictionary<string, string> one, IDictionary<string, string> other) =>
                one == null || other == null ? one == other : header.All(column => Cell(one, column) == Cell(other, column));
            var merged = new List<List<string>>();
            foreach (var key in rows.SelectMany(side => side.Keys).Distinct())
            {
                var before = rows[0].TryGetValue(key, out var b) ? b : null;
                var mine = rows[1].TryGetValue(key, out var d) ? d : null;
                var theirs = rows[2].TryGetValue(key, out var i) ? i : null;
                IDictionary<string, string> row;
                if (Same(mine, before)) row = theirs;
                else if (Same(theirs, before) || Same(mine, theirs)) row = mine;
                else if (mine == null || theirs == null) return null;
                else
                {
                    row = new Dictionary<string, string>();
                    foreach (var column in header)
                    {
                        string was = Cell(before, column), one = Cell(mine, column), other = Cell(theirs, column);
                        if (one != was && other != was && one != other) return null;
                        row[column] = one != was ? one : other;
                    }
                }
                if (row != null) merged.Add(header.Select(column => Cell(row, column)).ToList());
            }
            var output = new StringBuilder();
            AppendRow(output, header);
            foreach (var row in merged.OrderBy(row => long.TryParse(row[0], out _) ? 0 : 1)
                .ThenBy(row => long.TryParse(row[0], out var number) ? number : 0)
                .ThenBy(row => row[0], System.StringComparer.Ordinal))
                AppendRow(output, row);
            return output.ToString();
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
