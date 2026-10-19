using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // The IDE side's cache: the last export's snapshot, file map and stamps, reused while the IDE is unchanged.
    internal static partial class ComparePlanner
    {
        // A cached commit that git no longer has fails when its tree is read,
        // and that run falls back to a full export.
        static IDictionary<string, object> ReadIdeCache(string path, string project)
        {
            try
            {
                var cache = Cts.Agent.Json.Parse(File.ReadAllText(path)) as IDictionary<string, object>;
                if (cache == null || !string.Equals(Convert.ToString(cache["project"]), project, StringComparison.Ordinal)
                    || string.IsNullOrEmpty(Convert.ToString(cache["commit"]))) return null;
                return cache;
            }
            catch { return null; }
        }

        static Dictionary<string, SnapshotStamp> ReadSnapshotTimes(object raw)
        {
            var result = new Dictionary<string, SnapshotStamp>(StringComparer.OrdinalIgnoreCase);
            if (!(raw is IDictionary<string, object> values)) return result;
            foreach (var pair in values)
            {
                if (!(pair.Value is IDictionary<string, object> stamp) || !stamp.ContainsKey("guid") || !stamp.ContainsKey("timestamp")) continue;
                result[pair.Key] = new SnapshotStamp { Guid = Convert.ToString(stamp["guid"]), Timestamp = Convert.ToInt64(stamp["timestamp"]) };
            }
            return result;
        }

        static IdeCacheAttempt TryIdeCache(CliCall call, GitRepository.Facts facts, string viewRelative, string snapshot, string cachePath, IDictionary<string, object> cache)
        {
            var attempt = new IdeCacheAttempt();
            var folder = facts.Root;
            try
            {
                var cached = ReadCachedIdeState(cache);
                if (cached == null) return attempt;
                var clock = Stopwatch.StartNew();
                var reply = call.Call("project.skeleton", new Dictionary<string, object>());
                clock.Stop();
                attempt.ExportSeconds = clock.Elapsed.TotalSeconds;
                if (!(reply.TryGetValue("nodes", out var rawNodes) && rawNodes is IList<object>)) return attempt;
                var current = ReadSkeleton((IList<object>)rawNodes);
                var changes = FindSkeletonChanges(cached.Fields, current);
                if (changes.Changed.Count == 0 && changes.Removed.Count == 0)
                {
                    attempt.Files = new GitTreeViewFiles(folder, cached.Commit, viewRelative);
                    attempt.Times = ReadSnapshotTimes(cache["times"]);
                    attempt.State = "hit";
                    attempt.Success = true;
                    return attempt;
                }
                return ExportAndPatchIdeSubset(call, facts, viewRelative, snapshot, cachePath, cached, current, changes, attempt);
            }
            catch (CliFailure failure) when (failure.Declined)
            {
                return attempt;
            }
            catch (Exception error) when (error is InvalidOperationException || error is IOException || error is ArgumentException
                || error is UnauthorizedAccessException || error is FormatException || error is InvalidCastException
                || error is KeyNotFoundException || error is NullReferenceException || error is OverflowException)
            {
                return attempt;
            }
        }

        static CachedIdeState ReadCachedIdeState(IDictionary<string, object> cache)
        {
            // Another cts build renders the IDE's objects its own way.
            if (!(cache.TryGetValue("build", out var build) && Equals(Convert.ToString(build), CliRun.Build()))) return null;
            if (!(cache.TryGetValue("skeleton", out var rawSkeleton) && rawSkeleton is IList<object> skeleton)) return null;
            if (!(cache.TryGetValue("guid_files", out var rawFiles) && rawFiles is IDictionary<string, object>)) return null;
            if (!(cache.TryGetValue("commit", out var rawCommit) && rawCommit is string commit)) return null;
            return new CachedIdeState { Fields = ReadSkeleton(skeleton), GuidFiles = ReadGuidFiles(rawFiles), Commit = commit };
        }

        static SkeletonChanges FindSkeletonChanges(IList<SnapshotNodeFields> previous, IList<SnapshotNodeFields> current)
        {
            var oldModel = SnapshotReader.FromSkeleton(previous, "");
            var currentModel = SnapshotReader.FromSkeleton(current, "");
            var oldByGuid = previous.ToDictionary(field => field.Guid, StringComparer.OrdinalIgnoreCase);
            var changed = current.Where(field => !oldByGuid.TryGetValue(field.Guid, out var old) || old.Timestamp != field.Timestamp).Select(field => field.Guid).ToList();
            var removed = previous.Select(field => field.Guid).Except(current.Select(field => field.Guid), StringComparer.OrdinalIgnoreCase).ToList();
            foreach (var field in current)
            {
                if (!oldModel.Nodes.TryGetValue(field.Guid, out var oldNode) || !currentModel.Nodes.TryGetValue(field.Guid, out var newNode)) continue;
                if (!oldNode.Parts(oldModel).SequenceEqual(newNode.Parts(currentModel), StringComparer.OrdinalIgnoreCase)) changed.Add(field.Guid);
            }
            return new SkeletonChanges { Changed = changed.Distinct(StringComparer.OrdinalIgnoreCase).ToList(), Removed = removed, OldModel = oldModel, CurrentModel = currentModel };
        }

        static IdeCacheAttempt ExportAndPatchIdeSubset(CliCall call, GitRepository.Facts facts, string viewRelative, string snapshot, string cachePath, CachedIdeState cached, IList<SnapshotNodeFields> fields, SkeletonChanges changes, IdeCacheAttempt attempt)
        {
            var folder = facts.Root;
            var fetch = DecideFetchGuids(changes);
            if (fetch == null) return attempt;
            var clock = Stopwatch.StartNew();
            call.Call("project.export", new Dictionary<string, object> { { "path", snapshot }, { "guids", fetch } });
            clock.Stop();
            attempt.ExportSeconds += clock.Elapsed.TotalSeconds;
            var partial = SnapshotReader.Read(snapshot);
            foreach (var field in fields)
                if (partial.Nodes.TryGetValue(field.Guid, out var partialNode)) field.Entry = partialNode.Entry;
            var sparse = SnapshotReader.FromSkeleton(fields, partial.Namespace);
            var subset = new MemoryViewFiles();
            clock.Restart();
            var rendered = ViewExport.WriteSubset(sparse, folder, subset, fetch);
            clock.Stop();
            attempt.RenderSeconds = clock.Elapsed.TotalSeconds;
            var previous = new GitTreeViewFiles(folder, cached.Commit, viewRelative);
            var patch = ViewExport.Patch(sparse, previous, cached.GuidFiles, subset, rendered.GuidFiles, fetch, changes.Removed);
            if (patch.FallbackReason != null)
            {
                previous.Dispose();
                return attempt;
            }
            var commit = CompareTool.Store(folder, viewRelative, patch.Files, facts, previous);
            WriteIdeCache(cachePath, call.Hello.ProjectPath, commit, patch.GuidFiles, fields, SnapshotTimes(fields, sparse));
            attempt.Times = SnapshotTimes(fields, sparse);
            attempt.State = "partial";
            attempt.Success = true;
            attempt.Files = patch.Files;
            return attempt;
        }

        static IList<string> DecideFetchGuids(SkeletonChanges changes)
        {
            var seeds = changes.Changed.ToList();
            foreach (var removed in changes.Removed)
            {
                var oldNode = changes.OldModel.Nodes[removed];
                if (oldNode.ParentGuid != null && changes.CurrentModel.Nodes.ContainsKey(oldNode.ParentGuid)) seeds.Add(oldNode.ParentGuid);
            }
            var fetch = ViewExport.ExpandFetchGuids(changes.CurrentModel, seeds).Where(changes.CurrentModel.Nodes.ContainsKey).ToList();
            return ViewExport.PartialFallbackReason(changes.CurrentModel, changes.Changed, fetch) == null ? fetch : null;
        }

        static Dictionary<string, IList<string>> ReadGuidFiles(object raw)
        {
            var result = new Dictionary<string, IList<string>>(StringComparer.OrdinalIgnoreCase);
            if (!(raw is IDictionary<string, object> values)) return result;
            foreach (var pair in values)
                if (pair.Value is IList<object> paths) result[pair.Key] = paths.Select(Convert.ToString).ToList();
            return result;
        }

        static List<SnapshotNodeFields> ReadSkeleton(IList<object> raw)
        {
            var result = new List<SnapshotNodeFields>();
            foreach (var item in raw.OfType<IDictionary<string, object>>())
            {
                result.Add(new SnapshotNodeFields
                {
                    Guid = Convert.ToString(item["guid"]), ParentGuid = Convert.ToString(item["parent_guid"]),
                    Name = Convert.ToString(item["name"]), Type = Convert.ToString(item["type_guid"]),
                    Path = item.TryGetValue("path", out var path) && path is IList<object> parts ? parts.Select(Convert.ToString).ToList() : new List<string>(),
                    IsRoot = item.TryGetValue("is_root", out var isRoot) && Equals(isRoot, true),
                    ViewGuid = Convert.ToString(item.ContainsKey("view_guid") ? item["view_guid"] : null),
                    Timestamp = Convert.ToInt64(item["timestamp"]),
                });
            }
            return result;
        }

        // A cache of another version renders the IDE afresh: version 1
        // could hold members of a partial render as files of their own.
        static void WriteIdeCache(string path, string project, string commit, IDictionary<string, IList<string>> guidFiles, IList<SnapshotNodeFields> fields, IDictionary<string, SnapshotStamp> times)
        {
            var nodeData = fields.Select(field => (object)new Dictionary<string, object>
            {
                { "guid", field.Guid }, { "parent_guid", field.ParentGuid }, { "name", field.Name }, { "type_guid", field.Type },
                { "path", field.Path?.Cast<object>().ToList() ?? new List<object>() }, { "is_root", field.IsRoot },
                { "view_guid", field.ViewGuid }, { "timestamp", field.Timestamp },
            }).ToList();
            var fileData = guidFiles.ToDictionary(pair => pair.Key, pair => (object)pair.Value.Cast<object>().ToList(), StringComparer.OrdinalIgnoreCase);
            var timeData = times.ToDictionary(pair => pair.Key, pair => (object)new Dictionary<string, object> { { "guid", pair.Value.Guid }, { "timestamp", pair.Value.Timestamp } }, StringComparer.OrdinalIgnoreCase);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, Cts.Agent.Json.Serialize(new Dictionary<string, object>
            {
                { "build", CliRun.Build() }, { "project", project }, { "commit", commit }, { "guid_files", fileData }, { "skeleton", nodeData }, { "times", timeData },
            }));
        }

        static bool SameFolder(string left, string right)
        {
            var comparison = Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
            return string.Equals(Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar), Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar), comparison);
        }
        static Dictionary<string, SnapshotStamp> SnapshotTimes(ProjectModel model)
        {
            var result = new Dictionary<string, SnapshotStamp>(StringComparer.OrdinalIgnoreCase);
            foreach (var node in model.Nodes.Values)
            {
                var meta = node.Entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject");
                var timestamp = meta?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Timestamp")?.Value;
                if (!long.TryParse(timestamp, out var ticks) || ticks <= 0 || ticks > DateTime.MaxValue.Ticks) continue;
                result[string.Join("/", node.Parts(model))] = new SnapshotStamp { Guid = node.Guid, Timestamp = ticks };
                var xmlPath = model.XmlPath(node);
                result[xmlPath] = new SnapshotStamp { Guid = node.Guid, Timestamp = ticks };
                result[Path.ChangeExtension(xmlPath, ".csv")] = new SnapshotStamp { Guid = node.Guid, Timestamp = ticks };
            }
            return result;
        }

        static Dictionary<string, SnapshotStamp> SnapshotTimes(IList<SnapshotNodeFields> fields, ProjectModel model)
        {
            var timestamps = fields.ToDictionary(field => field.Guid, field => field.Timestamp, StringComparer.OrdinalIgnoreCase);
            var result = new Dictionary<string, SnapshotStamp>(StringComparer.OrdinalIgnoreCase);
            foreach (var node in model.Nodes.Values)
            {
                if (!timestamps.TryGetValue(node.Guid, out var ticks) || ticks <= 0 || ticks > DateTime.MaxValue.Ticks) continue;
                var stamp = new SnapshotStamp { Guid = node.Guid, Timestamp = ticks };
                result[string.Join("/", node.Parts(model))] = stamp;
                var xmlPath = model.XmlPath(node);
                result[xmlPath] = stamp;
                result[Path.ChangeExtension(xmlPath, ".csv")] = stamp;
            }
            return result;
        }
    }
}
