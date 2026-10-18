using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using Cts.Agent;

namespace Cts.Visu
{
    // An element's input configuration and actions, and the edits of a fragment's members.
    internal static partial class ElementTemplates
    {
        static string RenderConfiguredInputs(IDictionary<string, object> parameters)
        {
            var configured = parameters.TryGetValue("configured_inputs", out var input)
                ? input as IList<object>
                : null;
            var tap = Value(parameters, "tap_var", "");
            var toggle = Value(parameters, "toggle_var", "");
            if ((configured == null || configured.Count == 0) && tap.Length == 0 && toggle.Length == 0)
                return "              <Array Name=\"ConfiguredComplexInputs\" Type=\"{1de566f6-72a7-494c-9353-9a418172c96e}\" />";
            var result = new StringBuilder("              <Array Name=\"ConfiguredComplexInputs\" Type=\"{1de566f6-72a7-494c-9353-9a418172c96e}\">\n");
            if (configured != null)
            {
                foreach (var item in configured.OfType<IDictionary<string, object>>())
                {
                    var type = Value(item, "type", "");
                    var values = item.TryGetValue("values", out var raw) ? raw as IDictionary<string, object> : null;
                    if (type == "tap")
                        result.Append(ConfiguredInput("Visu_TapInput", "Tap", "Configure the tapping of a Boolean variable", values, false));
                    else if (type == "toggle")
                        result.Append(ConfiguredInput("Visu_ToggleInput", "Toggle", "Configure the toggling of a Boolean variable", values, true));
                    else throw new VisuException("Unknown configured complex input: " + type);
                }
            }
            if (tap.Length > 0)
                result.Append(ConfiguredInput("Visu_TapInput", "Tap", "Configure the tapping of a Boolean variable",
                    new Dictionary<string, object> { ["variable"] = tap }, false));
            if (toggle.Length > 0)
                result.Append(ConfiguredInput("Visu_ToggleInput", "Toggle", "Configure the toggling of a Boolean variable",
                    new Dictionary<string, object> { ["variable"] = toggle, ["toggle_on"] = Value(parameters, "toggle_on", "False") }, true));
            return result.Append("              </Array>").ToString();
        }

        static string ConfiguredInput(string signature, string name, string description,
                                      IDictionary<string, object> values, bool toggle)
        {
            values = values ?? new Dictionary<string, object>();
            var members = new StringBuilder();
            members.Append(InputMember("1186196937", "string", Value(values, "variable", "")));
            if (toggle) members.Append(InputMember("2164770859", "bool", Value(values, "toggle_on", "False")));
            return "                <Single Type=\"{1de566f6-72a7-494c-9353-9a418172c96e}\" Method=\"IArchivable\">\n"
                + "                  <Null Name=\"DescriptionTree\" />\n"
                + "                  <Single Name=\"VisualElemMemberList\" Type=\"{17e26cd1-bb9b-47fe-a3d5-18fcd63b9c96}\" Method=\"IArchivable\">\n"
                + "                    <List Name=\"VisualElemMemberList\" Type=\"{a4b83bea-3742-489c-9fe8-d96d68dba7ab}\">\n"
                + members + "                    </List>\n                  </Single>\n"
                + "                  <Single Name=\"SignatureName\" Type=\"string\">" + signature + "</Single>\n"
                + "                  <Single Name=\"Name\" Type=\"string\">" + name + "</Single>\n"
                + "                  <Single Name=\"Description\" Type=\"string\">" + description + "</Single>\n"
                + "                </Single>\n";
        }

