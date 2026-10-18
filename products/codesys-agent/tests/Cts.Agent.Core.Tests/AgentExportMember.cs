using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Agent.Tests
{
    // A view file's MetaObject or Object the way `objects.export` answers it:
    // the IDE's ExportObject document (BOM, declaration, CRLF, empty values
    // written open, a Timestamp in the meta) made a member by SnapshotFile.AsMember.
    static class AgentExportMember
    {
        internal static string Of(XDocument entry, string name)
        {
            var element = new XElement(entry.Root.Elements().First(candidate => (string)candidate.Attribute("Name") == name));
            element.Attribute("Name").Remove();
            if (name == "MetaObject")
                element.Elements().First().AddAfterSelf(new XText("\n        "), new XElement("Single", new XAttribute("Name", "Timestamp"), new XAttribute("Type", "long"), "638900000000000000"));
            var body = element.ToString(SaveOptions.DisableFormatting).Replace("\n      ", "\r\n");
            var opened = Regex.Replace(body, @"<([A-Za-z_][\w:.-]*)([^<>]*?) />", "<$1$2></$1>");
            var document = "﻿<?xml version=\"1.0\" encoding=\"utf-8\"?>\r\n" + opened.Insert(opened.IndexOf(' '), " xml:space=\"preserve\"");
            return SnapshotFile.AsMember(document, name);
        }
    }
}
