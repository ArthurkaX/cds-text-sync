using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using static Cts.Agent.JsonMap;

namespace Cts.Sync
{
    // A partial export: the objects an edit touched, fetched and patched into the previous view.
    public static partial class ViewExport
    {
        internal static IList<string> ExpandFetchGuids(ProjectModel model, IEnumerable<string> changedGuids)
        {
            var projections = TypeKinds.All.Projections.ToList();
            var selected = new HashSet<string>(changedGuids, StringComparer.OrdinalIgnoreCase);
            foreach (var guid in selected.ToList())
            {
                if (!model.Nodes.TryGetValue(guid, out var changed)) continue;
                var parts = changed.Parts(model);
                var kind = TypeKinds.All.Kind(changed.Type);
                if (IsMemberType(kind) && parts.Count > 1)
                {
                    model.Nodes.TryGetValue(changed.ParentGuid ?? "", out var owner);
                    owner = owner ?? model.Nodes.Values.FirstOrDefault(node => node.Parts(model).SequenceEqual(parts.Take(parts.Count - 1), StringComparer.OrdinalIgnoreCase));
                    if (owner != null) parts = owner.Parts(model);
                }
                if (!IsMemberType(kind) && projections.Any(projection => ProjectionApplies(projection, kind) && string.Equals(Text(projection, "format"), "st", StringComparison.OrdinalIgnoreCase)))
                {
                    foreach (var child in model.Nodes.Values.Where(node => node.Guid != changed.Guid && WithinOwner(model, node, changed.Guid, parts)))
                        if (IsMemberType(TypeKinds.All.Kind(child.Type))) selected.Add(child.Guid);
                }
                var prefix = parts.ToArray();
                var ownerGuid = model.Nodes.TryGetValue(changed.ParentGuid ?? "", out var parentNode) && IsMemberType(kind) ? parentNode.Guid : changed.Guid;
                foreach (var member in model.Nodes.Values.Where(node => WithinOwner(model, node, ownerGuid, prefix)))
                    if (IsMemberType(TypeKinds.All.Kind(member.Type))) selected.Add(member.Guid);
                var rootNode = model.Nodes.Values.FirstOrDefault(node => node.Parts(model).SequenceEqual(prefix, StringComparer.OrdinalIgnoreCase));
                if (rootNode != null) selected.Add(rootNode.Guid);
            }
            // An alarm group's .csv is rendered from it and its messages together.
            foreach (var guid in selected.ToList())
            {
                if (!model.Nodes.TryGetValue(guid, out var node)) continue;
                var twin = TypeKinds.All.Kind(node.Type) == "alarm_config_item" ? AlarmMessages(model, node) : AlarmGroupOf(model, node);
                if (twin != null) selected.Add(twin.Guid);
            }
            // A member renders inside its owner's file: one fetched without
            // its owner would be written as a file of its own.
            foreach (var guid in selected.ToList())
            {
                if (!model.Nodes.TryGetValue(guid, out var member) || !IsMemberType(TypeKinds.All.Kind(member.Type))) continue;
                var owner = member;
                while (owner.ParentGuid != null && model.Nodes.TryGetValue(owner.ParentGuid, out var parent) && IsMemberType(TypeKinds.All.Kind(owner.Type))) owner = parent;
                if (owner == member) continue;
                selected.Add(owner.Guid);
                foreach (var sibling in model.Nodes.Values.Where(node => DescendsFrom(model, node, owner.Guid)))
                    if (IsMemberType(TypeKinds.All.Kind(sibling.Type))) selected.Add(sibling.Guid);
            }
            return selected.OrderBy(guid => guid, StringComparer.OrdinalIgnoreCase).ToList();
        }

