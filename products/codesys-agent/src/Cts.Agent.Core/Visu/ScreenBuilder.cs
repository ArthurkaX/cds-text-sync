using System;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Linq;

namespace Cts.Visu
{
    // Screen envelope construction uses the checked-in CODESYS export verbatim;
    // keeping it as text preserves its member order and whitespace.
    internal static class ScreenBuilder
    {
        const string TemplatePrefix = "Cts.Visu.Templates.";

        internal static string Create(string view, string folder, string name, int width, int height,
                                      bool replace = false, string background = null)
        {
            var (parent, parentNode, pathNames) = Placement(view, folder);
            var pathText = string.Concat(pathNames.Select(part => "        <Single Type=\"string\">" + Markup.Escape(part) + "</Single>\n"));
            var output = Path.Combine(folder, name + ".xml");
            var visuGuid = (string)null;
            if (File.Exists(output))
            {
                if (!replace) throw new VisuException("Screen already exists: " + output);
                try
                {
                    var current = XElement.Load(output);
                    var currentMeta = current.DescendantsAndSelf().FirstOrDefault(node => node.Name.LocalName == "Single"
                        && (string)node.Attribute("Name") == "MetaObject");
                    visuGuid = ChildText(currentMeta, "Guid");
                }
                catch (Exception error)
                {
                    throw new VisuException("Cannot read screen XML at " + output + ": " + error.Message
                        + ". A screen that is being replaced has to keep its Guid.");
                }
            }
            var template = Resource("screen.xml.tmpl");
            var bgColor = "16777215";
            var bgFallback = "16777215";
            var bgActive = "False";
            if (!string.IsNullOrWhiteSpace(background))
            {
                bgColor = ParseColor(background);
                bgFallback = bgColor;
                bgActive = "True";
            }
            var xml = template.Replace("@@VISU_GUID@@", string.IsNullOrEmpty(visuGuid) ? Guid.NewGuid().ToString() : visuGuid)
                .Replace("@@PARENT_GUID@@", parent)
                .Replace("@@PARENT_SVNODE_GUID@@", parentNode)
                .Replace("@@NAME@@", Markup.Escape(name))
                .Replace("@@SIZE_X@@", width.ToString(CultureInfo.InvariantCulture))
                .Replace("@@SIZE_Y@@", height.ToString(CultureInfo.InvariantCulture))
                .Replace("@@UNIQUE_ID_GENERATOR@@", "1")
                .Replace("@@LAST_USED_ID@@", "1")
                .Replace("@@ELEMENTS@@", "")
                .Replace("@@PATH@@", pathText)
                .Replace("@@BG_ACTIVE@@", bgActive)
                .Replace("@@BG_COLOR@@", bgColor)
                .Replace("@@BG_COLOR_FALLBACK@@", bgFallback);
            File.WriteAllText(output, xml, new UTF8Encoding(false));
            return output;
        }

        // A screen's place in the project tree, from the .cds-object.xml of its
        // folder and the ones above: the application it belongs to, the tree node
        // it sits under (the nearest folder, else the application) and the names
        // on the way there.
        static (string Parent, string Node, string[] Path) Placement(string view, string folder)
        {
            var placement = Owner(view, folder);
            if (placement.Parent != null) return placement;
            var places = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .Select(Path.GetDirectoryName)
                .Where(directory => { try { return Owner(view, directory).Parent != null; } catch (VisuException) { return false; } })
                .Select(directory => ViewPlace.Relative(view, directory))
                .OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList();
            var here = ViewPlace.Relative(view, folder);
            throw new VisuException((here.Length == 0 ? "The project view's top folder" : "'" + here + "'")
                + " is not inside an application, where a screen belongs. "
                + (places.Count == 0 ? "The project view holds no application; run cts export first." : "Pass --folder, one of: " + ViewPlace.Names(places)));
        }

        // Parent is null when the folder is not inside an application.
        static (string Parent, string Node, string[] Path) Owner(string view, string folder)
        {
            string node = null;
            string[] path = null;
            var top = Path.GetFullPath(view).TrimEnd(Path.DirectorySeparatorChar);
            for (var directory = Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar);
                 !string.Equals(directory, top, StringComparison.OrdinalIgnoreCase);
                 directory = Path.GetDirectoryName(directory))
            {
                var marker = Path.Combine(directory, ".cds-object.xml");
                if (!File.Exists(marker))
                    throw new VisuException("'" + ViewPlace.Relative(view, directory) + "' has no .cds-object.xml, so it is not in the IDE yet: cts import what it holds first.");
                XElement root;
                try { root = XElement.Load(marker); }
                catch (Exception error) { throw new VisuException("Cannot read " + marker + ": " + error.Message); }
                var meta = Named(root, "MetaObject");
                var guid = ChildText(meta, "Guid");
                if (string.IsNullOrEmpty(guid)) throw new VisuException(marker + " has no Guid");
                path = path ?? (Named(root, "Path")?.Elements().Select(part => part.Value.Trim()) ?? Enumerable.Empty<string>())
                    .Concat(new[] { ChildText(meta, "Name") }).ToArray();
                node = node ?? guid;
                var kind = Cts.Sync.TypeKinds.All.Kind(ChildText(meta, "TypeGuid"));
                if (kind == "folder") continue;
                return (kind == "application" ? guid : null, node, path);
            }
            return (null, null, null);
        }

        static XElement Named(XElement root, string name) => root.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == name);

        static string Resource(string file)
        {
            using (var stream = typeof(ScreenBuilder).Assembly.GetManifestResourceStream(TemplatePrefix + file))
            {
                if (stream == null) throw new VisuException("Missing embedded screen template " + file);
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        static string ChildText(XElement parent, string name)
        {
            return parent?.Elements().FirstOrDefault(node => node.Name.LocalName == "Single"
                && (string)node.Attribute("Name") == name)?.Value.Trim();
        }

        static string ParseColor(string input)
        {
            var raw = input.Trim();
            if (raw.StartsWith("#", StringComparison.Ordinal)) raw = raw.Substring(1);
            else if (raw.StartsWith("0x", StringComparison.OrdinalIgnoreCase)) raw = raw.Substring(2);
            if (!uint.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var color))
                throw new VisuException("Invalid background color: " + input);
            if (raw.Length <= 6) color |= 0xff000000;
            return unchecked((int)color).ToString(CultureInfo.InvariantCulture);
        }
    }
}
