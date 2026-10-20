using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // Compare the exported IDE view with the working view, using the private
    // cts base to identify which side changed.
    internal static partial class ComparePlanner
    {
        internal sealed class SnapshotStamp
        {
            internal string Guid;
            internal long Timestamp;
        }

        sealed class IdeCacheAttempt
        {
            internal bool Success;
            internal IViewFiles Files;
            internal Dictionary<string, SnapshotStamp> Times;
            internal string State;
            internal double ExportSeconds;
            internal double RenderSeconds;
        }

        sealed class CachedIdeState
        {
            internal IList<SnapshotNodeFields> Fields;
            internal IDictionary<string, IList<string>> GuidFiles;
            internal string Commit;
        }

        sealed class SkeletonChanges
        {
            internal IList<string> Changed;
            internal IList<string> Removed;
            internal ProjectModel OldModel;
            internal ProjectModel CurrentModel;
        }

        internal static IDictionary<string, object> Plan(CliCall call) => BuildPlan(call, false).Payload;

        static ComparePlan BuildPlan(CliCall call, bool importing)
        {
            try { return Run(call, importing); }
            catch (CliFailure) { throw; }
            catch (Exception error) when (error is InvalidOperationException || error is IOException || error is ArgumentException
                || error is UnauthorizedAccessException || error is FormatException || error is InvalidCastException
                || error is KeyNotFoundException || error is NullReferenceException || error is OverflowException)
            {
                throw new CliFailure("compare", "refused", error.Message, "cts compare --help", 1);
            }
        }

        internal static ComparePlan TypedPlan(CliCall call) => BuildPlan(call, true);

        static ComparePlan Run(CliCall call, bool importing)
        {
            var started = Stopwatch.StartNew();
            var folder = call.Options.Params.ContainsKey("sync_folder") ? Convert.ToString(call.Options.Params["sync_folder"]) : call.Hello.SyncFolder;
            if (string.IsNullOrWhiteSpace(folder))
            {
                var status = call.Call("project.status", new Dictionary<string, object>());
                folder = status.ContainsKey("sync_folder") ? Convert.ToString(status["sync_folder"]) : null;
            }
            if (string.IsNullOrWhiteSpace(folder)) throw new CliFailure("compare", "refused", "no sync folder: cts set-sync-folder chooses one (or pass --sync-folder)", "cts set-sync-folder", 1);
            var facts = GitRepository.ReadFacts(folder);
            folder = facts.Root;
            if (!string.IsNullOrWhiteSpace(call.Hello.SyncFolder) && !SameFolder(folder, call.Hello.SyncFolder))
                throw new CliFailure("compare", "refused", "--sync-folder does not match the open project's sync folder", "cts compare --help", 1);
            SyncBase.CheckBase(folder, facts);
            var gitDir = facts.GitDir;
            var contentKeys = new ContentKeyCache(Path.Combine(gitDir, "cts", "content-keys"));
            // The base of another project file's sync is none of this one's:
            // every difference is the open project's against the disk.
            var otherProject = string.IsNullOrWhiteSpace(call.Hello.ProjectPath) ? null : SyncBase.OtherProject(folder, call.Hello.ProjectPath);
            var baseCommit = otherProject == null ? facts.BaseCommit : null;
            var ideStamp = call.Hello.Data.TryGetValue("ide_stamp", out var stamp) ? stamp as string : null;
            var stampPath = Path.Combine(gitDir, "cts", "ide-stamp.json");
            var fullCompare = string.Equals(call.Command.Name, "compare", StringComparison.OrdinalIgnoreCase) && call.Options.Params.ContainsKey("full");
            var unchanged = fullCompare ? false : ExportCommand.StampMatches(call, stampPath, ideStamp, baseCommit);
            var wantsTool = call.Options.Params.ContainsKey("tool");
            var against = call.Options.Params.ContainsKey("against") ? Convert.ToString(call.Options.Params["against"]) : null;
            if (!string.IsNullOrWhiteSpace(against) && !wantsTool) throw new CliFailure("compare", "refused", "--against needs --tool", "cts compare --help", 1);
            var view = ViewFolder.Of(folder);
            var viewRelative = ExportCommand.Relative(folder, view);
            if (wantsTool) CompareTool.ValidateAgainst(folder, against);
            var scratch = Path.Combine(gitDir, "cts", "tmp"); Directory.CreateDirectory(scratch);
            var snapshot = Path.Combine(scratch, "compare-" + Guid.NewGuid().ToString("N") + ".xml");
            var snapshotTimes = new Dictionary<string, SnapshotStamp>(StringComparer.OrdinalIgnoreCase);
            var ideCacheState = "miss";
            var ideCachePath = Path.Combine(gitDir, "cts", "ide-cache.json");
            var useIdeCache = string.Equals(call.Command.Name, "compare", StringComparison.OrdinalIgnoreCase) && !call.Options.Params.ContainsKey("full");
            var ideCache = useIdeCache ? ReadIdeCache(ideCachePath, call.Hello.ProjectPath) : null;
            if (useIdeCache && ideCache != null) unchanged = false;
            GitTreeViewFiles baseFiles = null;
            GitTreeViewFiles cachedIdeFiles = null;
            DiskAgainstBaseViewFiles diskBaseFiles = null;
            var parsedByBlob = new Dictionary<string, StViewResult>(StringComparer.OrdinalIgnoreCase);
            IViewFiles renderedView = null;
            var ideViewReady = false;
            var baseElapsedSeconds = 0d;
            var cacheExportSeconds = 0d;
            var cacheRenderSeconds = 0d;
            var ideElapsed = new Stopwatch();
            var exportElapsed = new Stopwatch();
            var renderElapsed = new Stopwatch();
            try
            {
                if (baseCommit != null) baseFiles = new GitTreeViewFiles(folder, baseCommit, viewRelative);
                if (useIdeCache && ideCache != null)
                {
                    ideElapsed.Start();
                    var attempt = TryIdeCache(call, facts, viewRelative, snapshot, ideCachePath, ideCache);
                    ideElapsed.Stop();
                    if (attempt.Success)
                    {
                        cacheExportSeconds = attempt.ExportSeconds;
                        cacheRenderSeconds = attempt.RenderSeconds;
                        ideCacheState = attempt.State;
                        snapshotTimes = attempt.Times;
                        ideViewReady = true;
                        if (attempt.State == "hit")
                        {
                            cachedIdeFiles = attempt.Files as GitTreeViewFiles;
                            unchanged = true;
                        }
                        else renderedView = attempt.Files;
                    }
                }
                if (!unchanged && !ideViewReady)
                {
                        ideElapsed.Start();
                        exportElapsed.Start();
                        IDictionary<string, object> skeleton = null;
                        if (useIdeCache)
                        {
                            try { skeleton = call.Call("project.skeleton", new Dictionary<string, object>()); }
                            catch (CliFailure failure) when (failure.Declined) { }
                        }
                        call.Call("project.export", new Dictionary<string, object> { { "path", snapshot } });
                        exportElapsed.Stop();
                        renderElapsed.Start();
                        var fullView = new MemoryViewFiles();
                        renderedView = fullView;
                        var exportResult = ViewExport.WriteTo(snapshot, folder, null, fullView);
                        snapshotTimes = SnapshotTimes(exportResult.Model);
                        if (useIdeCache && skeleton != null && skeleton.TryGetValue("nodes", out var rawSkeleton) && rawSkeleton is IList<object> skeletonNodes)
                        {
                            var commit = CompareTool.Store(folder, viewRelative, renderedView, facts, null);
                            var fields = ReadSkeleton(skeletonNodes);
                            WriteIdeCache(ideCachePath, call.Hello.ProjectPath, commit, exportResult.GuidFiles, fields, SnapshotTimes(fields, exportResult.Model));
                        }
                        renderElapsed.Stop();
                        ideElapsed.Stop();
                        ideViewReady = true;
                }
                if (otherProject != null)
                {
                    call.Options.Params["compare_info"] = new List<string>
                    {
                        "The last sync of this folder was with " + otherProject + ", not with the open project, so there is no common base: "
                        + "cts export writes the open project to disk (files with uncommitted changes stay), cts import gives the project the disk's text.",
                    };
                }
                if (wantsTool)
                {
                    // The tool sees the disk's file where Git's ignore rules leave an object to the owner.
                    var toolView = unchanged ? (IViewFiles)(cachedIdeFiles ?? (IViewFiles)baseFiles) : renderedView;
                    var onDisk = new DirectoryViewFiles(view);
                    var toolIgnored = ViewIgnore.Match(folder, viewRelative, toolView.Paths.Concat(onDisk.Paths));
                    if (toolIgnored.Count > 0) toolView = new IgnoredViewFiles(toolView, toolIgnored, onDisk);
                    var toolData = CompareTool.Open(folder, viewRelative, toolView, against, facts);
                    toolData["sync_folder"] = folder;
                    toolData["timings"] = new Dictionary<string, object>
                    {
                        { "total_s", Math.Round(started.Elapsed.TotalSeconds, 3) },
                        { "base_s", Math.Round(baseElapsedSeconds + (baseFiles?.ElapsedSeconds ?? 0), 3) },
                        { "ide_s", Math.Round(ideElapsed.Elapsed.TotalSeconds, 3) },
                        { "ide_cache", ideCacheState },
                        { "export_s", Math.Round(exportElapsed.Elapsed.TotalSeconds + cacheExportSeconds, 3) },
                        { "render_s", Math.Round(renderElapsed.Elapsed.TotalSeconds + cacheRenderSeconds, 3) },
                        { "disk_s", 0d },
                        { "compare_s", 0d },
                    };
                    if (call.Options.Params.TryGetValue("compare_info", out var toolInfo)) toolData["info"] = toolInfo;
                    return new ComparePlan { Payload = toolData, Records = new List<CompareRecord>() };
                }
                var ideTimedFiles = unchanged ? null : new TimedViewFiles(renderedView);
                IViewFiles ideFiles = unchanged ? (IViewFiles)(cachedIdeFiles ?? baseFiles) : ideTimedFiles;
                IViewFiles baseView = baseFiles;
                if (baseCommit != null)
                {
                    try { diskBaseFiles = new DiskAgainstBaseViewFiles(folder, viewRelative, baseFiles, Path.Combine(gitDir, "cts", "disk-index")); }
                    catch (Exception error) when (error is InvalidOperationException || error is IOException || error is UnauthorizedAccessException || error is ArgumentException)
                    {
                    }
                }
                var diskSource = diskBaseFiles ?? (IViewFiles)new DirectoryViewFiles(view);
                // What Git's ignore rules leave to the project's owner is no difference (ViewIgnore).
                var everyPath = diskSource.Paths.Concat(ideFiles.Paths).Concat(baseFiles == null ? Enumerable.Empty<string>() : baseFiles.Paths).ToList();
                var ignored = ViewIgnore.Match(folder, viewRelative, everyPath);
                var ignoredStale = new List<string>();
                if (ignored.Count > 0) ViewIgnore.Refuse(ignored, everyPath, path => ideFiles.Read(path) ?? diskSource.Read(path) ?? baseFiles?.Read(path));
                ignored.ExceptWith(IncludedIgnored(call, view, ignored));
                if (ignored.Count > 0)
                {
                    var onBothSides = new HashSet<string>(diskSource.Paths.Where(ignored.Contains), StringComparer.OrdinalIgnoreCase);
                    onBothSides.IntersectWith(ideFiles.Paths);
                    ignoredStale = onBothSides.Where(path => !SameViewContent(path, diskSource, ideFiles, contentKeys)).OrderBy(path => path, StringComparer.OrdinalIgnoreCase).ToList();
                    diskSource = new IgnoredViewFiles(diskSource, ignored);
                    ideFiles = new IgnoredViewFiles(ideFiles, ignored);
                    if (baseFiles != null) baseView = new IgnoredViewFiles(baseFiles, ignored);
                }
                var diskFiles = new TimedViewFiles(diskSource);
                var diskPaths = diskFiles.Paths.ToList();
                var idePaths = ideFiles.Paths.ToList();
                var basePaths = baseView == null ? new List<string>() : baseView.Paths.ToList();
                var diskPathSet = new HashSet<string>(diskPaths, StringComparer.OrdinalIgnoreCase);
                var idePathSet = new HashSet<string>(idePaths, StringComparer.OrdinalIgnoreCase);
                var basePathSet = new HashSet<string>(basePaths, StringComparer.OrdinalIgnoreCase);
                var paths = diskPaths.Union(idePaths).Union(basePaths).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(p => p, StringComparer.OrdinalIgnoreCase).ToList();
                var records = new List<CompareRecord>();
                var counts = new Dictionary<string, int> { { "unchanged", 0 }, { "modified", 0 }, { "added", 0 }, { "deleted", 0 }, { "not_importable", 0 } };
                var baseSt = baseView == null ? new StViewResult() : StViewReader.Read(baseView, parsedByBlob);
                var diskSt = StViewReader.Read(diskFiles, parsedByBlob);
                var ideSt = StViewReader.Read(ideFiles, parsedByBlob);
                var sameTripleSt = baseView == null ? new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                    : new HashSet<string>(basePaths.Intersect(diskFiles.Paths, StringComparer.OrdinalIgnoreCase).Intersect(ideFiles.Paths, StringComparer.OrdinalIgnoreCase)
                        .Where(path => baseSt.BlobIds.TryGetValue(path, out var baseBlob) && diskSt.BlobIds.TryGetValue(path, out var diskBlob)
                            && ideSt.BlobIds.TryGetValue(path, out var ideBlob) && string.Equals(baseBlob, diskBlob, StringComparison.Ordinal)
                            && string.Equals(baseBlob, ideBlob, StringComparison.Ordinal)), StringComparer.OrdinalIgnoreCase);
                var sameSt = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                var compareElapsed = Stopwatch.StartNew();
                var ownerKept = new List<string>();
                foreach (var path in paths)
                {
                    if (path.EndsWith(".st", StringComparison.OrdinalIgnoreCase))
                    {
                        var sameBlob = diskSt.BlobIds.TryGetValue(path, out var diskBlob) && ideSt.BlobIds.TryGetValue(path, out var ideBlob)
                            && string.Equals(diskBlob, ideBlob, StringComparison.Ordinal);
                        if (sameBlob || SameViewContent(path, diskFiles, ideFiles, contentKeys))
                        {
                            sameSt.Add(path);
                            continue;
                        }
                        continue;
                    }
                    if (SameViewContent(path, diskFiles, ideFiles, contentKeys))
                    {
                        counts["unchanged"]++;
                        if (call.Options.Params.ContainsKey("all"))
                        {
                            records.Add(new CompareRecord { Name = ContainerName(path), Path = path, Category = "unchanged" });
                        }
                        continue;
                    }
                    var diskExists = diskPathSet.Contains(path);
                    var ideExists = idePathSet.Contains(path);
                    // A folder is on disk while its directory is; the export writes its
                    // container file.  A device or an application only the IDE has (a new
                    // one, whose objects reached disk) still needs its own: it holds its settings.
                    if (!diskExists && IsContainer(path) && (!ideExists || basePathSet.Contains(path) || PlainFolder(ideFiles.Read(path)))
                        && Directory.Exists(Path.Combine(view, Path.GetDirectoryName(path.Replace('/', Path.DirectorySeparatorChar)))))
                    {
                        counts["unchanged"]++;
                        if (call.Options.Params.ContainsKey("all"))
                        {
                            records.Add(new CompareRecord { Name = ContainerName(path), Path = path, Category = "unchanged" });
                        }
                        continue;
                    }
                    if (!diskExists && !ideExists)
                    {
                        counts["unchanged"]++;
                        if (call.Options.Params.ContainsKey("all"))
                        {
                            records.Add(new CompareRecord { Name = ContainerName(path), Path = path, Category = "unchanged" });
                        }
                        continue;
                    }
                    var hasBase = basePathSet.Contains(path);
                    var ideBaseSame = hasBase && SameViewContent(path, ideFiles, baseView, contentKeys);
                    var diskBaseSame = hasBase && SameViewContent(path, diskFiles, baseView, contentKeys);
                    if (hasBase && !ideBaseSame && ideExists && ProjectInfo.OwnerKeeps(folder, ideFiles.Read(path)))
                    {
                        ownerKept.Add(path);
                        ideBaseSame = true;
                        if (diskBaseSame)
                        {
                            counts["unchanged"]++;
                            if (call.Options.Params.ContainsKey("all"))
                            {
                                records.Add(new CompareRecord { Name = ContainerName(path), Path = path, Category = "unchanged" });
                            }
                            continue;
                        }
                    }
                    string category;
                    if (!hasBase) category = !diskExists ? "ide_changed" : !ideExists ? "added" : "modified";
                    else if (ideBaseSame) category = !diskExists ? "deleted" : "modified";
                    else if (diskBaseSame) category = "ide_changed";
                    else category = "modified";
                    var both = category == "modified" && hasBase && !diskBaseSame && !ideBaseSame;
                    if (both) { counts["both"] = counts.ContainsKey("both") ? counts["both"] + 1 : 1; }
                    if (!counts.ContainsKey(category)) counts[category] = 0;
                    counts[category]++;
                    var record = new CompareRecord { Name = ContainerName(path), Path = path, Category = category };
                    if (category == "ide_changed") record.Reason = !ideExists ? "deleted in the IDE; cts sync removes the file" : !hasBase ? "not in the view; cts sync writes it to disk" : "changed in the IDE; cts sync writes it to disk";
                    record.IdeChanged = both;
                    // Both sides' edits of an object kept as XML join when they
                    // touch different elements; the import carries the merge.
                    var merged = both && diskExists && ideExists ? XmlMerge.Merge(baseView.Read(path), diskFiles.Read(path), ideFiles.Read(path), out _) : null;
                    if (merged != null)
                    {
                        record.Merges = true;
                        if (importing) record.MergedXml = merged;
                    }
                    if (snapshotTimes.TryGetValue(path, out var snapshotStamp)) { record.Guid = snapshotStamp.Guid; record.HasGuid = true; record.Timestamp = snapshotStamp.Timestamp; }
                    records.Add(record);
                }
                CompareSt(diskSt, baseSt, ideSt, sameSt, sameTripleSt, records, counts, call.Options.Params.ContainsKey("all"), snapshotTimes);
                compareElapsed.Stop();
                var objects = new Dictionary<string, object>
                {
                    { "modified", new List<IDictionary<string, object>>() }, { "added", new List<IDictionary<string, object>>() }, { "deleted", new List<IDictionary<string, object>>() },
                };
                foreach (var group in records.GroupBy(r => r.Category)) objects[group.Key] = group.Select(r => r.Answer()).ToList();
                var summary = counts.ToDictionary(pair => pair.Key, pair => (object)pair.Value);
                var data = new Dictionary<string, object> { { "summary", summary }, { "objects", objects }, { "base", baseCommit != null }, { "ide", ideCacheState == "hit" ? "cached" : unchanged ? "unchanged" : "exported" }, { "sync_folder", folder } };
                if (otherProject != null) data["base_project"] = otherProject;
                var importIdeFiles = call.Options.Params.ContainsKey("force") || importing
                    ? ideFiles.Paths.ToDictionary(path => path, path => ideFiles.Read(path), StringComparer.OrdinalIgnoreCase) : null;
                var info = call.Options.Params.TryGetValue("compare_info", out var compareInfo) ? ((IEnumerable<string>)compareInfo).ToList() : new List<string>();
                if (ownerKept.Count > 0) info.Add(OwnerKeptNote(ownerKept));
                if (ignored.Count > 0) info.Add(ViewIgnore.Note(ignored.Count));
                if (ignoredStale.Count > 0) info.Add(ViewIgnore.StaleNote(ignoredStale));
                if (info.Count > 0) data["info"] = info;
                var diskTimes = records.Where(r => r.Category == "modified" || r.Category == "added" || r.Category == "not_importable").Select(r => Path.Combine(view, r.Path.Replace('/', Path.DirectorySeparatorChar))).Where(File.Exists).Select(p => File.GetLastWriteTime(p)).ToList();
                var lastEdit = new Dictionary<string, object>();
                if (diskTimes.Count > 0) lastEdit["disk"] = diskTimes.Max().ToString("yyyy-MM-ddTHH:mm:ss", System.Globalization.CultureInfo.InvariantCulture);
                var ideTimes = records.Where(r => r.Category == "ide_changed" || r.IdeChanged).Where(r => r.Timestamp.HasValue).Select(r => r.Timestamp.Value).Where(t => t > 0).ToList();
                if (ideTimes.Count > 0)
                {
                    var date = new DateTime(ideTimes.Max(), DateTimeKind.Unspecified);
                    lastEdit["ide"] = date.ToString("yyyy-MM-ddTHH:mm:ss", System.Globalization.CultureInfo.InvariantCulture);
                }
                if (lastEdit.Count > 0) data["last_edit"] = lastEdit;
                data["view"] = viewRelative;
                data["timings"] = new Dictionary<string, object>
                {
                    { "ide_cache", ideCacheState },
                    { "total_s", Math.Round(started.Elapsed.TotalSeconds, 3) },
                    { "base_s", Math.Round(baseElapsedSeconds + (baseFiles?.ElapsedSeconds ?? 0), 3) },
                    { "ide_s", Math.Round(ideElapsed.Elapsed.TotalSeconds + (ideTimedFiles?.ElapsedSeconds ?? 0), 3) },
                    { "export_s", Math.Round(exportElapsed.Elapsed.TotalSeconds + cacheExportSeconds, 3) },
                    { "render_s", Math.Round(renderElapsed.Elapsed.TotalSeconds + cacheRenderSeconds + (ideTimedFiles?.ElapsedSeconds ?? 0), 3) },
                    { "disk_s", Math.Round(diskFiles.ElapsedSeconds, 3) },
                    { "compare_s", Math.Round(compareElapsed.Elapsed.TotalSeconds, 3) },
                };
                return new ComparePlan
                {
                    Payload = data,
                    Summary = summary,
                    IdeFiles = importIdeFiles,
                    IdeObjects = call.Options.Params.ContainsKey("force") || importing ? ideSt.Objects : null,
                    BaseObjects = importing ? baseSt.Objects : null,
                    Records = new[] { "modified", "added", "deleted", "not_importable", "ide_changed" }
                        .SelectMany(category => records.Where(record => record.Category == category)).ToList(),
                };
            }
            finally { contentKeys.Save(); baseFiles?.Dispose(); cachedIdeFiles?.Dispose(); (renderedView as IDisposable)?.Dispose(); if (File.Exists(snapshot)) File.Delete(snapshot); }
        }

        // Match objects by IDE path across files: imports may place a member in its own file while export puts it with its owner.
        internal static void CompareSt(StViewResult disk, StViewResult baseline, StViewResult ide, ICollection<string> sameFiles, ISet<string> sameTripleFiles,
            IList<CompareRecord> records, IDictionary<string, int> counts, bool all,
            IDictionary<string, SnapshotStamp> snapshotTimes)
        {
            var errors = disk.Errors.Concat(baseline.Errors).Concat(ide.Errors).Where(error => !sameFiles.Contains(error.File) && !sameTripleFiles.Contains(error.File)).ToList();
            var broken = new HashSet<string>(errors.Select(error => error.File), StringComparer.OrdinalIgnoreCase);
            foreach (var error in errors.GroupBy(error => error.File + "\n" + error.Reason, StringComparer.OrdinalIgnoreCase).Select(group => group.First()))
                AddRecord(records, counts, "not_importable", Path.GetFileNameWithoutExtension(error.File), error.File, null, error.Reason);
            var d = ByKey(disk); var b = ByKey(baseline); var i = ByKey(ide);
            var keys = d.Keys.Union(i.Keys, StringComparer.OrdinalIgnoreCase).Union(b.Keys, StringComparer.OrdinalIgnoreCase)
                .Select(key => new { Key = key, File = (d.TryGetValue(key, out var x) ? x : i.TryGetValue(key, out var y) ? y : b[key]).File })
                .OrderBy(item => item.File, StringComparer.OrdinalIgnoreCase).ThenBy(item => item.Key, StringComparer.OrdinalIgnoreCase);
            foreach (var entry in keys)
            {
                d.TryGetValue(entry.Key, out var diskObject); b.TryGetValue(entry.Key, out var baseObject); i.TryGetValue(entry.Key, out var ideObject);
                if (diskObject == null && ideObject == null) continue;
                if (new[] { diskObject, baseObject, ideObject }.Any(item => item != null && broken.Contains(item.File))) continue;
                var name = (diskObject ?? ideObject ?? baseObject).Path.LastOrDefault() ?? Path.GetFileNameWithoutExtension(entry.File);
                if (sameTripleFiles.Contains(entry.File))
                {
                    if (all)
                    {
                        AddRecord(records, counts, "unchanged", name, entry.File, diskObject, null, snapshotTimes: snapshotTimes);
                    }
                    else
                    {
                        counts["unchanged"]++;
                    }
                    continue;
                }
                var diskIdeParts = StViewObject.DifferentParts(diskObject, ideObject);
                if (diskObject != null && ideObject != null && diskIdeParts.Count == 0) { if (all) AddRecord(records, counts, "unchanged", name, entry.File, diskObject, null, snapshotTimes: snapshotTimes); else counts["unchanged"]++; continue; }
                if (baseObject == null) { if (diskObject == null) AddRecord(records, counts, "ide_changed", name, entry.File, ideObject, "not in the view; cts sync writes it to disk", snapshotTimes: snapshotTimes); else if (ideObject == null) AddRecord(records, counts, "added", name, entry.File, diskObject, null); else AddRecord(records, counts, "modified", name, entry.File, diskObject, null, diskIdeParts, snapshotTimes: snapshotTimes); continue; }
                var diskBaseParts = StViewObject.DifferentParts(diskObject, baseObject); var ideBaseParts = StViewObject.DifferentParts(ideObject, baseObject);
                if (diskObject != null && !string.Equals(diskObject.Kind, baseObject.Kind, StringComparison.OrdinalIgnoreCase) && diskBaseParts.Count > 0) { AddRecord(records, counts, "not_importable", name, entry.File, diskObject, "object kind changed from " + baseObject.Kind + " to " + diskObject.Kind, diskBaseParts); continue; }
                if (diskObject != null && ideObject == null && diskBaseParts.Count > 0) { AddRecord(records, counts, "not_importable", name, entry.File, diskObject, "changed on disk, not in the IDE", diskBaseParts); continue; }
                var diskChanged = diskBaseParts.Count > 0; var ideChanged = ideBaseParts.Count > 0;
                if (!diskChanged && !ideChanged) { if (all) AddRecord(records, counts, "unchanged", name, entry.File, diskObject, null, snapshotTimes: snapshotTimes); else counts["unchanged"]++; continue; }
                if (diskChanged && !ideChanged) { if (diskObject == null) AddRecord(records, counts, "deleted", name, entry.File, baseObject, null); else AddRecord(records, counts, "modified", name, entry.File, diskObject, null, diskBaseParts, snapshotTimes: snapshotTimes); }
                else if (!diskChanged && ideChanged) AddRecord(records, counts, "ide_changed", name, entry.File, ideObject ?? baseObject, ideObject == null ? "deleted in the IDE; cts sync removes the file" : "changed in the IDE; cts sync writes it to disk", ideBaseParts, snapshotTimes: snapshotTimes);
                else AddRecord(records, counts, "modified", name, entry.File, diskObject ?? ideObject, null, diskIdeParts, true, snapshotTimes);
            }
        }
        // The files `import --include-ignored` names, view-relative: each must be one Git's ignore rules match.
        static IEnumerable<string> IncludedIgnored(CliCall call, string view, ISet<string> ignored)
        {
            if (!call.Options.Params.TryGetValue("include_ignored", out var named)) return Enumerable.Empty<string>();
            var included = new List<string>();
            foreach (var path in ((IEnumerable<object>)named).Select(Convert.ToString))
            {
                var relative = ExportCommand.Relative(view, Path.GetFullPath(path));
                if (!ignored.Contains(relative))
                    throw new CliFailure(call.Command.Name, "refused", path + " is not a file of the view that Git's ignore rules match"
                        + (relative.StartsWith("../", StringComparison.Ordinal) ? " (it is outside " + view + ")" : "; cts import carries it without --include-ignored"), "cts compare", 1);
                included.Add(relative);
            }
            return included;
        }

        static Dictionary<string, StViewObject> ByKey(StViewResult result) => result.Objects.GroupBy(item => item.Key, StringComparer.OrdinalIgnoreCase).ToDictionary(group => group.Key, group => group.First(), StringComparer.OrdinalIgnoreCase);
        static bool PlainFolder(byte[] content)
        {
            var type = content == null ? null : Regex.Match(System.Text.Encoding.UTF8.GetString(content), "Name=\"TypeGuid\"[^>]*>([^<]*)<");
            return type == null || (type.Success && type.Groups[1].Value.Trim().Trim('{', '}').Equals(ObjectKinds.FolderType, StringComparison.OrdinalIgnoreCase));
        }

        static bool IsContainer(string path) => Path.GetFileName(path).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase) && path.Contains("/");
        static string ContainerName(string path) => Path.GetFileName(path).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase) ? Path.GetFileName(Path.GetDirectoryName(path)) : Path.GetFileNameWithoutExtension(path);
        static void AddRecord(IList<CompareRecord> records, IDictionary<string, int> counts, string category, string name, string file, StViewObject item, string reason, IList<string> parts = null, bool both = false, IDictionary<string, SnapshotStamp> snapshotTimes = null)
        {
            counts[category] = counts.ContainsKey(category) ? counts[category] + 1 : 1;
            if (both) counts["both"] = counts.ContainsKey("both") ? counts["both"] + 1 : 1;
            var record = new CompareRecord { Name = name, Path = file, Category = category, Reason = reason, Parts = parts, IdeChanged = both, ObjectPath = item?.Key, Kind = item?.Kind };
            if (item != null && snapshotTimes != null && snapshotTimes.TryGetValue(item.Key, out var stamp))
            {
                record.Guid = stamp.Guid;
                record.HasGuid = true;
                record.Timestamp = stamp.Timestamp;
            }
            records.Add(record);
        }
    }
}