        static string RenderInputActions(IDictionary<string, object> parameters)
        {
            var actions = parameters.TryGetValue("input_actions", out var raw) ? raw as IList<object> : null;
            if (actions == null || actions.Count == 0)
                return "              <Dictionary Type=\"System.Collections.Hashtable\" Name=\"VisualElementInputActions\" />";
            using (var stream = typeof(ElementTemplates).Assembly.GetManifestResourceStream("Cts.Visu.Catalog.input_actions.json"))
            using (var reader = new StreamReader(stream, Encoding.UTF8))
            {
                var root = Json.Parse(reader.ReadToEnd()) as IDictionary<string, object>;
                var specs = root["visual_element_input_actions"] as IDictionary<string, object>;
                var result = new StringBuilder("              <Dictionary Type=\"System.Collections.Hashtable\" Name=\"VisualElementInputActions\">\n");
                foreach (var grouping in actions.OfType<IDictionary<string, object>>().GroupBy(action => Value(action, "event", ""), StringComparer.Ordinal).OrderBy(group => group.Key, StringComparer.Ordinal))
                {
                    var arrayType = Value(specs, "array_type", "");
                    result.Append("                <Entry>\n                  <Key>\n                    <Single Type=\"string\">").Append(Markup.Escape(grouping.Key))
                        .Append("</Single>\n                  </Key>\n                  <Value>\n                    <Array Type=\"").Append(arrayType).Append("\">\n");
                    foreach (var action in grouping) result.Append(RenderInputAction(specs, action));
                    result.Append("                    </Array>\n                  </Value>\n                </Entry>\n");
                }
                return result.Append("              </Dictionary>").ToString();
            }
        }

        static string RenderInputAction(IDictionary<string, object> specs, IDictionary<string, object> action)
        {
            var name = Value(action, "type", "");
            if (!specs.TryGetValue(name, out var raw) || !(raw is IDictionary<string, object> spec))
                throw new VisuException("Unknown visual element input action: " + name);
            var values = action.TryGetValue("values", out var value) ? value as IDictionary<string, object> : null;
            var result = new StringBuilder("                      <Single Type=\"").Append(Value(spec, "type", "")).Append("\" Method=\"IArchivable\">\n");
            foreach (var field in ((IList<object>)spec["fields"]).OfType<IDictionary<string, object>>())
            {
                var xmlName = Value(field, "xml_name", "");
                var kind = Value(field, "kind", "string");
                if (kind == "null") { result.Append(" <Null Name=\"").Append(xmlName).Append("\" />\n"); continue; }
                var fieldName = Value(field, "name", "");
                var fieldValue = values != null && values.TryGetValue(fieldName, out var supplied)
                    ? Convert.ToString(supplied, CultureInfo.InvariantCulture)
                    : Value(field, "default", "");
                if (kind == "dict")
                {
                    var from = Value(field, "from", "");
                    var dictionary = values != null && values.TryGetValue(from, out var dictionaryValue)
                        ? dictionaryValue as IDictionary<string, object>
                        : null;
                    if (dictionary == null && values != null && values.TryGetValue(from, out dictionaryValue)
                        && dictionaryValue is IDictionary<string, string> stringDictionary)
                    {
                        dictionary = stringDictionary.ToDictionary(pair => pair.Key, pair => (object)pair.Value, StringComparer.Ordinal);
                    }
                    if (dictionary == null || dictionary.Count == 0)
                    {
                        result.Append(" <Dictionary Type=\"System.Collections.Hashtable\" Name=\"").Append(xmlName).Append("\" />\n");
                    }
                    else
                    {
                        result.Append(" <Dictionary Type=\"System.Collections.Hashtable\" Name=\"").Append(xmlName).Append("\">\n");
                        foreach (var pair in dictionary)
                        {
                            result.Append("  <Entry>\n   <Key>\n    <Single Type=\"string\">").Append(Markup.Escape(pair.Key))
                                .Append("</Single>\n   </Key>\n   <Value>\n    <Single Type=\"string\">").Append(Markup.Escape(Convert.ToString(pair.Value, CultureInfo.InvariantCulture)))
                                .Append("</Single>\n   </Value>\n  </Entry>\n");
                        }
                        result.Append(" </Dictionary>\n");
                    }
                    continue;
                }
                result.Append("                        <Single Name=\"").Append(xmlName).Append("\" Type=\"").Append(kind).Append("\">")
                    .Append(Markup.Escape(fieldValue)).Append("</Single>\n");
            }
            return result.Append("                      </Single>\n").ToString();
        }

        static string InputMember(string id, string type, string value)
        {
            return "                      <Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                + "                        <Single Name=\"Id\" Type=\"long\">" + id + "</Single>\n"
                + "                        <Single Name=\"Value\" Type=\"" + type + "\">" + Markup.Escape(value) + "</Single>\n"
                + "                      </Single>\n";
        }

