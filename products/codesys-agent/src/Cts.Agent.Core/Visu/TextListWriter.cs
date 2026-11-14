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
        // The project's GlobalTextList as the IDE exports it while it holds no
        // rows. Its GUID is the same in every project; the three below it are
        // the project's own.
        const string EmptyList = @"<?xml version='1.0' encoding='utf-8'?>
<Single Type=""{6198ad31-4b98-445c-927f-3258a0e82fe3}"" Method=""IArchivable"">
      <Single Name=""IsRoot"" Type=""bool"">True</Single>
      <Single Name=""MetaObject"" Type=""{81297157-7ec9-45ce-845e-84cab2b88ade}"" Method=""IArchivable"">
        <Single Name=""Guid"" Type=""System.Guid"">b5430773-3042-47d6-a6d3-28650a6ce532</Single>
        <Single Name=""ParentGuid"" Type=""System.Guid"">00000000-0000-0000-0000-000000000000</Single>
        <Single Name=""Name"" Type=""string"">GlobalTextList</Single>
        <Dictionary Type=""{2c41fa04-1834-41c1-816e-303c7aa2c05b}"" Name=""Properties"" />
        <Single Name=""TypeGuid"" Type=""System.Guid"">63784cbb-9ba0-45e6-9d69-babf3f040511</Single>
        <Array Name=""EmbeddedTypeGuids"" Type=""System.Guid"" />
      </Single>
      <Single Name=""Object"" Type=""{63784cbb-9ba0-45e6-9d69-babf3f040511}"" Method=""IArchivable"">
        <List Name=""TextList"" Type=""System.Collections.ArrayList"" />
        <List Name=""Languages"" Type=""System.Collections.ArrayList"" />
        <Single Name=""GuidInit"" Type=""System.Guid"">@@INIT@@</Single>
        <Single Name=""GuidReInit"" Type=""System.Guid"">@@REINIT@@</Single>
        <Single Name=""GuidExitX"" Type=""System.Guid"">@@EXIT@@</Single>
      </Single>
      <Single Name=""ParentSVNodeGuid"" Type=""System.Guid"">00000000-0000-0000-0000-000000000000</Single>
      <Array Name=""Path"" Type=""string"" />
      <Single Name=""Index"" Type=""int"">-1</Single>
    </Single>
";

        // *log* takes whole [OK]/[WARN] lines.
        internal static string Allocate(string projectView, string text, Action<string> log)
        {
            var path = Path.Combine(projectView, "POUs", "GlobalTextList.csv");
            if (!File.Exists(path))
            {
                // A project gets its GlobalTextList with its first text, so a
                // fresh one has none.
                Directory.CreateDirectory(Path.GetDirectoryName(path));
                var xml = Path.ChangeExtension(path, ".xml");
                if (!File.Exists(xml))
                    File.WriteAllText(xml, EmptyList.Replace("@@INIT@@", Guid.NewGuid().ToString()).Replace("@@REINIT@@", Guid.NewGuid().ToString())
                        .Replace("@@EXIT@@", Guid.NewGuid().ToString()), new UTF8Encoding(false));
                File.WriteAllText(path, "TextID,TextDefault\n", new UTF8Encoding(false));
                log("[OK] Created POUs/GlobalTextList: cts import brings it into the IDE");
            }
            var table = Csv.Parse(File.ReadAllText(path, Encoding.UTF8));
            var header = table.FirstOrDefault() ?? new List<string>();
            var idColumn = header.IndexOf("TextID");
            var textColumn = header.IndexOf("TextDefault");
            if (idColumn < 0 || textColumn < 0)
            {
                log("[WARN] No TextID and TextDefault columns in " + path);
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
