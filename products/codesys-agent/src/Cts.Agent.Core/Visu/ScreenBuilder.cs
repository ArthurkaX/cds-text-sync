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
        const string ScreenType = "{6198ad31-4b98-445c-927f-3258a0e82fe3}";

        internal static string Create(string view, string folder, string name, int width, int height, bool startVisu,
                                      bool replace = false, string background = null)
        {
            var sibling = FindSibling(folder);
            if (sibling == null)
            {
                var places = new[] { view }.Concat(Directory.GetDirectories(view, "*", SearchOption.AllDirectories))
                    .Where(directory => FindSibling(directory) != null)
                    .Select(directory => ViewPlace.Relative(view, directory))
                    .OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList();
                var here = ViewPlace.Relative(view, folder);
                throw new VisuException("No object in " + (here.Length == 0 ? "the project view's top folder" : "'" + here + "'")
                    + " to take the new screen's place in the project tree from: a new screen goes beside an object "
                    + "kept as .xml. "
                    + (places.Count == 0
                        ? "The project view holds none; run cts export first."
                        : "Pass --folder, one of: " + ViewPlace.Names(places)));
            }
            XElement root;
            try
            {
                root = XElement.Load(sibling);
            }
            catch (Exception error)
            {
                throw new VisuException("Could not parse sibling XML " + sibling + ": " + error.Message);
            }
            var meta = root.DescendantsAndSelf().FirstOrDefault(node => node.Name.LocalName == "Single"
                && (string)node.Attribute("Name") == "MetaObject");
            var parent = ChildText(meta, "ParentGuid");
            var parentNode = ChildText(root, "ParentSVNodeGuid");
            var path = root.DescendantsAndSelf().FirstOrDefault(node => node.Name.LocalName == "Array"
                && (string)node.Attribute("Name") == "Path");
            if (string.IsNullOrEmpty(parent) || string.IsNullOrEmpty(parentNode))
                throw new VisuException("Sibling " + sibling + " is missing ParentGuid/ParentSVNodeGuid");
            var pathText = path == null ? "" : string.Concat(path.Elements()
                .Where(node => node.Name.LocalName == "Single")
                .Select(node => "        <Single Type=\"string\">" + Markup.Escape(node.Value.Trim()) + "</Single>\n"));
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
                .Replace("@@IS_START_VISU@@", startVisu ? "True" : "False")
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

        static string FindSibling(string folder)
        {
            foreach (var file in Directory.GetFiles(folder, "*.xml").OrderBy(path => path, StringComparer.Ordinal))
            {
                if (file.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase)) continue;
                XElement root;
                try
                {
                    root = XElement.Load(file);
                }
                catch (Exception error)
                {
                    throw new VisuException("Cannot read " + file + ": it is not valid XML (" + error.Message
                        + "). Fix or remove it -- placement comes from a sibling object and a broken file cannot be ruled out as one.");
                }
                if ((string)root.Attribute("Type") == ScreenType
                    && root.DescendantsAndSelf().Any(node => node.Name.LocalName == "Single"
                        && (string)node.Attribute("Name") == "ParentSVNodeGuid")) return file;
            }
            return null;
        }

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
