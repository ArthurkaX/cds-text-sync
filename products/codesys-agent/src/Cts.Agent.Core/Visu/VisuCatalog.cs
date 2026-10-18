using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Agent;

namespace Cts.Visu
{
    // What `cts visu` refuses, in words for whoever typed the command.
    internal sealed class VisuException : Exception
    {
        internal VisuException(string message) : base(message)
        {
        }
    }

    // The element types `cts visu` knows: one JSON file per type, embedded
    // from the catalog folder (DESIGN.md there is the schema).
    internal static class VisuCatalog
    {
        const string Prefix = "Cts.Visu.Catalog.";
        const string Suffix = ".json";
        // A catalog that is not an element type: the input actions a button takes.
        const string InputActions = "input_actions";
        static readonly string[] Required = { "type", "visualElementTypeName", "base_members", "params" };

        internal static IList<string> Types()
        {
            return typeof(VisuCatalog).Assembly.GetManifestResourceNames()
                .Where(name => name.StartsWith(Prefix, StringComparison.Ordinal) && name.EndsWith(Suffix, StringComparison.Ordinal))
                .Select(name => name.Substring(Prefix.Length, name.Length - Prefix.Length - Suffix.Length))
                .Where(type => type != InputActions)
                .OrderBy(type => type, StringComparer.Ordinal)
                .ToList();
        }

        internal static IDictionary<string, object> Load(string type)
        {
            if (string.IsNullOrWhiteSpace(type)) throw new VisuException("No element type given");
            using (var stream = typeof(VisuCatalog).Assembly.GetManifestResourceStream(Prefix + type + Suffix))
            {
                if (stream == null || type == InputActions)
                    throw new VisuException("Unknown element type '" + type + "'. Available: " + string.Join(", ", Types()));
                using (var reader = new StreamReader(stream, Encoding.UTF8))
                {
                    var catalog = (IDictionary<string, object>)Json.Parse(reader.ReadToEnd());
                    var missing = Required.FirstOrDefault(key => !catalog.ContainsKey(key));
                    if (missing != null) throw new VisuException("Catalog '" + type + "' missing required key '" + missing + "'");
                    return catalog;
                }
            }
        }

        // The value the type's base member gives a settable property: its
        // colour for a colour member, else its value; null when none does.
        internal static object Default(IDictionary<string, object> catalog, IDictionary<string, object> property)
        {
            var id = Convert.ToString(JsonMap.Value(property, "member_id"));
            foreach (IDictionary<string, object> member in (IList<object>)catalog["base_members"])
            {
                if (Convert.ToString(JsonMap.Value(member, "id")) != id) continue;
                return Equals(JsonMap.Value(member, "form"), "color") ? JsonMap.Value(member, "color") : JsonMap.Value(member, "value");
            }
            return null;
        }
    }
}
