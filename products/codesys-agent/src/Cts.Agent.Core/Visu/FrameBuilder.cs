using System.Collections.Generic;
using System.IO;
using System.Text;
using Cts.Agent;

namespace Cts.Visu
{
    internal static class FrameBuilder
    {
        internal static (IDictionary<string, object> Catalog, string Template) Load(string projectView, string visu)
        {
            var directory = Path.Combine(projectView, ".cds-visu", "frames");
            var catalogPath = Path.Combine(directory, visu + ".json");
            var templatePath = Path.Combine(directory, visu + ".xml.tmpl");
            if (!File.Exists(catalogPath) || !File.Exists(templatePath))
                throw new VisuException("no captured template for frame '" + visu
                    + "'; run cts visu capture-frame --visu " + visu + " first");
            var catalog = Json.Parse(File.ReadAllText(catalogPath, Encoding.UTF8)) as IDictionary<string, object>;
            if (catalog == null) throw new VisuException("Invalid frame catalog: " + catalogPath);
            return (catalog, File.ReadAllText(templatePath, Encoding.UTF8));
        }
    }
}
