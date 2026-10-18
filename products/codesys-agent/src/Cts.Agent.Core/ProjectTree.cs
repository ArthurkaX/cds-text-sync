using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public sealed class ProjectNode
    {
        public string Name { get; set; }
        public string ObjectName { get; set; }
        public string Guid { get; set; }
        public string Type { get; set; }
        public IList<ProjectNode> Children { get; set; } = new List<ProjectNode>();
    }

    public static class ProjectTree
    {
        public static Dictionary<string, object> Build(ProjectNode root, int depth)
        {
            if (root == null) throw new ArgumentNullException("root");
            return BuildNode(root, depth, 0);
        }

        static Dictionary<string, object> BuildNode(ProjectNode item, int depth, int level)
        {
            var result = new Dictionary<string, object> { { "name", item.Name ?? "" } };
            // Only where it differs: the IDE labels a few objects by their kind.
            if (!String.IsNullOrEmpty(item.ObjectName) && item.ObjectName != item.Name) result["object_name"] = item.ObjectName;
            if (!String.IsNullOrEmpty(item.Guid)) result["guid"] = item.Guid;
            if (!String.IsNullOrEmpty(item.Type)) result["type"] = item.Type;
            if (depth > 0 && level >= depth) return result;
            var children = item.Children.Select(child => BuildNode(child, depth, level + 1)).ToList();
            if (children.Count > 0) result["children"] = children;
            return result;
        }
    }
}
