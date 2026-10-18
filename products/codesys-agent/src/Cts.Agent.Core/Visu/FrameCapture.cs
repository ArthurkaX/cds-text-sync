using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace Cts.Visu
{
    // A VisuFbFrame instance turned into a reusable template: its geometry,
    // identifier and element id become @@...@@ placeholders, the members that
    // carry its interface parameters leave the template for @@PARAM_MEMBERS@@.
    internal static class FrameCapture
    {
        internal sealed class Parameter
        {
            internal string Name;
            internal long MemberId;
            internal string IecType;
            internal string Default;
        }

        static readonly Dictionary<long, string> Geometry = new Dictionary<long, string>
        {
            [ScreenXml.X] = "@@X@@",
            [ScreenXml.Y] = "@@Y@@",
            [ScreenXml.Width] = "@@WIDTH@@",
            [ScreenXml.Height] = "@@HEIGHT@@",
            [ScreenXml.CenterX] = "@@CENTER_X@@",
            [ScreenXml.CenterY] = "@@CENTER_Y@@",
        };
        static readonly Regex Generated = new Regex(@"^GenElemInst_\d+$");
        static readonly Regex Digits = new Regex(@"^\d+$");

        // The frames under *root* whose first VisNodeRefs33 names *visu*.
        internal static IEnumerable<XElement> Frames(XElement root, string visu)
        {
            foreach (var element in root.DescendantsAndSelf("Single"))
            {
                if (ScreenXml.NamedText(element, "VisualElementTypeName") != "VisuFbFrame") continue;
                var reference = element.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "VisNodeRefs33");
                if (reference != null && reference.Value.Trim() == visu) yield return element;
            }
        }

        // How many parameter members the frame sets: the instance with the
        // fewest makes the cleanest template.
        internal static int SetParameters(XElement frame)
        {
            var members = ScreenXml.Members(frame);
            return Parameters(frame).Count(parameter => members.ContainsKey(parameter.MemberId));
        }

        // The interface parameters listed under the first non-empty
        // VisNodeRefs33, with the value this instance gives each.
        internal static List<Parameter> Parameters(XElement frame)
        {
            var parameters = new List<Parameter>();
            var reference = frame.DescendantsAndSelf("Single").FirstOrDefault(node => (string)node.Attribute("Name") == "VisNodeRefs33" && node.Value.Trim().Length > 0);
            var children = reference?.Parent == null ? null : ScreenXml.Named(reference.Parent, "List", "TypeNodeChildren");
            if (children == null) return parameters;
            var members = ScreenXml.Members(frame);
            foreach (var node in children.Elements("Single"))
            {
                var name = ScreenXml.Named(node, "Single", "TypeNodeName")?.Value.Trim() ?? "";
                var id = ScreenXml.Named(node, "Single", "TypeNodeIdLong")?.Value.Trim();
                if (name.Length == 0 || !long.TryParse(id, NumberStyles.Integer, CultureInfo.InvariantCulture, out var memberId)) continue;
                var type = ScreenXml.Named(node, "Single", "TypeNodeType");
                parameters.Add(new Parameter
                {
                    Name = name,
                    MemberId = memberId,
                    IecType = type == null ? "" : ScreenXml.NamedText(type, "QualifiedName"),
                    Default = members.TryGetValue(memberId, out var member) ? member.Value ?? "" : "",
                });
            }
            return parameters;
        }

        internal static string Template(XElement frame, ICollection<long> parameterIds)
        {
            var copy = new XElement(frame);
            var list = ScreenXml.MemberList(copy);
            if (list != null)
            {
                foreach (var member in ScreenXml.MemberEntries(copy).ToList())
                {
                    var id = long.Parse(ScreenXml.Named(member, "Single", "Id").Value.Trim(), CultureInfo.InvariantCulture);
                    if (parameterIds.Contains(id)) member.Remove();
                    else if (Geometry.TryGetValue(id, out var placeholder)) ScreenXml.Named(member, "Single", "Value")?.SetValue(placeholder);
                }
            }
            foreach (var node in copy.DescendantsAndSelf("Single"))
            {
                var name = (string)node.Attribute("Name");
                var text = node.HasElements ? null : node.Value;
                if (name == "VisualElementIdentifier" && text != null && Generated.IsMatch(text)) node.SetValue("@@IDENTIFIER@@");
                if (name == "VisualElementId" && (string)node.Attribute("Type") == "int" && text != null && Digits.IsMatch(text)) node.SetValue("@@VISUAL_ELEMENT_ID@@");
            }
            if (list != null)
            {
                list = ScreenXml.MemberList(copy);
                while (list.LastNode is XText space && string.IsNullOrWhiteSpace(space.Value)) space.Remove();
                list.Add(new XText("\n" + new string(' ', 16) + "@@PARAM_MEMBERS@@\n" + new string(' ', 12)));
            }
            return copy.ToString(SaveOptions.DisableFormatting);
        }

        // The catalog `cts visu add --type frame` reads beside the template.
        internal static IDictionary<string, object> Catalog(string visu, IEnumerable<Parameter> parameters)
        {
            return new Dictionary<string, object>
            {
                ["type"] = "frame",
                ["visualElementTypeName"] = "VisuFbFrame",
                ["visu"] = visu,
                ["golden_template"] = visu + ".xml.tmpl",
                ["base_members"] = new List<object>(),
                ["params"] = parameters.Select(parameter => (object)new Dictionary<string, object>
                {
                    ["name"] = parameter.Name,
                    ["member_id"] = parameter.MemberId,
                    ["iec_type"] = parameter.IecType,
                    ["default"] = parameter.Default,
                }).ToList(),
            };
        }
    }
}
