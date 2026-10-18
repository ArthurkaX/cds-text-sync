using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Docs
{
    // One row of an interface table: a variable, a structure field, or the
    // return type (Scope "Return").
    internal sealed class InterfaceRow
    {
        internal string Scope = "", Name = "", Type = "", Initial = "", Comment = "", From;
    }

    // One documented symbol of a library: a POU page of its LibDoc tree.
    internal sealed class LibrarySymbol
    {
        internal string Name, Kind, Signature = "", Description = "", Location;
        internal readonly List<string> Examples = new List<string>();
        internal readonly List<InterfaceRow> Interface = new List<InterfaceRow>();
    }

    // The installed LibDoc tree of one library version and locale, and its
    // POU pages (manifest location by title).
    internal sealed class LibDocTree
    {
        internal string Path, Version, Vendor;
        internal List<string> Pages;
    }

    // CODESYS keeps each installed library's documentation as Sphinx HTML
    // under <LibDoc root>/<vendor>/<library>/<version>/<locale>, indexed by
    // a manifest.json whose std:doc inventory names a POU page "Swap (FUN)".
    internal static class LibDoc
    {
        static readonly Regex PageKind = new Regex(@"\s\(([A-Z_]+)\)$");
        static readonly string[] Locales = { "en", "Default" };
        // The paragraph right under the title is the declaration when it
        // starts with one; a GVL page starts with its description instead.
        static readonly Regex Declaration = new Regex(@"^(?:FUNCTION_BLOCK|FUNCTION|PROGRAM|METHOD|PROPERTY|INTERFACE|TYPE|ACTION|VAR_GLOBAL)\b");
        static readonly Dictionary<string, string> KindNames = new Dictionary<string, string>
        {
            ["FUN"] = "FUNCTION", ["FB"] = "FUNCTION_BLOCK", ["PRG"] = "PROGRAM", ["METH"] = "METHOD", ["PROP"] = "PROPERTY",
            ["ITF"] = "INTERFACE", ["ACT"] = "ACTION", ["PARAMS"] = "PARAMETERS",
        };

        // The LibDoc folder under root (or root itself), or null.
        internal static string Root(string root)
        {
            var nested = System.IO.Path.Combine(root, "LibDoc");
            return Directory.Exists(nested) ? nested : Directory.Exists(root) ? root : null;
        }

        // The tree of the exact version a reference names, or of the highest
        // installed one for "*"; null when there is none. Another version is
        // never taken for an exact one.
        internal static LibDocTree Find(string root, LibraryReference reference)
        {
            var libdoc = Root(root);
            if (libdoc == null || reference.Name.Trim().Length == 0) return null;
            var wildcard = reference.Version.Trim().Length == 0 || reference.Version.Trim() == "*";
            foreach (var vendor in Folders(libdoc).Where(vendor => reference.Vendor.Trim().Length == 0 || Name(vendor).Equals(reference.Vendor.Trim(), StringComparison.OrdinalIgnoreCase)))
            {
                var library = Folders(vendor).FirstOrDefault(folder => Name(folder).Equals(reference.Name.Trim(), StringComparison.OrdinalIgnoreCase));
                if (library == null) continue;
                var versions = Folders(library);
                var version = wildcard ? versions.OrderByDescending(VersionKey, new VersionOrder()).FirstOrDefault() : versions.FirstOrDefault(folder => Name(folder) == reference.Version.Trim());
                if (version == null) continue;
                var locale = Locale(version);
                if (locale == null) continue;
                var manifest = Manifest(locale);
                if (manifest == null) continue;
                return new LibDocTree { Path = locale, Version = Name(version), Vendor = Name(vendor), Pages = Pages(manifest) };
            }
            return null;
        }

        // Why a reference has no tree: no LibDoc root, the library is not
        // installed, its exact version is not, or no version is.
        internal static string MissingReason(string root, LibraryReference reference)
        {
            var libdoc = Root(root);
            if (libdoc == null) return "library_root_unavailable";
            var libraries = Folders(libdoc).Where(vendor => reference.Vendor.Length == 0 || Name(vendor).Equals(reference.Vendor, StringComparison.OrdinalIgnoreCase))
                .SelectMany(Folders).Where(folder => Name(folder).Equals(reference.Name, StringComparison.OrdinalIgnoreCase)).ToList();
            if (libraries.Count == 0) return "documentation_package_absent";
            if (reference.Version.Length > 0 && reference.Version != "*")
                return libraries.Any(library => Directory.Exists(System.IO.Path.Combine(library, reference.Version))) ? "documentation_package_absent" : "exact_version_missing";
            return libraries.Any(library => Folders(library).Count > 0) ? "documentation_package_absent" : "wildcard_unresolved";
        }

        // Installed libraries no reference names, each with its versions
        // (a name under several vendors gets the union).
        internal static SortedDictionary<string, SortedSet<string>> Unreferenced(string root, IEnumerable<LibraryReference> references)
        {
            var found = new SortedDictionary<string, SortedSet<string>>(StringComparer.Ordinal);
            var libdoc = System.IO.Path.Combine(root, "LibDoc");
            if (!Directory.Exists(libdoc)) libdoc = Name(root).Equals("LibDoc", StringComparison.OrdinalIgnoreCase) && Directory.Exists(root) ? root : null;
            if (libdoc == null) return found;
            var referenced = new HashSet<string>(references.Select(reference => reference.Name), StringComparer.OrdinalIgnoreCase);
            foreach (var library in Folders(libdoc).SelectMany(Folders).Where(library => !referenced.Contains(Name(library))))
            {
                if (!found.TryGetValue(Name(library), out var versions)) found[Name(library)] = versions = new SortedSet<string>(StringComparer.Ordinal);
                versions.UnionWith(Folders(library).Select(Name));
            }
            return found;
        }

        internal static string KindName(string code) => KindNames.TryGetValue(code, out var name) ? name : code;

        static List<string> Folders(string parent)
        {
            try
            {
                return Directory.GetDirectories(parent).OrderBy(path => path, StringComparer.Ordinal).ToList();
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
            {
                return new List<string>();
            }
        }

        static string Name(string path) => System.IO.Path.GetFileName(path.TrimEnd(System.IO.Path.DirectorySeparatorChar, System.IO.Path.AltDirectorySeparatorChar));

        static string Locale(string version)
        {
            var locales = Folders(version);
            foreach (var wanted in Locales)
            {
                var match = locales.FirstOrDefault(locale => Name(locale) == wanted);
                if (match != null) return match;
            }
            return locales.FirstOrDefault(locale => File.Exists(System.IO.Path.Combine(locale, "manifest.json")));
        }

        static IDictionary<string, object> Manifest(string locale)
        {
            try
            {
                return Json.Parse(File.ReadAllText(System.IO.Path.Combine(locale, "manifest.json"), Encoding.UTF8).TrimStart('﻿')) as IDictionary<string, object>;
            }
            catch (Exception error) when (error is IOException || error is UnauthorizedAccessException || error is JsonException)
            {
                return null;
            }
        }

        // 3.5.15.0 after 3.5.9.0: numeric segments compare as numbers.
        static string[] VersionKey(string folder) => Name(folder).Split('.');

        sealed class VersionOrder : IComparer<string[]>
        {
            public int Compare(string[] left, string[] right)
            {
                for (var i = 0; i < Math.Min(left.Length, right.Length); i++)
                {
                    var leftNumber = left[i].All(char.IsDigit) && left[i].Length > 0;
                    var rightNumber = right[i].All(char.IsDigit) && right[i].Length > 0;
                    int order;
                    if (leftNumber && rightNumber) order = decimal.Parse(left[i], System.Globalization.CultureInfo.InvariantCulture).CompareTo(decimal.Parse(right[i], System.Globalization.CultureInfo.InvariantCulture));
                    else if (leftNumber != rightNumber) order = leftNumber ? -1 : 1;
                    else order = string.CompareOrdinal(left[i], right[i]);
                    if (order != 0) return order;
                }
                return left.Length.CompareTo(right.Length);
            }
        }

        // The POU pages of the manifest's std:doc inventory: a title with a
        // kind ("Swap (FUN)"); navigation pages have none.
        static List<string> Pages(IDictionary<string, object> manifest)
        {
            var inventory = manifest.TryGetValue("inventory", out var value) ? value as IDictionary<string, object> : null;
            var pages = inventory != null && inventory.TryGetValue("std:doc", out var doc) ? doc as IDictionary<string, object> : null;
            if (pages == null) return new List<string>();
            return pages.Values.OfType<IDictionary<string, object>>()
                .Where(entry => PageKind.IsMatch(Convert.ToString(entry.TryGetValue("name", out var name) ? name : "", System.Globalization.CultureInfo.InvariantCulture) ?? ""))
                .Select(entry => Convert.ToString(entry.TryGetValue("location", out var location) ? location : "", System.Globalization.CultureInfo.InvariantCulture) ?? "")
                .Where(location => location.Length > 0).Distinct().OrderBy(location => location, StringComparer.Ordinal).ToList();
        }

        // Every POU page of a tree, read and parsed, by name.
        internal static List<LibrarySymbol> Symbols(LibDocTree tree)
        {
            var symbols = new List<LibrarySymbol>();
            foreach (var location in tree.Pages)
            {
                string html;
                try
                {
                    html = File.ReadAllText(System.IO.Path.Combine(tree.Path, location), Encoding.UTF8);
                }
                catch (Exception error) when (error is IOException || error is UnauthorizedAccessException)
                {
                    continue;
                }
                var symbol = Page(html);
                if (symbol.Name.Length == 0) continue;
                symbol.Location = location;
                symbols.Add(symbol);
            }
            return symbols.OrderBy(symbol => symbol.Name.ToLowerInvariant(), StringComparer.Ordinal).ThenBy(symbol => symbol.Location, StringComparer.Ordinal).ToList();
        }

        // One POU page: the title "TON (FB)", the declaration paragraph, the
        // description (paragraphs and lists), the examples (<pre>), and the
        // interface table under the "InOut:" term.
        internal static LibrarySymbol Page(string html)
        {
            var document = HtmlNode.Parse(html);
            var symbol = new LibrarySymbol { Name = "", Kind = "" };
            var title = document.Find("h1");
            if (title == null) return symbol;
            var headline = Clean(title.InnerText().Replace("¶", " "));
            var kind = PageKind.Match(headline);
            symbol.Name = kind.Success ? headline.Substring(0, kind.Index).TrimEnd() : headline;
            symbol.Kind = kind.Success ? KindName(kind.Groups[1].Value) : "";
            var description = new List<string>();
            var first = true;
            foreach (var node in title.Following())
            {
                switch (node.Tag)
                {
                    case "p":
                        var text = Clean(node.InnerText());
                        if (first && Declaration.IsMatch(text)) symbol.Signature = text;
                        else if (text.Length > 0) description.Add(text);
                        first = false;
                        break;
                    case "ul":
                        var items = node.Children.Where(child => child.Tag == "li").Select(item => Clean(item.InnerText())).Where(item => item.Length > 0).ToList();
                        if (items.Count > 0) description.Add(string.Join("\n", items.Select(item => "- " + item)));
                        break;
                    case "pre":
                        var code = node.InnerText().Trim('\n').TrimEnd();
                        if (code.Length > 0) symbol.Examples.Add(code);
                        break;
                    case "dl":
                        Interface(node, symbol.Interface);
                        break;
                }
            }
            symbol.Description = string.Join("\n\n", description);
            return symbol;
        }

        // The table of the term "InOut:". CODESYS writes the scope once per
        // group with a rowspan over it, so a spanning cell is carried into
        // the rows below or every later cell would shift left.
        static void Interface(HtmlNode list, List<InterfaceRow> rows)
        {
            var children = list.Children.Where(child => child.Tag == "dt" || child.Tag == "dd").ToList();
            for (var i = 0; i + 1 < children.Count; i++)
            {
                if (children[i].Tag != "dt" || children[i + 1].Tag != "dd" || !Clean(children[i].InnerText()).StartsWith("inout", StringComparison.OrdinalIgnoreCase)) continue;
                var table = children[i + 1].Find("table");
                if (table == null) continue;
                var headers = table.All().Where(node => node.Tag == "th").Select(node => Clean(node.InnerText()).ToLowerInvariant()).ToList();
                if (headers.Count == 0) continue;
                var carried = new Dictionary<int, KeyValuePair<string, int>>();
                foreach (var row in (table.All().FirstOrDefault(node => node.Tag == "tbody") ?? table).All().Where(node => node.Tag == "tr"))
                {
                    var cells = row.Children.Where(cell => cell.Tag == "td").ToList();
                    if (cells.Count == 0) continue;
                    var values = new Dictionary<string, string>();
                    var index = 0;
                    for (var column = 0; column < headers.Count; column++)
                    {
                        if (carried.TryGetValue(column, out var carry))
                        {
                            values[headers[column]] = carry.Key;
                            if (carry.Value > 1) carried[column] = new KeyValuePair<string, int>(carry.Key, carry.Value - 1);
                            else carried.Remove(column);
                            continue;
                        }
                        if (index >= cells.Count) break;
                        var cell = cells[index++];
                        var text = Clean(cell.InnerText());
                        values[headers[column]] = text;
                        var span = cell.RowSpan();
                        if (span > 1) carried[column] = new KeyValuePair<string, int>(text, span - 1);
                    }
                    string Value(string key) => values.TryGetValue(key, out var value) ? value : "";
                    if (Value("name").Length == 0) continue;
                    rows.Add(new InterfaceRow { Scope = Value("scope"), Name = Value("name"), Type = Value("type"), Initial = Value("initial"), Comment = Value("comment") });
                }
            }
        }

        static string Clean(string text) => Regex.Replace(text, @"\s+", " ").Trim();
    }

    // Just enough of an HTML tree for the Sphinx pages LibDoc holds: elements
    // with their children and decoded text. Void elements close themselves,
    // an end tag closes up to its element (or is ignored without one), and
    // script and style hold no elements.
    internal sealed class HtmlNode
    {
        static readonly Regex Token = new Regex(@"<!--.*?-->|<!.*?>|<(?<close>/)?(?<tag>[A-Za-z][A-Za-z0-9]*)(?<attributes>(?:[^>""']|""[^""]*""|'[^']*')*)>|(?<text>[^<]+)|<", RegexOptions.Singleline);
        static readonly Regex RowSpanAttribute = new Regex(@"\browspan\s*=\s*[""']?(\d+)", RegexOptions.IgnoreCase);
        static readonly HashSet<string> LineTags = new HashSet<string> { "br", "dd", "div", "dt", "li", "p", "tr" };
        static readonly HashSet<string> Void = new HashSet<string> { "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr" };

        internal string Tag, Attributes = "", Text;
        internal HtmlNode Parent;
        internal readonly List<HtmlNode> Children = new List<HtmlNode>();

        internal static HtmlNode Parse(string html)
        {
            var root = new HtmlNode { Tag = "#document" };
            var open = root;
            var position = 0;
            while (position < html.Length)
            {
                var token = Token.Match(html, position);
                position = token.Index + Math.Max(1, token.Length);
                if (token.Groups["text"].Success || token.Value == "<")
                {
                    open.Children.Add(new HtmlNode { Tag = "#text", Text = WebUtility.HtmlDecode(token.Value), Parent = open });
                    continue;
                }
                if (!token.Groups["tag"].Success) continue;
                var tag = token.Groups["tag"].Value.ToLowerInvariant();
                if (token.Groups["close"].Success)
                {
                    for (var node = open; node.Parent != null; node = node.Parent)
                        if (node.Tag == tag)
                        {
                            open = node.Parent;
                            break;
                        }
                    continue;
                }
                var element = new HtmlNode { Tag = tag, Attributes = token.Groups["attributes"].Value, Parent = open };
                open.Children.Add(element);
                if (tag == "script" || tag == "style")
                {
                    var end = html.IndexOf("</" + tag, position, StringComparison.OrdinalIgnoreCase);
                    position = end < 0 ? html.Length : html.IndexOf('>', end) + 1;
                    if (position == 0) position = html.Length;
                    continue;
                }
                if (!Void.Contains(tag) && !element.Attributes.TrimEnd().EndsWith("/", StringComparison.Ordinal)) open = element;
            }
            return root;
        }

        // The text, with a line break around each block element, so lines
        // written as one <div> each stay apart.
        internal string InnerText()
        {
            if (Text != null) return Text;
            var text = new StringBuilder();
            foreach (var child in Children) text.Append(child.InnerText());
            return LineTags.Contains(Tag ?? "") ? "\n" + text + "\n" : text.ToString();
        }

        internal int RowSpan()
        {
            var match = RowSpanAttribute.Match(Attributes);
            return match.Success && int.TryParse(match.Groups[1].Value, out var span) ? Math.Max(1, span) : 1;
        }

        // Every element below this one, in document order.
        internal IEnumerable<HtmlNode> All() => Children.Where(child => child.Text == null).SelectMany(child => new[] { child }.Concat(child.All()));

        internal HtmlNode Find(string tag) => All().FirstOrDefault(node => node.Tag == tag);

        // The blocks after this one in document order, up to the end of the
        // page's section (Sphinx wraps a page in div.section); a block is
        // not entered (its parts are its own).
        internal IEnumerable<HtmlNode> Following()
        {
            for (var node = this; node.Parent != null && !node.IsSection(); node = node.Parent)
            {
                var siblings = node.Parent.Children;
                for (var i = siblings.IndexOf(node) + 1; i < siblings.Count; i++)
                    foreach (var found in Blocks(siblings[i])) yield return found;
            }
        }

        bool IsSection() => Tag == "body" || Tag == "div" && Regex.IsMatch(Attributes, @"\bclass\s*=\s*[""'][^""']*\bsection\b", RegexOptions.IgnoreCase);

        static IEnumerable<HtmlNode> Blocks(HtmlNode node)
        {
            if (node.Text != null || node.Tag == "table") yield break;
            if (node.Tag == "p" || node.Tag == "ul" || node.Tag == "pre" || node.Tag == "dl")
            {
                yield return node;
                yield break;
            }
            foreach (var child in node.Children)
                foreach (var found in Blocks(child)) yield return found;
        }
    }
}
