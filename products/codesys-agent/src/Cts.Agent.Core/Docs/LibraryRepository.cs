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
        static readonly Regex Identifier = new Regex(@"^[A-Za-z_][A-Za-z0-9_]*$");
        static readonly byte[] StringReference = { 0xD0, 0x00, 0x01, 0x2D };

        // The namespace the library's names take unless a reference gives
        // another, as the Library Manager offers it: its DefaultNamespace, else
        // its Title, as CODESYS takes it; null when neither is an identifier.
        // projectinfo keeps each string once, in a table of entries numbered
        // from 1 (the number, the length in bytes, the UTF-16 text); below it a
        // property is the reference to its name followed by the reference to
        // its value, each StringReference and the entry's number.
        internal static string DefaultNamespace(string folder)
        {
            var path = Path.Combine(folder, "projectinfo");
            if (!File.Exists(path)) return null;
            var bytes = File.ReadAllBytes(path);
            var (strings, end) = Strings(bytes);
            string Property(string name)
            {
                var key = strings.IndexOf(name);
                if (key < 0) return null;
                var wanted = StringReference.Concat(Encoded(key + 1)).ToArray();
                for (var at = end; at + wanted.Length + StringReference.Length < bytes.Length; at++)
                {
                    if (!Same(bytes, at, wanted)) continue;
                    var next = at + wanted.Length;
                    if (!Same(bytes, next, StringReference)) return null;
                    next += StringReference.Length;
                    var value = Number(bytes, ref next);
                    return value > 0 && value <= strings.Count ? strings[value.Value - 1] : null;
                }
                return null;
            }
            return new[] { Property("DefaultNamespace"), Property("Title") }.FirstOrDefault(value => value != null && Identifier.IsMatch(value));
        }

        // The string table: the first run of two or more entries numbered 1,
        // 2, ... and the offset past its last entry.
        static (List<string> strings, int end) Strings(byte[] bytes)
        {
            for (var start = 0; start < bytes.Length; start++)
            {
                if (bytes[start] != 1) continue;
                var strings = new List<string>();
                var at = start;
                while (true)
                {
                    var next = at;
                    var number = Number(bytes, ref next);
                    var length = Number(bytes, ref next);
                    if (number != strings.Count + 1 || length == null || length.Value % 2 != 0 || next + length.Value > bytes.Length) break;
                    strings.Add(Encoding.Unicode.GetString(bytes, next, length.Value));
                    at = next + length.Value;
                }
                if (strings.Count >= 2) return (strings, at);
            }
            return (new List<string>(), bytes.Length);
        }

        static IEnumerable<byte> Encoded(int number)
        {
            for (; number >= 0x80; number >>= 7) yield return (byte)(number & 0x7F | 0x80);
            yield return (byte)number;
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