        static string SetMember(string xml, string id, string value)
        {
            var quote = ((char)34).ToString();
            var pattern = "(<Single Type=" + quote + Regex.Escape(MemberType) + quote + " Method=" + quote + "IArchivable" + quote
                + ">\\s*<Single Name=" + quote + "Id" + quote + " Type=" + quote + "long" + quote + ">"
                + Regex.Escape(id) + "</Single>\\s*<Single Name=" + quote + "Value" + quote + " Type=" + quote + "[^" + quote + "]+"
                + quote + ">)[^<]*(</Single>)";
            xml = Regex.Replace(xml, pattern, match => match.Groups[1].Value + Markup.Escape(value) + match.Groups[2].Value, RegexOptions.None, TimeSpan.FromSeconds(1));
            if (value.Length == 0) return xml;
            // An empty value is written self-closed: it takes the value with a closing tag.
            var empty = "(<Single Type=" + quote + Regex.Escape(MemberType) + quote + " Method=" + quote + "IArchivable" + quote
                + ">\\s*<Single Name=" + quote + "Id" + quote + " Type=" + quote + "long" + quote + ">"
                + Regex.Escape(id) + "</Single>\\s*<Single Name=" + quote + "Value" + quote + " Type=" + quote + "[^" + quote + "]+"
                + quote + ")\\s*/>";
            return Regex.Replace(xml, empty, match => match.Groups[1].Value + ">" + Markup.Escape(value) + "</Single>", RegexOptions.None, TimeSpan.FromSeconds(1));
        }

        // A member the captured template lacks goes at the end of the element's member list.
        static string SetOrAddMember(string xml, string id, string kind, string value)
        {
            var set = SetMember(xml, id, value);
            if (set != xml || value.Length == 0 || Regex.IsMatch(xml, ">" + Regex.Escape(id) + "</Single>")) return set;
            const string list = "<List Name=\"VisualElemMemberList\" Type=\"{a4b83bea-3742-489c-9fe8-d96d68dba7ab}\">";
            var start = xml.IndexOf(list, StringComparison.Ordinal);
            if (start < 0) throw new VisuException("Element template has no member list");
            var close = ClosingList(xml, start + list.Length);
            var member = "  <Single Type=\"" + MemberType + "\" Method=\"IArchivable\">\n"
                + "                    <Single Name=\"Id\" Type=\"long\">" + id + "</Single>\n"
                + "                    <Single Name=\"Value\" Type=\"" + kind + "\">" + Markup.Escape(value) + "</Single>\n"
                + "                  </Single>\n                ";
            return xml.Insert(close, member);
        }

        static string ReplaceMember(string xml, string name, string value, string type)
        {
            var quote = ((char)34).ToString();
            var pattern = "(<Single Name=" + quote + Regex.Escape(name) + quote + " Type=" + quote + type + quote + ">)[^<]*(</Single>)";
            return Regex.Replace(xml, pattern, match => match.Groups[1].Value + value + match.Groups[2].Value, RegexOptions.None, TimeSpan.FromSeconds(1));
        }

        // CODESYS writes an empty list self-closed (<List Name="TextList" ... />); give it a
        // closing tag, so entries can go in.
        internal static string OpenEmptyList(string xml, string name)
        {
            var pattern = "(<List\\s+Name=\"" + Regex.Escape(name) + "\"[^>]*?)\\s*/>";
            return Regex.Replace(xml, pattern, "$1></List>", RegexOptions.None, TimeSpan.FromSeconds(1));
        }

        internal static int ClosingList(string xml, int position)
        {
            var depth = 0;
            while (true)
            {
                var open = xml.IndexOf("<List", position, StringComparison.Ordinal);
                var close = xml.IndexOf("</List>", position, StringComparison.Ordinal);
                if (close < 0) throw new VisuException("Malformed VisualElementList (no closing tag)");
                if (open >= 0 && open < close)
                {
                    var end = xml.IndexOf('>', open);
                    if (end < 0) throw new VisuException("Malformed VisualElementList");
                    if (xml[end - 1] != '/') depth++;
                    position = open + 5;
                }
                else if (depth == 0) return close;
                else
                {
                    depth--;
                    position = close + 7;
                }
            }
        }
    }
}
