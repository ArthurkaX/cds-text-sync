// The order and placement of a structured view's entries in an export: a
// depth-first walk of the view's nodes in children order, each entry carrying
// the display names of its ancestors (Path -- "PLC Logic" even when the object
// is named "Plc Logic"), its parent node's object and whether it is a root.
// The same nodes also make `project.tree` (Tree).  The IDE's node type is
// reached through the delegates, so the walk itself is tested on Linux
// against plain stand-ins.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    public sealed class SvPlacement
    {
        public Guid Object { get; set; }
        public bool IsRoot { get; set; }
        public Guid ParentNode { get; set; }
        public string[] Path { get; set; }
        public int Index { get; set; }
    }

    public sealed class SvNodeAccess
    {
        public Func<object, Guid> ObjectOf { get; set; }
        public Func<object, string> NameOf { get; set; }
        // The object's own name, which the export names its file by; the
        // node's Name is the label the IDE shows ("Symbol Configuration").
        public Func<object, string> ObjectNameOf { get; set; }
        public Func<object, IEnumerable<object>> ChildrenOf { get; set; }
        public Func<object, int> IndexOf { get; set; }
        public Func<object, Guid> TypeOf { get; set; }
        // A node with no export entry (a task-call reference): it and its
        // subtree are skipped.
        public Func<object, bool> Skip { get; set; }
    }

    public static class SvWalk
    {
        public static IEnumerable<SvPlacement> Walk(IEnumerable<object> roots, SvNodeAccess access)
        {
            foreach (var root in roots)
                foreach (var placement in Visit(root, access, Guid.Empty, new List<string>()))
                    yield return placement;
        }

        // Every node as the project tree, task calls included, below the node
        // the IDE shows it under: an object in a folder is below the folder,
        // where its ParentObjectGuid names the application.
        public static List<ProjectNode> Tree(IEnumerable<object> roots, SvNodeAccess access)
        {
            return roots.Select(root => TreeNode(root, access)).ToList();
        }

        static ProjectNode TreeNode(object node, SvNodeAccess access)
        {
            var result = new ProjectNode
            {
                Name = access.NameOf(node) ?? "",
                ObjectName = access.ObjectNameOf == null ? null : access.ObjectNameOf(node),
                Guid = access.ObjectOf(node).ToString("D"),
                Type = access.TypeOf == null ? null : access.TypeOf(node).ToString("D"),
            };
            foreach (var child in access.ChildrenOf(node) ?? new object[0])
                result.Children.Add(TreeNode(child, access));
            return result;
        }

        static IEnumerable<SvPlacement> Visit(object node, SvNodeAccess access, Guid parent, List<string> path)
        {
            if (access.Skip != null && access.Skip(node)) yield break;
            var guid = access.ObjectOf(node);
            yield return new SvPlacement
            {
                Object = guid,
                IsRoot = path.Count == 0,
                ParentNode = parent,
                Path = path.ToArray(),
                Index = access.IndexOf == null ? -1 : access.IndexOf(node),
            };
            path.Add(access.NameOf(node) ?? "");
            foreach (var child in access.ChildrenOf(node) ?? new object[0])
                foreach (var placement in Visit(child, access, guid, path))
                    yield return placement;
            path.RemoveAt(path.Count - 1);
        }
    }
}
