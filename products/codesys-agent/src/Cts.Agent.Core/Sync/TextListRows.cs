using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;
using Cts.Agent;

namespace Cts.Sync
{
    // A text list's rows live in its .csv: its .xml on disk holds the rest of
    // the list (its languages, its ids) and an empty TextList, and the import
    // gives the IDE the .xml with the .csv's rows put back.
    internal static class TextListRows
    {
        const string RowType = "{53da1be7-ad25-47c3-b0e8-e26286dad2e0}";

        internal static bool IsTextList(string typeGuid) =>
            new[] { "textlist", "global_text_list" }.Contains(TypeKinds.All.Kind(typeGuid ?? ""), StringComparer.Ordinal);

        // A copy of *entry*, a text list's, without its rows.
        internal static XElement Without(XElement entry)
        {
            var copy = new XElement(entry);
            Rows(copy)?.RemoveNodes();
            return copy;
        }

        // *xml*, a text list's file, with the rows of *csv*, its .csv; null
        // when the csv has no TextID column.
        internal static string With(string xml, string csv)
        {
            var table = Csv.Parse(csv);
            if (table.Count == 0 || !table[0].Contains("TextID")) return null;
            var document = XDocument.Parse(xml.TrimStart('﻿'));
            var list = Rows(document.Root);
            if (list == null) return xml;
            var ns = list.Name.Namespace;
            var languages = Member(document.Root, "Languages")?.Elements().Select(element => element.Value).ToList() ?? new List<string>();
            var headers = table[0];
            list.RemoveNodes();
            foreach (var row in table.Skip(1).Where(row => row.Any(cell => cell.Length > 0)))
            {
                string Cell(string name) { var at = headers.IndexOf(name); return at >= 0 && at < row.Count ? row[at] : ""; }
                list.Add(new XElement(ns + "Single", new XAttribute("Type", RowType), new XAttribute("Method", "IArchivable"),
                    Text(ns, "TextID", Cell("TextID")), Text(ns, "TextDefault", Cell("TextDefault")),
                    new XElement(ns + "List", new XAttribute("Name", "LanguageTexts"), new XAttribute("Type", "System.Collections.ArrayList"),
                        languages.Select(language => new XElement(ns + "Single", new XAttribute("Type", "string"), Cell(language))))));
            }
            return (document.Declaration == null ? "" : document.Declaration + "\n") + document.Root.ToString(SaveOptions.DisableFormatting);
        }

        static XElement Text(XNamespace ns, string name, string value) =>
            new XElement(ns + "Single", new XAttribute("Name", name), new XAttribute("Type", "string"), value);

        static XElement Rows(XElement entry) => Member(entry, "TextList");

        static XElement Member(XElement entry, string name) => entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Object")
            ?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == name);
    }
}
