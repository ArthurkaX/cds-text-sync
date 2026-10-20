using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Xml;
using System.Xml.Linq;
using Cts.Agent;

namespace Cts.Sync
{
    // The bytes a native object is written as: canonical XML, text list and alarm CSV.
    public static partial class ViewExport
    {
        static string TextListCsv(XElement entry)
        {
            var list = entry.Descendants().FirstOrDefault(e => (string)e.Attribute("Name") == "TextList");
            if (list == null) return null;
            var langs = entry.Descendants().FirstOrDefault(e => (string)e.Attribute("Name") == "Languages")?.Elements().Select(e => e.Value).ToList() ?? new List<string>();
            var b = new StringBuilder();
            Csv.AppendRow(b, new[] { "TextID", "TextDefault" }.Concat(langs));
            var rows = new List<List<string>>();
            foreach (var item in list.Elements().Where(e => e.Name.LocalName == "Single"))
            {
                string field(string n) { return item.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == n)?.Value ?? ""; }
                var row = new List<string> { field("TextID"), field("TextDefault") };
                var texts = item.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == "LanguageTexts")?.Elements().ToList() ?? new List<XElement>();
                for (var i = 0; i < langs.Count; i++) row.Add(i < texts.Count ? texts[i].Value : "");
                rows.Add(row);
            }
            // The IDE keeps the rows in its own order, which a new row reshuffles;
            // by TextID (numbers as numbers) the file changes only where a row does.
            foreach (var row in rows.OrderBy(row => long.TryParse(row[0], out _) ? 0 : 1)
                .ThenBy(row => long.TryParse(row[0], out var number) ? number : 0)
                .ThenBy(row => row[0], StringComparer.Ordinal))
                Csv.AppendRow(b, row);
            return b.ToString();
        }
        // An alarm group's alarms, each with its message (and the message in
        // each language) from *messages*, the text list whose TextIDs are the
        // alarm IDs.
        static string AlarmItemsCsv(XElement entry, XElement messages)
        {
            var alarms = entry.Descendants().FirstOrDefault(e => (string)e.Attribute("Name") == "Alarms");
            if (alarms == null) return null;
            var items = alarms.Elements().Where(e => e.Name.LocalName == "Entry").Select(e => e.Elements().FirstOrDefault(x => x.Name.LocalName == "Value")?.Elements().FirstOrDefault(x => x.Name.LocalName == "Single")).Where(e => e != null).ToList();
            if (items.Count == 0) return null;
            var table = messages == null ? null : Csv.Parse(TextListCsv(messages) ?? "");
            var languages = table == null || table.Count == 0 ? new List<string>() : table[0].Skip(2).ToList();
            var texts = new Dictionary<string, List<string>>(StringComparer.Ordinal);
            if (table != null)
                foreach (var row in table.Skip(1).Where(row => row.Count > 0 && row[0].Length > 0))
                    texts[row[0]] = row.Skip(1).Concat(Enumerable.Repeat("", languages.Count + 1)).Take(languages.Count + 1).ToList();
            var headers = new[] { "AlarmID" }.Concat(AlarmMessageColumns(languages))
                .Concat(new[] { "Expression", "Comparison", "ExpressionToCompare", "AlarmClass", "LatchVariable1", "LatchVariable2", "Deactivation", "MinPendingTime", "OffDelayTime", "HigherPrioAlarm", "AdditionalMessageIDs" });
            string value(XElement e, string name) { return e?.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == name)?.Value ?? ""; }
            var rows = items.Select(alarm =>
            {
                var observation = alarm.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == "ObservationType");
                var alarmClass = alarm.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == "AlarmClass");
                var additional = alarm.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == "AdditionalMessageIDs");
                var ids = additional == null ? "" : string.Join(";", additional.Elements().Select(id =>
                {
                    var textId = value(id, "TextID"); var textDefault = value(id, "TextDefault");
                    return textId.Length > 0 && textDefault.Length > 0 ? textId + ":" + textDefault : textId.Length > 0 ? textId : id.Value;
                }));
                var id = value(alarm, "ID");
                var message = texts.TryGetValue(id, out var found) ? found : Enumerable.Repeat("", languages.Count + 1).ToList();
                return new[] { id }.Concat(message).Concat(new[] { value(observation, "Expression"), value(observation, "Comparison"), value(observation, "ExpressionToCompare"), value(alarmClass, "Name") is string cls && cls.Length > 0 ? cls : value(alarm, "FullAlarmClassName"), value(alarm, "LatchVariable1"), value(alarm, "LatchVariable2"), value(alarm, "Deactivation"), value(alarm, "MinPendingTime"), value(alarm, "OffDelayTime"), value(alarm, "HigherPrioAlarm"), ids }).ToArray();
            }).OrderBy(row => { long n; return long.TryParse(row[0], out n) ? "0" + n.ToString("D20", System.Globalization.CultureInfo.InvariantCulture) : "1" + row[0]; }, StringComparer.Ordinal).ToList();
            var b = new StringBuilder(); Csv.AppendRow(b, headers);
            foreach (var row in rows) Csv.AppendRow(b, row);
            return b.ToString();
        }

        // `Message`, then `Message (LANGUAGE)` for each of the messages' languages.
        internal static IEnumerable<string> AlarmMessageColumns(IEnumerable<string> languages) =>
            new[] { "Message" }.Concat(languages.Select(language => "Message (" + language + ")"));

        static string CanonicalXml(XElement entry)
        {
            var copy = new XElement(entry);
            foreach (var element in copy.DescendantsAndSelf().ToList())
                foreach (var child in element.Elements().Where(e => (string)e.Attribute("Name") == "Timestamp").ToList()) RemoveElement(child);
            foreach (var dictionary in copy.DescendantsAndSelf().Where(e => e.Name.LocalName == "Dictionary" && (string)e.Attribute("Name") == "Properties"))
                foreach (var property in dictionary.Elements().Where(e => IsDerivedProperty(e) || ProjectInfo.IsOwnEntry(e)).ToList()) RemoveElement(property);
            foreach (var dictionary in copy.DescendantsAndSelf().Where(e => e.Name.LocalName == "Dictionary").Reverse()) SortElements(dictionary, e => Serialize(e.Elements().FirstOrDefault(k => k.Name.LocalName == "Key") ?? new XElement("Key")));
            foreach (var list in copy.DescendantsAndSelf().Where(e => (string)e.Attribute("Name") == "VisualElemMemberList"))
            {
                var children = list.Elements().ToList();
                if (children.All(e => e.Elements().Any(x => (string)x.Attribute("Name") == "Id"))) SortElements(list, e => e.Elements().First(x => (string)x.Attribute("Name") == "Id").Value);
            }
            foreach (var parent in copy.DescendantsAndSelf())
            {
                if (!parent.Elements().Any(e => (string)e.Attribute("Name") == "RedirectedPlaceholderResolution")) continue;
                foreach (var child in parent.Elements().Where(e => e.Name.LocalName == "Dictionary2" && (string)e.Attribute("Name") == "PlaceholderResolution").ToList())
                {
                    var replacement = new XElement(child.Name.Namespace + "Null", new XAttribute("Name", "PlaceholderResolution"));
                    ReplaceElement(child, replacement);
                }
            }
            return "<?xml version='1.0' encoding='utf-8'?>\n" + Serialize(copy);
        }
        static string ExternalizedXml(XElement entry)
        {
            var copy = new XElement(entry);
            foreach (var element in copy.DescendantsAndSelf().ToList())
            {
                var name = (string)element.Attribute("Name");
                if (name == "TextBlobForSerialisation") element.Value = "";
                else if (name == "TextLines")
                {
                    var template = element.Elements().FirstOrDefault();
                    foreach (var line in element.Elements().ToList()) line.Remove();
                    if (template != null)
                    {
                        var line = new XElement(template);
                        var id = line.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == "Id");
                        if (id != null) id.Value = "1";
                        var text = line.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == "Text");
                        if (text != null) text.Value = "";
                        element.Add(line);
                    }
                }
            }
            return "<?xml version='1.0' encoding='utf-8'?>\n" + Serialize(CanonicalElement(copy));
        }
        static XElement CanonicalElement(XElement element)
        {
            var text = CanonicalXml(element);
            return XElement.Parse(text.Substring(text.IndexOf('\n') + 1), LoadOptions.PreserveWhitespace);
        }
        static void RemoveElement(XElement element)
        {
            var previous = element.PreviousNode as XText;
            if (previous != null && string.IsNullOrWhiteSpace(previous.Value)) previous.Remove();
            element.Remove();
        }
        static void ReplaceElement(XElement oldElement, XElement replacement)
        {
            oldElement.ReplaceWith(replacement);
        }
        static bool IsDerivedProperty(XElement entry)
        {
            var value = entry.Elements().FirstOrDefault(e => e.Name.LocalName == "Value");
            var holders = value == null ? new List<XElement>() : value.Elements().ToList();
            if (holders.Count != 1) return false;
            var members = holders[0].Elements().ToList();
            return members.Count > 0 && members.All(m => (string)m.Attribute("Name") == "PlaceholderResolution");
        }
        static void SortElements(XElement parent, Func<XElement, string> key)
        {
            var elements = parent.Elements().ToList();
            if (elements.Count < 2) return;
            var sorted = elements.OrderBy(key, StringComparer.Ordinal).Select(e => new XElement(e)).ToList();
            for (var i = 0; i < elements.Count; i++) elements[i].ReplaceWith(sorted[i]);
        }
        static string Serialize(XElement element)
        {
            var sb = new StringBuilder();
            using (var writer = XmlWriter.Create(sb, new XmlWriterSettings { OmitXmlDeclaration = true, ConformanceLevel = ConformanceLevel.Fragment, Indent = false, NewLineHandling = NewLineHandling.None })) element.WriteTo(writer);
            return SelfClose(sb.ToString());
        }
        // <name attributes></name> becomes <name attributes />, as the export always wrote it. One pass over the
        // writer's output: a start tag directly followed by its end tag.
        internal static string SelfClose(string xml)
        {
            StringBuilder result = null;
            var copied = 0;
            var gap = xml.IndexOf("></", StringComparison.Ordinal);
            while (gap >= 0)
            {
                var next = gap + 3;
                var open = xml.LastIndexOf('<', gap);
                var nameEnd = open + 1;
                var named = open >= copied && nameEnd < gap && IsNameStart(xml[nameEnd]);
                if (named)
                {
                    nameEnd++;
                    while (nameEnd < gap && IsNameChar(xml[nameEnd]))
                    {
                        nameEnd++;
                    }
                }
                var nameLength = nameEnd - open - 1;
                var closes = named
                    && xml.IndexOf('>', nameEnd, gap - nameEnd) < 0
                    && gap + 3 + nameLength < xml.Length
                    && string.CompareOrdinal(xml, open + 1, xml, gap + 3, nameLength) == 0
                    && xml[gap + 3 + nameLength] == '>';
                if (closes)
                {
                    if (result == null)
                    {
                        result = new StringBuilder(xml.Length);
                    }
                    result.Append(xml, copied, gap - copied);
                    result.Append(" />");
                    copied = gap + 3 + nameLength + 1;
                    next = copied;
                }
                gap = next < xml.Length ? xml.IndexOf("></", next, StringComparison.Ordinal) : -1;
            }
            if (result == null)
            {
                return xml;
            }
            result.Append(xml, copied, xml.Length - copied);
            return result.ToString();
        }
        static bool IsNameStart(char value)
        {
            return (value >= 'A' && value <= 'Z') || (value >= 'a' && value <= 'z') || value == '_';
        }
        static bool IsNameChar(char value)
        {
            return char.IsLetterOrDigit(value) || value == '_' || value == ':' || value == '.' || value == '-';
        }
    }
}
