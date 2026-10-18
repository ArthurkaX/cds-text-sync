using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Sync
{
    public static class StPragma
    {
        internal static readonly string[] EndKeywords = { "PROGRAM", "FUNCTION_BLOCK", "FUNCTION", "INTERFACE", "METHOD", "PROPERTY", "ACTION", "GET", "SET" };
        internal const string ImplementationMarker = "// --- implementation ---";
        static readonly Regex Pragma = new Regex(@"^\(\*\s*cds-text-sync:\s*(.*?)\s*\*\)$", RegexOptions.Compiled);
        static readonly Regex Head = new Regex(@"^\(\*\s*cds-text-sync:", RegexOptions.IgnoreCase);
        static readonly Regex Token = new Regex(@"(\w+)(?:=""([^""]*)"")?", RegexOptions.Compiled);
        internal const string BuildProperty = "24568a24-c491-472c-a21f-ee5d33859fab";

        // An object setting the pragma carries by its field name: in the
        // object's build properties (Prop "BuildProperty") or on the object.
        // Only a value other than the IDE's default is written; a True/False
        // one is its bare name when True.
        internal sealed class Setting
        {
            internal string Name, Prop, Default;
            internal bool Flag => Default == "False";
        }

        internal static readonly Setting[] Settings =
        {
            new Setting { Name = "ExcludeFromBuild", Prop = "BuildProperty", Default = "False" },
            new Setting { Name = "LinkAlways", Prop = "BuildProperty", Default = "False" },
            new Setting { Name = "External", Prop = "BuildProperty", Default = "False" },
            new Setting { Name = "EnableSystemCall", Prop = "BuildProperty", Default = "False" },
            new Setting { Name = "CompilerDefines", Prop = "BuildProperty", Default = "" },
            new Setting { Name = "MemoryReserveForOnlineChange", Prop = "BuildProperty", Default = "0" },
            new Setting { Name = "POULevel", Prop = "", Default = "Standard" },
            new Setting { Name = "SpecialFunc", Prop = "", Default = "None" },
            new Setting { Name = "AddAttributeSubsequent", Prop = "", Default = "False" },
            new Setting { Name = "ParameterList", Prop = "", Default = "False" },
            new Setting { Name = "TaskForWrite", Prop = "", Default = "00000000-0000-0000-0000-000000000000" },
        };

        // Whether *value* fits in the pragma: a quote or a comment end would cut it.
        internal static bool Fits(string value) => !value.Contains("\"") && !value.Contains("*)") && !value.Contains("\n");

        // The settings of an export *entry* that are not the default, by name.
        internal static IDictionary<string, string> Read(XElement entry)
        {
            var settings = new Dictionary<string, string>(StringComparer.Ordinal);
            var build = Field(Field(entry, "MetaObject"), "Properties")?.Elements()
                .FirstOrDefault(property => property.Elements().FirstOrDefault(e => e.Name.LocalName == "Key")?.Value.Trim().Trim('{', '}').ToLowerInvariant() == BuildProperty)
                ?.Elements().FirstOrDefault(e => e.Name.LocalName == "Value");
            var obj = Field(entry, "Object");
            foreach (var setting in Settings)
            {
                var field = setting.Prop.Length == 0 ? Field(obj, setting.Name) : build?.Descendants().FirstOrDefault(e => (string)e.Attribute("Name") == setting.Name);
                if (field == null || field.HasElements) continue;
                var value = setting.Flag ? (field.Value.Equals("True", StringComparison.OrdinalIgnoreCase) ? "True" : "False") : field.Value;
                if (value != setting.Default && Fits(value)) settings[setting.Name] = value;
            }
            return settings;
        }

        static XElement Field(XElement element, string name) => element?.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == name);

        // Whether line is a cts pragma line, the first of a declaration.
        internal static bool Is(string line) => Head.IsMatch((line ?? "").Trim());

        // The settings a pragma line names, by their catalog spelling; a name
        // cts does not know is left out.
        internal static IDictionary<string, string> Parse(string text, out string typeGuid)
        {
            typeGuid = null;
            var settings = new Dictionary<string, string>(StringComparer.Ordinal);
            var match = Pragma.Match(text ?? "");
            if (!match.Success) return settings;
            foreach (Match token in Token.Matches(match.Groups[1].Value))
            {
                var name = token.Groups[1].Value;
                var value = token.Groups[2].Success ? token.Groups[2].Value : null;
                if (name.Equals("TypeGuid", StringComparison.OrdinalIgnoreCase)) { typeGuid = value?.Trim().Trim('{', '}').ToLowerInvariant(); continue; }
                var setting = Settings.FirstOrDefault(candidate => candidate.Name.Equals(name, StringComparison.OrdinalIgnoreCase));
                if (setting == null) continue;
                var given = value ?? (setting.Flag ? "True" : null);
                if (given == null) continue;
                if (setting.Flag) given = given.Equals("True", StringComparison.OrdinalIgnoreCase) ? "True" : "False";
                if (given != setting.Default) settings[setting.Name] = given;
            }
            return settings;
        }

        internal static string EndForKind(string kind)
        {
            switch (kind) { case "PROGRAM": return "END_PROGRAM"; case "FUNCTION_BLOCK": return "END_FUNCTION_BLOCK"; case "FUNCTION": return "END_FUNCTION"; case "INTERFACE": return "END_INTERFACE"; case "METHOD": return "END_METHOD"; case "PROPERTY": return "END_PROPERTY"; case "ACTION": return "END_ACTION"; case "GET": return "END_GET"; case "SET": return "END_SET"; default: return null; }
        }
        public static string Format(string typeGuid, IDictionary<string, string> settings)
        {
            var parts = new List<string>();
            if (!string.IsNullOrEmpty(typeGuid)) parts.Add("TypeGuid=\"{" + typeGuid.Trim().Trim('{', '}').ToLowerInvariant() + "}\"");
            foreach (var setting in Settings)
                if (settings != null && settings.TryGetValue(setting.Name, out var value) && value != setting.Default)
                    parts.Add(setting.Flag ? setting.Name : setting.Name + "=\"" + value + "\"");
            return parts.Count == 0 ? null : "(* cds-text-sync: " + string.Join(" ", parts) + " *)";
        }

        // A setting's value in *settings*, its default when absent.
        internal static string Value(IDictionary<string, string> settings, Setting setting) =>
            settings != null && settings.TryGetValue(setting.Name, out var value) ? value : setting.Default;
    }
}
