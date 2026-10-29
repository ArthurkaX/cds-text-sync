using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Xml.Linq;

namespace Cts.Sync
{
    internal sealed class ProjectNode
    {
        internal string Guid, Name, Type, ParentGuid, OutputName;
        internal ProjectNode() { OutputName = null; }
        internal readonly List<string> DisplayPath = new List<string>();
        internal readonly Dictionary<string, object> Metadata = new Dictionary<string, object>();
        internal XElement Entry;
        internal List<string> Parts(ProjectModel model)
        {
            var result = DisplayPath.Where(p => p.Length != 0).Select(ProjectModel.SafeComponent).ToList();
            result.Add(ProjectModel.SafeComponent(OutputName ?? Name));
            if (model.HasCollision(this)) result[result.Count - 1] += "__" + Guid.Substring(0, 8);
            return result;
        }
        internal List<string> IdeParts() => DisplayPath.Where(p => p.Length != 0).Concat(new[] { OutputName ?? Name }).ToList();
    }

    internal sealed class SnapshotNodeFields
    {
        internal string Guid, ParentGuid, Name, Type;
        internal IList<string> Path;
        internal bool IsRoot;
        internal string ViewGuid;
        internal long Timestamp;
        internal XElement Entry;
    }

    internal sealed class ProjectModel
    {
        internal readonly Dictionary<string, ProjectNode> Nodes = new Dictionary<string, ProjectNode>();
        internal readonly List<ProjectNode> RootNodes = new List<ProjectNode>();
        Dictionary<string, int> collisionCounts;
        HashSet<string> outputChildPaths;
        HashSet<string> parentGuids;
        List<CollapsedNode> collapsedNodes;
        internal string Namespace;
        static readonly HashSet<string> Collapsed = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            "6f9dac99-8de1-4efc-8465-68ac443b7d08", "6654496c-404d-479a-aad2-8551054e5f1e" };
        internal static string SafeComponent(string value)
        {
            var safe = new StringBuilder(value ?? "object");
            for (var i = 0; i < safe.Length; i++)
            {
                if ("<>:\"/\\|?*".IndexOf(safe[i]) >= 0)
                {
                    safe[i] = '_';
                }
            }
            var trimmed = safe.ToString().Trim(' ', '.');
            return trimmed.Length > 0 ? trimmed : "object";
        }
        internal bool HasCollision(ProjectNode node)
        {
            if (collisionCounts == null)
            {
                collisionCounts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                foreach (var item in Nodes.Values)
                {
                    var key = CollisionKey(item);
                    collisionCounts[key] = collisionCounts.ContainsKey(key) ? collisionCounts[key] + 1 : 1;
                }
            }
            return collisionCounts[CollisionKey(node)] > 1;
        }
        string CollisionKey(ProjectNode node) { return string.Join("\0", node.DisplayPath.Select(SafeComponent).Concat(new[] { SafeComponent(node.OutputName ?? node.Name) })); }
        internal bool IsCollapsed(ProjectNode node) { return HoldsMembers(node.Type); }
        // Whether an object of *type* holds its members in its own file (a POU, an interface).
        internal static bool HoldsMembers(string type) { return Collapsed.Contains(type ?? ""); }
        internal ProjectNode CollapsedParent(ProjectNode node)
        {
            var path = node.DisplayPath.Where(p => p.Length != 0).Select(SafeComponent).ToArray();
            if (path.Length == 0) return null;
            if (collapsedNodes == null)
            {
                collapsedNodes = Nodes.Values.Where(IsCollapsed)
                    .Select(item => new CollapsedNode { Node = item, Parts = item.Parts(this) })
                    .OrderByDescending(item => item.Parts.Count)
                    .ToList();
            }
            var parent = collapsedNodes.FirstOrDefault(item => item.Node != node && path.Length >= item.Parts.Count
                && path.Take(item.Parts.Count).SequenceEqual(item.Parts, StringComparer.OrdinalIgnoreCase));
            return parent?.Node;
        }
        sealed class CollapsedNode
        {
            internal ProjectNode Node;
            internal List<string> Parts;
        }
        internal bool HasOutputChildren(ProjectNode node)
        {
            if (outputChildPaths == null)
            {
                outputChildPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                parentGuids = new HashSet<string>(Nodes.Values.Where(n => n.ParentGuid != null).Select(n => n.ParentGuid), StringComparer.OrdinalIgnoreCase);
                foreach (var item in Nodes.Values)
                    outputChildPaths.Add(string.Join("\0", item.DisplayPath.Select(SafeComponent)));
            }
            if (IsCollapsed(node)) return false;
            var path = node.Parts(this);
            return outputChildPaths.Contains(string.Join("\0", path)) || parentGuids.Contains(node.Guid);
        }
        internal string XmlPath(ProjectNode node)
        {
            var parent = CollapsedParent(node);
            if (parent != null)
            {
                // A member of a POU kept as XML lies beside it as Owner.Member.xml.
                var parentParts = parent.Parts(this);
                var nodePath = node.DisplayPath.Where(p => p.Length > 0).Select(SafeComponent).ToList();
                var tail = nodePath.Take(parentParts.Count).SequenceEqual(parentParts) ? nodePath.Skip(parentParts.Count).ToList() : new List<string>();
                tail.Add(SafeComponent(node.OutputName ?? node.Name));
                return string.Join("/", parentParts.Take(parentParts.Count - 1).Concat(new[] { string.Join(".", parentParts.Skip(parentParts.Count - 1).Concat(tail)) })) + ".xml";
            }
            var parts = node.Parts(this);
            return string.Join("/", HasOutputChildren(node) ? parts.Concat(new[] { ".cds-object.xml" }) : parts) + (HasOutputChildren(node) ? "" : ".xml");
        }
    }
}