        static bool DescendsFrom(ProjectModel model, ProjectNode node, string ancestor)
        {
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            for (var parent = node.ParentGuid; parent != null && seen.Add(parent) && model.Nodes.TryGetValue(parent, out var parentNode); parent = parentNode.ParentGuid)
                if (string.Equals(parent, ancestor, StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        static bool WithinOwner(ProjectModel model, ProjectNode node, string ancestorGuid, IList<string> parts)
        {
            var nodeParts = node.Parts(model);
            return DescendsFrom(model, node, ancestorGuid)
                || (nodeParts.Count > parts.Count && nodeParts.Take(parts.Count).SequenceEqual(parts, StringComparer.OrdinalIgnoreCase));
        }

        internal static string PartialFallbackReason(ProjectModel model, IEnumerable<string> changedGuids, IEnumerable<string> fetchGuids)
        {
            var guids = fetchGuids.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            if (guids.Count > 50) return "more than 50 objects need entries";
            foreach (var guid in changedGuids.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                if (!model.Nodes.TryGetValue(guid, out var node)) continue;
                if (model.IsCollapsed(node)) return "a collapsed parent changed";
                if (string.Equals(node.Name, "Project Settings", StringComparison.OrdinalIgnoreCase)
                    || string.Equals((node.Type ?? "").Trim().Trim('{', '}'), "8753fe6f-4a22-4320-8103-e553c4fc8e04", StringComparison.OrdinalIgnoreCase)) return "Project Settings changed";
            }
            return null;
        }

        internal static ViewPatchResult Patch(ProjectModel model, IViewFiles previous, IDictionary<string, IList<string>> previousGuidFiles, IViewFiles subset, IDictionary<string, IList<string>> subsetGuidFiles, IEnumerable<string> changedGuids, IEnumerable<string> removedGuids)
        {
            var changed = new HashSet<string>(changedGuids, StringComparer.OrdinalIgnoreCase);
            var removed = new HashSet<string>(removedGuids, StringComparer.OrdinalIgnoreCase);
            var files = new MemoryViewFiles();
            var baselinePaths = new HashSet<string>(previous.Paths, StringComparer.OrdinalIgnoreCase);
            var removedPaths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var guidFiles = previousGuidFiles.ToDictionary(pair => pair.Key, pair => (IList<string>)pair.Value.ToList(), StringComparer.OrdinalIgnoreCase);
            foreach (var guid in removed)
            {
                RemoveGuidFiles(files, guidFiles, guid, baselinePaths, removedPaths);
            }
            foreach (var guid in changed)
            {
                RemoveGuidFiles(files, guidFiles, guid, baselinePaths, removedPaths);
                if (!model.Nodes.ContainsKey(guid)) continue;
                if (!subsetGuidFiles.TryGetValue(guid, out var renderedPaths)) renderedPaths = new List<string>();
                guidFiles[guid] = renderedPaths.ToList();
                foreach (var path in renderedPaths) WritePatchFile(files, removedPaths, path, subset.Read(path));
            }
            foreach (var item in guidFiles.ToList())
            {
                if (changed.Contains(item.Key) || removed.Contains(item.Key)) continue;
                if (!model.Nodes.TryGetValue(item.Key, out var node))
                {
                    RemoveGuidFiles(files, guidFiles, item.Key, baselinePaths, removedPaths);
                    continue;
                }
                var moved = new List<string>();
                foreach (var oldPath in item.Value)
                {
                    var newPath = RelocatedPath(model, node, oldPath);
                    if (string.Equals(oldPath, newPath, StringComparison.OrdinalIgnoreCase))
                    {
                        moved.Add(oldPath);
                        continue;
                    }
                    if (Path.GetExtension(oldPath).Equals(".xml", StringComparison.OrdinalIgnoreCase))
                        return Fallback(files, guidFiles, "a moved native XML needs a fresh entry");
                    var bytes = files.Paths.Contains(oldPath, StringComparer.OrdinalIgnoreCase) ? files.Read(oldPath) : previous.Read(oldPath);
                    RemovePatchFile(files, removedPaths, oldPath, baselinePaths);
                    if (files.Paths.Contains(newPath, StringComparer.OrdinalIgnoreCase) || (baselinePaths.Contains(newPath) && !removedPaths.Contains(newPath)))
                        return Fallback(files, guidFiles, "a moved file collides with another rendered file");
                    WritePatchFile(files, removedPaths, newPath, bytes);
                    moved.Add(newPath);
                }
                guidFiles[item.Key] = moved;
            }
            return new ViewPatchResult { Files = new OverlayViewFiles(previous, files, removedPaths), GuidFiles = guidFiles };
        }

        static ViewPatchResult Fallback(MemoryViewFiles files, IDictionary<string, IList<string>> guidFiles, string reason)
        {
            return new ViewPatchResult { Files = files, GuidFiles = guidFiles, FallbackReason = reason };
        }

        static void RemoveGuidFiles(MemoryViewFiles files, IDictionary<string, IList<string>> guidFiles, string guid, HashSet<string> baselinePaths, HashSet<string> removedPaths)
        {
            if (!guidFiles.TryGetValue(guid, out var paths)) return;
            foreach (var path in paths) RemovePatchFile(files, removedPaths, path, baselinePaths);
            guidFiles.Remove(guid);
        }

        static void RemovePatchFile(MemoryViewFiles files, HashSet<string> removedPaths, string path, HashSet<string> baselinePaths)
        {
            files.Remove(path);
            if (baselinePaths.Contains(path)) removedPaths.Add(path);
        }

        static void WritePatchFile(MemoryViewFiles files, HashSet<string> removedPaths, string path, byte[] bytes)
        {
            removedPaths.Remove(path);
            files.Write(path, bytes);
        }

        static string RelocatedPath(ProjectModel model, ProjectNode node, string path)
        {
            var extension = Path.GetExtension(path);
            if (extension.Equals(".st", StringComparison.OrdinalIgnoreCase)) return string.Join("/", node.Parts(model)) + ".st";
            if (extension.Equals(".csv", StringComparison.OrdinalIgnoreCase)) return ReplaceExtension(model.XmlPath(node), ".csv");
            if (extension.Equals(".xml", StringComparison.OrdinalIgnoreCase)) return model.XmlPath(node);
            return path;
        }
    }
}
