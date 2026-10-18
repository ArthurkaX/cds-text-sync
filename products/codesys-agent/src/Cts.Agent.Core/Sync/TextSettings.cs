using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;
using Cts.Agent;

namespace Cts.Sync
{
    internal static class TextSettings
    {
        static readonly HashSet<string> TextParts = new HashSet<string> { "Implementation", "Interface" };
        // Ids the IDE makes for an object of its own, a new one on each create.
        static readonly HashSet<string> Bookkeeping = new HashSet<string> { "UniqueIdGenerator", "IsGet", "GuidImplicitDUT", "GuidImplicitGVL", "guidinit", "guidcyclic" };
        // Fields of a persistent variable list a new one has; another value stays beside it.
        static readonly Dictionary<string, string> Defaults = new Dictionary<string, string> { { "dymmattributecount", "0" } };
        static readonly HashSet<string> Empty = new HashSet<string> { "ChildObjectGuids" };
        internal static bool Outside(XElement entry)
        {
            var meta = Child(entry, "MetaObject");
            var properties = Child(meta, "Properties");
            if (properties != null)
            foreach (var property in properties.Elements())
            {
                var key = property.Elements().FirstOrDefault(e => e.Name.LocalName == "Key")?.Value.Trim().Trim('{', '}').ToLowerInvariant() ?? "";
                if (key == ObjectKinds.FolderPlacementProperty) continue;
                if (key == StPragma.BuildProperty)
                {
                    var value = property.Elements().FirstOrDefault(e => e.Name.LocalName == "Value");
                    var fields = value?.Descendants().Where(e => e.Attribute("Name") != null).ToList() ?? new List<XElement>();
                    foreach (var field in fields)
                    {
                        var name = (string)field.Attribute("Name");
                        if (InPragma("BuildProperty", field)) continue;
                        if (name == "Undefines" && !field.Elements().Any()) continue;
                        return true;
                    }
                    continue;
                }
                return true;
            }
            var obj = Child(entry, "Object");
            if (obj == null) return false;
            foreach (var field in obj.Elements())
            {
                var name = (string)field.Attribute("Name") ?? "";
                if (TextParts.Contains(name) || Bookkeeping.Contains(name) || InPragma("", field)) continue;
                if (Empty.Contains(name) && !field.Elements().Any()) continue;
                if (Defaults.TryGetValue(name, out var initial) && !field.HasElements && field.Value.Trim() == initial) continue;
                // An unset field (a persistent list's persvarlist, a GVL's NetVarProperties) holds no setting.
                if (field.Name.LocalName == "Null") continue;
                return true;
            }
            return false;
        }
        // Whether the cts pragma carries *field* (a setting whose value fits in it).
        static bool InPragma(string prop, XElement field) =>
            !field.HasElements && StPragma.Fits(field.Value)
            && StPragma.Settings.Any(setting => setting.Prop == prop && setting.Name == (string)field.Attribute("Name"));
        static XElement Child(XElement element, string name) { return element?.Elements().FirstOrDefault(e => (string)e.Attribute("Name") == name); }
    }
}
