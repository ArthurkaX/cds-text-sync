using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Cts.Sync;

namespace Cts.Cli
{
    // Objects kept as XML on the import: their MetaObject, their properties, and
    // the read-back that tells whether the IDE took the write.
    internal static partial class ImportCommand
    {
        internal sealed class NativeWrite
        {
            internal string Guid;
            internal string Name;
            internal string Path;
            internal string Content;
            internal bool Created;
            // The IDE's Object member before a replace wrote it.
            internal string Before;
            // The .csv beside the .xml: a text list's, whose rows the IDE was
            // given with it, or an alarm group's.
            internal string Csv;
        }

        static string NativeMetaValue(string content, string name)
        {
            var document = XDocument.Parse(content.TrimStart('\uFEFF'));
            var value = document.Descendants().FirstOrDefault(element => (string)element.Attribute("Name") == name);
            return value?.Value.Trim();
        }

        static string NativeEntryProblem(string content)
        {
            try
            {
                var root = XDocument.Parse(content.TrimStart('\uFEFF')).Root;
                if (root?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject") == null)
                    return "the xml has no MetaObject";
                if (root.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Object") == null)
                    return "the xml has no Object";
                return null;
            }
            catch (System.Xml.XmlException error)
            {
                return "the xml does not parse: " + error.Message;
            }
        }

        static string PlaceNative(ViewStamps stamps, string path, string content, string oldGuid, string guid, string parentGuid)
        {
            var raw = File.ReadAllBytes(path);
            var hasBom = raw.Length >= 3 && raw[0] == 0xEF && raw[1] == 0xBB && raw[2] == 0xBF;
            if (!string.IsNullOrEmpty(oldGuid) && !string.Equals(oldGuid, guid, StringComparison.OrdinalIgnoreCase))
                content = Regex.Replace(content, Regex.Escape(oldGuid), _ => guid, RegexOptions.IgnoreCase);
            var metaStart = content.IndexOf("Name=\"MetaObject\"", StringComparison.Ordinal);
            var objectStart = metaStart < 0 ? -1 : content.IndexOf("Name=\"Object\"", metaStart, StringComparison.Ordinal);
            if (metaStart >= 0 && objectStart > metaStart)
            {
                var meta = content.Substring(metaStart, objectStart - metaStart);
                foreach (var pair in new[] { new KeyValuePair<string, string>("Guid", guid), new KeyValuePair<string, string>("ParentGuid", parentGuid) })
                {
                    var pattern = "(<Single Name=\"" + pair.Key + "\" Type=\"System.Guid\">)[^<]*(</Single>)";
                    meta = Regex.Replace(meta, pattern, match => match.Groups[1].Value + pair.Value + match.Groups[2].Value, RegexOptions.None, TimeSpan.FromSeconds(1));
                }
                content = content.Substring(0, metaStart) + meta + content.Substring(objectStart);
            }
            stamps.Write(path, new UTF8Encoding(false).GetBytes((hasBom ? "\uFEFF" : "") + content));
            return content;
        }

        static List<string> NativePropertyChangesFromMeta(string disk, string ideMeta)
        {
            var diskProperties = NativeProperties(disk);
            var meta = XElement.Parse(ideMeta.TrimStart('\uFEFF'));
            var ideProperties = NativeProperties(meta);
            return PropertyChanges(diskProperties, ideProperties);
        }

        static List<string> PropertyChanges(IDictionary<string, string> diskProperties, IDictionary<string, string> ideProperties)
        {
            return diskProperties.Keys.Union(ideProperties.Keys, StringComparer.OrdinalIgnoreCase)
                .Where(key => !diskProperties.ContainsKey(key) || !ideProperties.ContainsKey(key)
                    || !string.Equals(diskProperties[key], ideProperties[key], StringComparison.Ordinal))
                .OrderBy(key => key, StringComparer.Ordinal).ToList();
        }

        static Dictionary<string, string> NativeProperties(string xml)
        {
            var meta = XDocument.Parse(xml.TrimStart('\uFEFF')).Descendants().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject");
            return NativeProperties(meta);
        }

        static Dictionary<string, string> NativeProperties(XElement meta)
        {
            var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var properties = meta?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Properties");
            foreach (var item in properties?.Elements() ?? Enumerable.Empty<XElement>())
            {
                var key = item.Elements().FirstOrDefault(element => element.Name.LocalName == "Key" || (string)element.Attribute("Name") == "Key");
                var value = item.Elements().FirstOrDefault(element => element.Name.LocalName == "Value" || (string)element.Attribute("Name") == "Value");
                var guid = key?.DescendantsAndSelf().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid"
                    || (string)element.Attribute("Type") == "System.Guid")?.Value.Trim();
                if (!string.IsNullOrEmpty(guid)) result[guid] = value?.ToString(SaveOptions.DisableFormatting) ?? "";
            }
            return result;
        }

        // `objects.export` of *guids*, every page: a reply stops once it holds
        // a few megabytes of XML and names the guids it did not export as
        // `rest`, which are asked again until none is left. An object whose
        // TimeStamp is still the one *known* gives it comes back `unchanged`.
        internal static List<IDictionary<string, object>> ExportedObjects(CliCall call, IList<string> guids, IDictionary<string, object> known = null)
        {
            var objects = new List<IDictionary<string, object>>();
            var asked = guids.ToArray();
            while (asked.Length > 0)
            {
                var parameters = new Dictionary<string, object> { { "guids", asked } };
                if (known != null) parameters["known"] = known;
                var reply = call.Call("objects.export", parameters);
                objects.AddRange(Items(reply.ContainsKey("objects") ? reply["objects"] : null));
                var rest = (reply.ContainsKey("rest") ? reply["rest"] as IEnumerable<object> : null)?.Select(Convert.ToString).ToArray() ?? new string[0];
                if (rest.Length >= asked.Length)
                    throw new CliFailure(call.Command.Verb, "bad_reply", "objects.export answered none of " + asked.Length + " objects and named them all as rest", null, 1);
                asked = rest;
            }
            return objects;
        }

        static List<IDictionary<string, object>> ReadBackNative(CliCall call, IList<NativeWrite> writes)
        {
            if (writes.Count == 0) return new List<IDictionary<string, object>>();
            List<IDictionary<string, object>> exported;
            try { exported = ExportedObjects(call, writes.Select(item => item.Guid).ToList()); }
            catch (CliFailure error) when (error.Declined)
            {
                return writes.Select(item =>
                {
                    var miss = UnappliedNative(item, new[] { "MetaObject", "Object" });
                    miss["error"] = error.Message;
                    return miss;
                }).ToList();
            }
            var objects = exported
                .ToDictionary(item => Convert.ToString(item["guid"]).Trim('{', '}'), StringComparer.OrdinalIgnoreCase);
            var unapplied = new List<IDictionary<string, object>>();
            foreach (var item in writes)
            {
                if (!objects.TryGetValue(item.Guid.Trim('{', '}'), out var current)
                    || !current.ContainsKey("meta") || !current.ContainsKey("object"))
                {
                    unapplied.Add(UnappliedNative(item, new[] { "MetaObject", "Object" }));
                    continue;
                }
                // A new object is what CODESYS made of the file, defaults added (a
                // generated screen gains hundreds): it exists, so it landed, and its
                // export replaces the file.
                if (item.Created) continue;
                var parts = new List<string>();
                foreach (var member in new[] { "MetaObject", "Object" })
                {
                    var original = NativeMemberText(item.Content, member);
                    var currentText = Convert.ToString(current[member == "MetaObject" ? "meta" : "object"]);
                    var currentMember = XElement.Parse(currentText.TrimStart('\uFEFF'));
                    currentMember.Attribute("Name")?.Remove();
                    var originalMember = XElement.Parse(original);
                    originalMember.Attribute("Name")?.Remove();
                    if (!ExportCommand.SameContent(item.Path, Encoding.UTF8.GetBytes(originalMember.ToString(SaveOptions.DisableFormatting)), Encoding.UTF8.GetBytes(currentMember.ToString(SaveOptions.DisableFormatting)))
                        && !(member == "Object" && TookTheWrite(item, currentMember)))
                        parts.Add(member);
                }
                if (parts.Count == 1 && parts[0] == "MetaObject"
                    && NativeOnlyPropertiesDiffer(item.Content, Convert.ToString(current["meta"]))) parts.Clear();
                if (parts.Count > 0) unapplied.Add(UnappliedNative(item, parts));
            }
            return unapplied;
        }

        // CODESYS stores a replaced object its own way (a generated screen's
        // elements gain their defaults), so its text differs from the file
        // even when the write landed; an Object that changed from before the
        // write was taken, its export then replaces the file.
        static bool TookTheWrite(NativeWrite item, XElement current)
        {
            if (string.IsNullOrEmpty(item.Before)) return false;
            var before = XElement.Parse(item.Before.TrimStart('\uFEFF'));
            before.Attribute("Name")?.Remove();
            return !ExportCommand.SameContent(item.Path, Encoding.UTF8.GetBytes(before.ToString(SaveOptions.DisableFormatting)), Encoding.UTF8.GetBytes(current.ToString(SaveOptions.DisableFormatting)));
        }

        static string NativeMemberText(string entry, string name)
        {
            var element = XDocument.Parse(entry.TrimStart('\uFEFF'), LoadOptions.PreserveWhitespace).Root
                .Elements().FirstOrDefault(candidate => (string)candidate.Attribute("Name") == name);
            return element?.ToString(SaveOptions.DisableFormatting) ?? "";
        }

        static bool NativeOnlyPropertiesDiffer(string disk, string ideMeta)
        {
            var diskMeta = XElement.Parse(NativeMemberText(disk, "MetaObject"));
            var ide = XElement.Parse(ideMeta.TrimStart('\uFEFF'));
            var diskProperties = diskMeta.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Properties");
            var ideProperties = ide.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Properties");
            var propertyIndex = diskMeta.Elements().TakeWhile(element => !ReferenceEquals(element, diskProperties)).Count();
            if (ideProperties != null) ideProperties.Remove();
            if (diskProperties != null)
            {
                var before = ide.Elements().ElementAtOrDefault(propertyIndex);
                if (before == null) ide.Add(diskProperties);
                else before.AddBeforeSelf(diskProperties);
            }
            return ExportCommand.SameContent("native.xml", Encoding.UTF8.GetBytes(diskMeta.ToString(SaveOptions.DisableFormatting)),
                Encoding.UTF8.GetBytes(ide.ToString(SaveOptions.DisableFormatting)));
        }

        static IDictionary<string, object> UnappliedNative(NativeWrite item, IEnumerable<string> parts)
        {
            return new Dictionary<string, object>
            {
                { "guid", item.Guid }, { "name", item.Name }, { "path", item.Path }, { "parts", parts.ToArray() },
            };
        }
    }
}
