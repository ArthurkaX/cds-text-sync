using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Visu
{
    // Text identifiers are global to the project, so repeated labels reuse the
    // existing id and newly allocated text becomes a row of the global text
    // list's .csv, where its rows live.
    internal static class TextListWriter
    {
        internal static string Allocate(string projectView, string text, Action<string> warning)
        {
            var path = Path.Combine(projectView, "POUs", "GlobalTextList.csv");
            if (!File.Exists(path))
            {
                warning("POUs/GlobalTextList.csv not found under " + projectView);
                return "1";
            }
            var table = Csv.Parse(File.ReadAllText(path, Encoding.UTF8));
            var header = table.FirstOrDefault() ?? new List<string>();
            var idColumn = header.IndexOf("TextID");
            var textColumn = header.IndexOf("TextDefault");
            if (idColumn < 0 || textColumn < 0)
            {
                warning("No TextID and TextDefault columns in " + path);
                return "1";
            }
            var rows = table.Skip(1).ToList();
            string Cell(IList<string> row, int column) => column < row.Count ? row[column] : "";
            var same = rows.FirstOrDefault(row => Cell(row, textColumn) == (text ?? "") && Cell(row, idColumn).Length > 0);
            if (same != null) return Cell(same, idColumn);
            var max = rows.Select(row => int.TryParse(Cell(row, idColumn), NumberStyles.Integer, CultureInfo.InvariantCulture, out var id) ? id : 0).DefaultIfEmpty(0).Max();
            var idText = (max + 1).ToString(CultureInfo.InvariantCulture);
            var added = Enumerable.Repeat("", header.Count).ToList();
            added[idColumn] = idText;
            added[textColumn] = text ?? "";
            var output = new StringBuilder();
            Csv.AppendRow(output, header);
            foreach (var row in rows.Where(row => row.Any(cell => cell.Length > 0)).Append(added)) Csv.AppendRow(output, row);
            File.WriteAllText(path, output.ToString(), new UTF8Encoding(false));
            return idText;
        }
    }
}
