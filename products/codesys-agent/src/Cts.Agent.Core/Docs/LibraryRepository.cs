using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml;

namespace Cts.Docs
{
    // What the library repository (<root>/Managed Libraries/<vendor>/<name>/<version>)
    // says of an installed library beside its compiled file: its default
    // namespace (projectinfo) and the objects it holds (browsercache).
    internal static class LibraryRepository
    {
        static readonly byte[] NamespaceKey = Encoding.Unicode.GetBytes("DefaultNamespace");
        static readonly Regex Identifier = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*$");

        // The namespace the library's names take unless a reference gives
        // another, as the Library Manager offers it; null when it names none.
        // projectinfo keeps its strings in a table of entries: a number, the
        // length in bytes, the UTF-16 text; a property's value follows its name.
        internal static string DefaultNamespace(string folder)
        {
            var path = Path.Combine(folder, "projectinfo");
            if (!File.Exists(path)) return null;
            var bytes = File.ReadAllBytes(path);
            for (var at = 1; at + NamespaceKey.Length < bytes.Length; at++)
            {
                if (bytes[at - 1] != NamespaceKey.Length || !Same(bytes, at, NamespaceKey)) continue;
                var next = at + NamespaceKey.Length;
                if (Number(bytes, ref next) == null) return null;
                var length = Number(bytes, ref next);
                if (length == null || next + length.Value > bytes.Length) return null;
                var value = Encoding.Unicode.GetString(bytes, next, length.Value);
                return Identifier.IsMatch(value) ? value : null;
            }
            return null;
        }

        // For each of names, the installed libraries, each at its newest
        // version, that hold an object so called (a POU, a type, a GVL; not a
        // method, which many share): "Name, Version (Vendor)", the newest
        // version first (an old library a newer one replaced holds it too); a
        // name no library holds is left out.
        internal static Dictionary<string, List<string>> Holding(string root, IEnumerable<string> names)
        {
            var wanted = new HashSet<string>(names, StringComparer.OrdinalIgnoreCase);
            var found = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
            var libraries = Path.Combine(root, "Managed Libraries");
            if (wanted.Count == 0 || !Directory.Exists(libraries)) return found;
            foreach (var vendor in Directory.GetDirectories(libraries).OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
                foreach (var library in Directory.GetDirectories(vendor).OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
                {
                    var folder = Cli.LibCommand.InstalledFolder(root, Path.GetFileName(library), "*", Path.GetFileName(vendor));
                    if (folder == null) continue;
                    var reference = Path.GetFileName(library) + ", " + Path.GetFileName(folder) + " (" + Path.GetFileName(vendor) + ")";
                    foreach (var name in Held(Path.Combine(folder, "browsercache"), wanted))
                    {
                        if (!found.TryGetValue(name, out var holders)) found[name] = holders = new List<string>();
                        holders.Add(reference);
                    }
                }
            return found.ToDictionary(pair => pair.Key, pair => pair.Value.OrderByDescending(Version).ToList(), StringComparer.OrdinalIgnoreCase);
        }

        static Version Version(string reference) => System.Version.TryParse(LibraryReferences.Parse(reference)[1], out var version) ? version : new Version(0, 0);

        // The cts lib add that references *library* ("Name, Version (Vendor)")
        // at its newest version.
        internal static string AddHint(string library)
        {
            var parts = LibraryReferences.Parse(library);
            return "cts lib add \"" + parts[0] + ", * (" + parts[2] + ")\"";
        }

        static HashSet<string> Held(string browsercache, HashSet<string> wanted)
        {
            var held = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (!File.Exists(browsercache)) return held;
            try
            {
                using (var reader = XmlReader.Create(browsercache))
                    while (reader.Read())
                        if (reader.NodeType == XmlNodeType.Element && reader.Depth == 1 && reader.Name == "Node" && reader.GetAttribute("Name") is string name && wanted.Contains(name)) held.Add(name);
            }
            catch (Exception error) when (error is XmlException || error is IOException || error is UnauthorizedAccessException)
            {
            }
            return held;
        }

        static bool Same(byte[] bytes, int at, byte[] wanted)
        {
            for (var i = 0; i < wanted.Length; i++)
                if (bytes[at + i] != wanted[i]) return false;
            return true;
        }

        // A 7-bit encoded number at *at*, moved past it; null past the end.
        static int? Number(byte[] bytes, ref int at)
        {
            var value = 0;
            for (var shift = 0; shift < 32 && at < bytes.Length; shift += 7)
            {
                var part = bytes[at++];
                value |= (part & 0x7F) << shift;
                if ((part & 0x80) == 0) return value;
            }
            return null;
        }
    }
}
