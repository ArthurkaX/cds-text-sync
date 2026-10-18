using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;

namespace Cts.Sync
{
    internal static class SnapshotReader
    {
        static readonly Dictionary<string, string> Pathless = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) {
            {"8753fe6f-4a22-4320-8103-e553c4fc8e04", "POUs"}, {"085afe48-c5d8-4ea5-ab0d-b35701fa6009", "POUs"},
            {"63784cbb-9ba0-45e6-9d69-babf3f040511", "POUs"}, {"adb5cb65-8e1d-4a00-b70a-375ea27582f3", "POUs"} };
        // A project-level object of these types has no device path; the view keeps it under POUs/.
        internal static bool UnderPous(string type) => type != null && Pathless.ContainsKey(type.Trim().Trim('{', '}'));
        static readonly HashSet<string> AliasTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { "6f9dac99-8de1-4efc-8465-68ac443b7d08", "ffbfa93a-b94d-45fc-a329-229860183b1d", "2db5746d-d284-4425-9f7f-2663a34b0ebc" };
        static readonly Dictionary<string, string> Localized = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase) { { "PLC逻辑", "Plc Logic" }, { "任务配置", "Task Configuration" } };
        internal static ProjectModel Read(string path)
        {
            var doc = XDocument.Load(path, LoadOptions.PreserveWhitespace);
            var root = doc.Root;
            if (root == null) throw new InvalidOperationException("Snapshot has no root element");
            var model = new ProjectModel { Namespace = root.Name.NamespaceName };
            XNamespace ns = root.Name.Namespace;
            var views = root.Descendants(ns + "StructuredView").ToList();
            var lists = new List<XElement>();
            if (views.Count == 0) lists.AddRange(root.Descendants(ns + "List2").Where(e => (string)e.Attribute("Name") == "EntryList"));
            else foreach (var view in views) lists.AddRange(view.Descendants(ns + "List2").Where(e => (string)e.Attribute("Name") == "EntryList"));
            var fields = lists.SelectMany(list => list.Elements(ns + "Single")).Select(entry => Fields(entry, ns)).Where(item => item != null);
            return FromSkeleton(fields, root.Name.NamespaceName);
        }

        internal static ProjectModel FromSkeleton(IEnumerable<SnapshotNodeFields> fields, string namespaceName)
        {
            var model = new ProjectModel { Namespace = namespaceName ?? "" };
            var parsed = new List<ProjectNode>();
            foreach (var fieldsForNode in fields)
            {
                var guid = Normalize(fieldsForNode.Guid);
                var type = fieldsForNode.Type ?? "";
                var name = string.IsNullOrWhiteSpace(fieldsForNode.Name) ? "Unknown" : fieldsForNode.Name.Trim();
                if (string.IsNullOrEmpty(guid) || model.Nodes.ContainsKey(guid)) continue;
                if (type.Trim().Trim('{', '}').Equals("1c2acac5-35d6-4f83-b11f-df306c83e706", StringComparison.OrdinalIgnoreCase) && name.StartsWith("__", StringComparison.Ordinal)) continue;
                var node = new ProjectNode { Guid = guid, Name = name, Type = type, ParentGuid = Normalize(fieldsForNode.ParentGuid), Entry = fieldsForNode.Entry };
                if (fieldsForNode.Path != null) node.DisplayPath.AddRange(fieldsForNode.Path.Select(part => Localized.TryGetValue(part, out var canonical) ? canonical : part));
                if (node.DisplayPath.Count == 0 && UnderPous(type)) node.DisplayPath.Add("POUs");
                if (node.DisplayPath.Count == 0 && type.Trim().Trim('{', '}').Equals("9001d745-b9c5-4d77-90b7-b29c3f77a23b", StringComparison.OrdinalIgnoreCase))
                {
                    node.DisplayPath.Add("Resources");
                    node.DisplayPath.Add("Embedded");
                    var source = name.Split(new[] { '|' }, 2).Last().Replace('\\', '/');
                    node.OutputName = source.Split('/').LastOrDefault();
                    if (string.IsNullOrEmpty(node.OutputName)) node.OutputName = name;
                }
                if (node.DisplayPath.Count == 0 && type.Trim().Trim('{', '}').Equals("2bef0454-1bd3-412a-ac2c-af0f31dbc40f", StringComparison.OrdinalIgnoreCase) && name == "System") node.DisplayPath.Add("Resources");
                if (fieldsForNode.Entry != null) ReadEntryMetadata(node, fieldsForNode.Entry);
                parsed.Add(node);
            }
            foreach (var node in Deduplicate(parsed))
            {
                model.Nodes.Add(node.Guid, node);
                if (node.ParentGuid == null) model.RootNodes.Add(node);
            }
            AlignPaths(model);
            return model;
        }

        static SnapshotNodeFields Fields(XElement entry, XNamespace ns)
        {
            var meta = Child(entry, "MetaObject");
            var guid = Normalize(Value(Child(meta, "Guid")));
            if (guid.Length == 0) return null;
            var path = entry.Elements(ns + "Array").FirstOrDefault(element => (string)element.Attribute("Name") == "Path");
            return new SnapshotNodeFields
            {
                Guid = guid,
                ParentGuid = Normalize(Value(Child(meta, "ParentGuid"))),
                Name = Value(Child(meta, "Name")),
                Type = Value(Child(meta, "TypeGuid")),
                Path = path == null ? new string[0] : path.Elements().Select(element => Value(element).Trim()).Where(value => value.Length > 0).ToList(),
                IsRoot = Value(Child(entry, "IsRoot")).Equals("True", StringComparison.OrdinalIgnoreCase),
                Entry = entry,
            };
        }

        static string Normalize(string value)
        {
            var normalized = (value ?? "").Trim().Trim('{', '}').ToLowerInvariant();
            return normalized == "00000000-0000-0000-0000-000000000000" ? null : normalized;
        }

        static void ReadEntryMetadata(ProjectNode node, XElement entry)
        {
            var impl = Child(Child(entry, "Object"), "Implementation");
            if (impl == null) return;
            if (!impl.Descendants().Any(element => (string)element.Attribute("Name") == "TextBlobForSerialisation" || (string)element.Attribute("Name") == "TextLines")) node.Metadata["graphical"] = true;
        }
        static IEnumerable<ProjectNode> Deduplicate(IList<ProjectNode> nodes)
        {
            var output = new List<ProjectNode>();
            foreach (var node in nodes)
            {
                var type = (node.Type ?? "").Trim().Trim('{', '}');
                if (!AliasTypes.Contains(type)) { output.Add(node); continue; }
                var key = (node.OutputName ?? node.Name).ToLowerInvariant();
                var candidatePath = OutputKey(node);
                var existingIndex = output.FindIndex(existing => AliasTypes.Contains((existing.Type ?? "").Trim().Trim('{', '}')) && string.Equals((existing.OutputName ?? existing.Name).ToLowerInvariant(), key, StringComparison.Ordinal) && IsSuffixAlias(OutputKey(existing), candidatePath));
                if (existingIndex < 0) { output.Add(node); continue; }
                if (candidatePath.Length > OutputKey(output[existingIndex]).Length) output[existingIndex] = node;
            }
            return output;
        }
        static string[] OutputKey(ProjectNode node) { return node.DisplayPath.Where(p => p.Trim().Length > 0).Select(p => p.Trim().ToLowerInvariant()).Concat(new[] { (node.OutputName ?? node.Name).Trim().ToLowerInvariant() }).ToArray(); }
        static bool IsSuffixAlias(string[] a, string[] b)
        {
            if (a.Length == b.Length) return false;
            var shortPath = a.Length < b.Length ? a : b; var longPath = a.Length < b.Length ? b : a;
            return longPath.Skip(longPath.Length - shortPath.Length).SequenceEqual(shortPath);
        }
        // CODESYS records each object's Path from the tree's folder labels,
        // which can differ in case from the parent's own name ("PLC Logic"
        // below "Plc Logic"); on a case-sensitive disk that splits one folder
        // in two. A path that matches the parent chain apart from case takes
        // the parent's spelling, parents first; a folder, which has no parent
        // GUID, takes the spelling the parented objects use for its segments.
        static void AlignPaths(ProjectModel model)
        {
            foreach (var node in model.Nodes.Values.OrderBy(n => Depth(model, n)))
            {
                var parent = ParentOf(model, node);
                var recorded = node.DisplayPath.Where(p => p.Length > 0).ToList();
                if (parent == null || recorded.Count == 0) continue;
                var derived = parent.DisplayPath.Where(p => p.Length > 0).Select(model.SafeComponent)
                    .Concat(new[] { model.SafeComponent(parent.OutputName ?? parent.Name) }).ToList();
                var shared = Math.Min(recorded.Count, derived.Count);
                if (!recorded.Take(shared).SequenceEqual(derived.Take(shared), StringComparer.OrdinalIgnoreCase)) continue;
                SetPath(node, derived.Take(recorded.Count).Concat(recorded.Skip(derived.Count)));
            }
            var spelling = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var node in model.Nodes.Values.Where(n => ParentOf(model, n) != null).OrderBy(n => n.DisplayPath.Count).ThenBy(n => n.Guid, StringComparer.Ordinal))
            {
                var parts = node.DisplayPath.Where(p => p.Length > 0).ToList();
                for (var depth = 0; depth < parts.Count; depth++)
                {
                    var key = SegmentKey(parts, depth);
                    if (!spelling.ContainsKey(key)) spelling[key] = parts[depth];
                }
            }
            foreach (var node in model.Nodes.Values.Where(n => ParentOf(model, n) == null).ToList())
            {
                var recorded = node.DisplayPath.Where(p => p.Length > 0).ToList();
                SetPath(node, recorded.Select((part, depth) => spelling.TryGetValue(SegmentKey(recorded, depth), out var known) ? known : part));
            }
        }
        static string SegmentKey(IList<string> parts, int depth) { return string.Join("\0", parts.Take(depth + 1)).ToLowerInvariant(); }
        static void SetPath(ProjectNode node, IEnumerable<string> parts)
        {
            var path = parts.ToList();
            if (path.SequenceEqual(node.DisplayPath.Where(p => p.Length > 0))) return;
            node.DisplayPath.Clear();
            node.DisplayPath.AddRange(path);
        }
        static ProjectNode ParentOf(ProjectModel model, ProjectNode node)
        {
            return node.ParentGuid != null && model.Nodes.TryGetValue(node.ParentGuid, out var parent) && parent != node ? parent : null;
        }
        static int Depth(ProjectModel model, ProjectNode node)
        {
            var seen = new HashSet<string>();
            var depth = 0;
            for (var current = ParentOf(model, node); current != null && seen.Add(current.Guid); current = ParentOf(model, current)) depth++;
            return depth;
        }
        static XElement Child(XElement e, string name) { return e == null ? null : e.Elements().FirstOrDefault(c => (string)c.Attribute("Name") == name); }
        static string Value(XElement e) { return e == null ? "" : e.Value; }
    }
}
