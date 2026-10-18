using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml;
using System.Xml.Linq;

namespace Cts.Docs
{
    // One library a Library Manager of the project references: by a
    // placeholder, pinned directly (concrete), or only through the
    // placeholder redirection table (redirected).
    internal sealed class LibraryReference
    {
        internal string Kind, Placeholder, Name, Version, Vendor, Namespace;
        internal bool System;
    }

    // The library references of every Library Manager in an exported view: a
    // project-level one (visualization libraries) and one per application.
    // Read straight from the export, matched by type GUID; a malformed or
    // unreadable file is skipped.
    internal static class LibraryReferences
    {
        const string ManagerType = "adb5cb65-8e1d-4a00-b70a-375ea27582f3";
        const string PlaceholderItem = "4723ebe7-5bfc-43c6-be6b-5097002ef6b4";
        // A concrete item has no DefaultResolution: "name, version (vendor)"
        // is its Name.
        const string ConcreteItem = "51a11660-6c0d-4598-8c08-419c5845ea1f";
        // Points a placeholder at the version used; Standard reaches a
        // project only this way.
        const string RedirectionTable = "PlaceholderRedirectionTable";
        static readonly Regex Resolution = new Regex(@"^\s*([^,]+?),\s*(\*|[0-9][0-9.]*)\s*\(([^()]*?)\)\s*$");

        // The references deduplicated on name and version, first one kept,
        // in file then document order; gap says why there are none.
        internal static List<LibraryReference> Read(string view, out string gap)
        {
            var managers = new List<XElement>();
            foreach (var path in Directory.EnumerateFiles(view, "*.xml", SearchOption.AllDirectories).OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
            {
                try
                {
                    if (File.ReadAllText(path).IndexOf(ManagerType, StringComparison.OrdinalIgnoreCase) < 0) continue;
                    var root = XDocument.Load(path).Root;
                    if (IsManager(root)) managers.Add(root);
                }
                catch (Exception error) when (error is XmlException || error is IOException || error is UnauthorizedAccessException)
                {
                }
            }
            var references = new List<LibraryReference>();
            gap = null;
            if (managers.Count == 0)
            {
                gap = "no Library Manager object found under " + view;
                return references;
            }
            var seen = new HashSet<string>();
            foreach (var root in managers)
            {
                // A redirection table points this manager's placeholders,
                // not another application's.
                var own = references.Count;
                foreach (var item in root.Descendants("Single"))
                {
                    var type = Guid((string)item.Attribute("Type"));
                    var kind = type == PlaceholderItem ? "placeholder" : type == ConcreteItem ? "concrete" : null;
                    if (kind == null) continue;
                    var placeholder = Text(item, "PlaceholderName");
                    var resolved = Parse(Text(item, kind == "concrete" ? "Name" : "DefaultResolution"));
                    var name = resolved[0].Length > 0 ? resolved[0] : placeholder;
                    if (name.Length == 0 || !seen.Add(name.ToLowerInvariant() + "\n" + resolved[1])) continue;
                    references.Add(new LibraryReference
                    {
                        Kind = kind, Placeholder = placeholder, Name = name, Version = resolved[1], Vendor = resolved[2],
                        Namespace = Text(item, "Namespace"), System = Text(item, "SystemLibrary").Equals("true", StringComparison.OrdinalIgnoreCase),
                    });
                }
                foreach (var table in root.Descendants("Dictionary").Where(table => ((string)table.Attribute("Name") ?? "").Trim() == RedirectionTable))
                    foreach (var entry in table.Descendants("Entry"))
                    {
                        var key = Wrapped(entry, "Key");
                        var resolved = Parse(Wrapped(entry, "Value"));
                        if (key.Length > 0 && resolved[0].Length > 0) Redirect(references, own, seen, key, resolved);
                    }
            }
            if (references.Count == 0) gap = "Library Manager objects have no library entries";
            return references;
        }

        // "name, version (vendor)"; a bare name has the version * and no vendor.
        internal static string[] Parse(string value)
        {
            var text = (value ?? "").Trim();
            var match = Resolution.Match(text);
            return match.Success ? new[] { match.Groups[1].Value.Trim(), match.Groups[2].Value.Trim(), match.Groups[3].Value.Trim() } : new[] { text, "*", "" };
        }

        // The table fixes the version of the item it names (one of the
        // manager's own, from own on); a placeholder
        // without an item becomes a reference of its own (the system pulls
        // it in, so the project uses it).
        static void Redirect(List<LibraryReference> references, int own, HashSet<string> seen, string placeholder, string[] resolved)
        {
            var known = references.Skip(own).FirstOrDefault(reference => reference.Placeholder.Equals(placeholder, StringComparison.OrdinalIgnoreCase)
                || reference.Name.Equals(placeholder, StringComparison.OrdinalIgnoreCase));
            if (known != null)
            {
                known.Kind = "redirected";
                known.Name = resolved[0];
                known.Version = resolved[1];
                known.Vendor = resolved[2];
                return;
            }
            if (!seen.Add(resolved[0].ToLowerInvariant() + "\n" + resolved[1])) return;
            // The table carries no SystemLibrary flag: the vendor "System" is
            // what marks the libraries CODESYS pulls in itself.
            references.Add(new LibraryReference
            {
                Kind = "redirected", Placeholder = placeholder, Name = resolved[0], Version = resolved[1], Vendor = resolved[2], Namespace = "",
                System = resolved[2].Equals("System", StringComparison.OrdinalIgnoreCase),
            });
        }

        // The type GUID appears bare (TypeGuid of the MetaObject) and in
        // braces (the Object's Type attribute).
        static bool IsManager(XElement root)
        {
            var meta = root.DescendantsAndSelf("Single").FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject");
            if (meta != null && Guid(Text(meta, "TypeGuid")) == ManagerType) return true;
            var item = root.DescendantsAndSelf("Single").FirstOrDefault(element => (string)element.Attribute("Name") == "Object");
            return item != null && Guid((string)item.Attribute("Type")) == ManagerType;
        }

        static string Guid(string value) => (value ?? "").Trim().Trim('{', '}').Trim().ToLowerInvariant();

        static string Text(XElement parent, string name) => (parent.Elements("Single").FirstOrDefault(element => (string)element.Attribute("Name") == name)?.Value ?? "").Trim();

        // <Key><Single>text</Single></Key> inside one table entry.
        static string Wrapped(XElement entry, string name)
        {
            var holder = entry.Element(name);
            if (holder == null) return "";
            return (holder.Element("Single")?.Value ?? holder.Value).Trim();
        }
    }
}
