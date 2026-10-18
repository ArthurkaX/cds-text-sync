using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Visu
{
    internal static class Stylesheet
    {
        internal static IDictionary<string, IDictionary<string, string>> Load(string projectDir)
        {
            var rules = new Dictionary<string, IDictionary<string, string>>(StringComparer.Ordinal);
            using (var stream = typeof(Stylesheet).GetTypeInfo().Assembly.GetManifestResourceStream("Cts.Visu.stylesheet.css"))
            {
                if (stream != null)
                {
                    using (var reader = new StreamReader(stream)) Merge(rules, reader.ReadToEnd());
                }
            }
            if (projectDir != null)
            {
                var projectPath = Path.Combine(projectDir, "visu.css");
                if (File.Exists(projectPath)) Merge(rules, File.ReadAllText(projectPath));
            }
            return rules;
        }

        internal static void ApplyClass(XElement element, IDictionary<string, IDictionary<string, string>> rules)
        {
            if (element.Attribute("data-cds-type") != null) return;
            var defaults = new Dictionary<string, string>(StringComparer.Ordinal);
            var classes = ((string)element.Attribute("class") ?? "").Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
            foreach (var className in classes)
            {
                if (!rules.TryGetValue(className, out var declarations)) continue;
                foreach (var declaration in declarations)
                    defaults[declaration.Key] = declaration.Value;
            }
            var injected = new List<string>();
            foreach (var declaration in defaults)
            {
                if (element.Attribute(declaration.Key) != null) continue;
                element.SetAttributeValue(declaration.Key, declaration.Value);
                injected.Add(declaration.Key);
            }
            if (injected.Count > 0) element.SetAttributeValue("data-cds-class-attrs", string.Join(",", injected));
        }

        internal static bool WasSetByAuthor(XElement element, string attribute)
        {
            var source = (string)element.Attribute("data-cds-class-attrs") ?? "";
            return element.Attribute(attribute) != null && !source.Split(',').Contains(attribute);
        }

        static void Merge(IDictionary<string, IDictionary<string, string>> rules, string css)
        {
            css = Regex.Replace(css, @"/\*.*?\*/", "", RegexOptions.Singleline);
            foreach (Match rule in Regex.Matches(css, @"\.([A-Za-z0-9_-]+)\s*\{([^}]*)\}"))
            {
                var name = rule.Groups[1].Value;
                if (!rules.ContainsKey(name)) rules[name] = new Dictionary<string, string>(StringComparer.Ordinal);
                foreach (Match declaration in Regex.Matches(rule.Groups[2].Value, @"([A-Za-z-]+)\s*:\s*([^;]+)"))
                {
                    var property = declaration.Groups[1].Value.ToLowerInvariant();
                    if (property == "fill" || property == "stroke" || property == "font-size")
                        rules[name][property] = declaration.Groups[2].Value.Trim();
                }
            }
        }
    }
}
