using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // Plans import decisions without applying IDE or disk writes.
        sealed partial class ImportPlanner
        {
            readonly CliCall _call;
            readonly ImportWork _work;
            readonly IList<StViewObject> _baseObjects;
            string _take;
            bool _tool;
            HashSet<string> _addedKeys;
            List<string> _folderCreateKeys;

            internal ImportPlanner(CliCall call, bool syncing, bool settling, ComparePlan plan)
            {
                _call = call;
                _baseObjects = plan.BaseObjects;
                _work = new ImportWork
                {
                    Syncing = syncing || settling,
                    Settling = settling,
                    Data = plan.Payload,
                    IdeFiles = plan.IdeFiles,
                    IdeObjects = plan.IdeObjects,
                    Changed = plan.Records.Where(record => !settling
                        || record.Category == "modified" && record.IdeChanged
                            && (record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase) || record.MergedXml != null)).ToList()
                };
            }

            internal IDictionary<string, object> Plan(out ImportWork work)
            {
                work = _work;
                // Everything in this method only reads; dry runs meet the refusals, merges and conflicts the import would.
                var stop = Check();
                if (stop != null) return stop;
                Collect();
                return PlanTextLists() ?? PlanNatives() ?? PlanAdded() ?? PlanIdeNew() ?? PlanModified() ?? PlanIdeEdits() ?? PlanForced()
                    ?? ReadNativeMeta();
            }

            internal IDictionary<string, object> DryRunAnswer()
            {
                if (_work.Merged.Count > 0) _work.Data["merges"] = _work.Merged;
                if (_work.Conflicts.Count > 0) { _work.Data["conflicts"] = _work.Conflicts; _work.Data["conflict_next"] = ConflictNext; }
                MatchRenames();
                if (_work.Renames.Count > 0) _work.Data["renames"] = _work.Renames.Select(rename => (object)new Dictionary<string, object>
                    { { "from", rename.DeletedRecord.Path }, { "to", rename.Item.File } }).ToList();
                return _work.Data;
            }

            // Refusals that need nothing but the plan: another project's base, no base for a merge, no merge tool.
            IDictionary<string, object> Check()
            {
                _work.OtherProject = SyncBase.OtherProject(Convert.ToString(_work.Data["sync_folder"]), _call.Hello.ProjectPath);
                if (_work.Syncing && _work.OtherProject != null)
                    return Refused(_call, _work.Data, "the last sync of this folder was with " + _work.OtherProject + ", so a merge has no common base with the open project: "
                        + "cts compare shows how they differ; cts import gives the project the disk's text, cts export gives the disk the project's");
                var refusal = Refusal(_call, _work.Data, _work.Changed);
                if (refusal != null) return Refused(_call, _work.Data, refusal);
                _work.HasBase = Equals(_work.Data.ContainsKey("base") ? _work.Data["base"] : null, true);
                if (_work.Syncing && !_work.HasBase) return Refused(_call, _work.Data, "no sync base yet: run cts export first");
                // sync --take: the side a conflict takes; the rest syncs as without it.
                _take = _work.Syncing && _call.Options.Params.ContainsKey("take") ? Convert.ToString(_call.Options.Params["take"]) : null;
                _tool = _call.Options.Params.ContainsKey("conflict_tool") && !_call.Options.Params.ContainsKey("dry_run");
                return null;
            }

            // The records by kind, the disk's parsed text and the IDE's tree; a new native object's
            // missing folders become folder records.
            void Collect()
            {
                _work.Folder = Convert.ToString(_work.Data["sync_folder"]);
                _work.View = ViewFolder.Of(_work.Folder);
                var force = _work.HasBase && _call.Options.Params.ContainsKey("force");
                _work.ForceRecords = force ? _work.Changed.Where(record => !IsFolderRecord(record) && (record.Category == "ide_changed"
                    || record.IdeChanged)).ToList() : new List<CompareRecord>();
                // --force: a folder the IDE deleted (or renamed) is made again; one only the IDE
                // has goes once the forced deletes emptied it.
                if (force)
                    foreach (var record in _work.Changed.Where(record => IsFolderRecord(record) && ComparePlanner.IdeDeleted(record)))
                        record.Category = "added";
                _work.Parsed = StViewReader.Read(_work.View);
                _work.StRecords = _work.Changed.Where(record => record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)).ToList();
                _work.FolderRecords = _work.Changed.Where(IsFolderRecord).ToList();
                _work.Deleted = _work.StRecords.Where(record => record.Category == "deleted").OrderByDescending(record => RecordDepth(record, _work.Parsed)).ToList();
                var tree = _call.Call("project.tree", new Dictionary<string, object>());
                _work.IdeNodes = TreeObjects(tree);
                _work.IdeByPath = _work.IdeNodes.ToDictionary(pair => pair.Key, pair => pair.Value.Guid, StringComparer.OrdinalIgnoreCase);
                _work.NativeRecords = _work.Changed.Where(record => !IsFolderRecord(record)
                    && !record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)
                    && record.Path.EndsWith(".xml", StringComparison.OrdinalIgnoreCase)).ToList();
                _work.CsvRecords = _work.Changed.Where(record => record.Path.EndsWith(".csv", StringComparison.OrdinalIgnoreCase)).ToList();
                foreach (var record in _work.NativeRecords.Where(record => record.Category == "added"))
                {
                    var directory = ParentKey(Path.ChangeExtension(record.Path, null).Replace('\\', '/'));
                    var segments = directory.Split('/');
                    for (var depth = 1; depth <= segments.Length; depth++)
                    {
                        var key = string.Join("/", segments.Take(depth));
                        if (!_work.IdeByPath.ContainsKey(key) && !_work.FolderRecords.Any(container =>
                            string.Equals(FolderKey(container.Path), key, StringComparison.OrdinalIgnoreCase)))
                            _work.FolderRecords.Add(new CompareRecord { Category = "added", Path = key + "/.cds-object.xml", Name = segments[depth - 1] });
                    }
                }
            }

            // Deleted text objects get their guids; new ones their kinds and parents, with the folders they need.
            IDictionary<string, object> PlanAdded()
            {
                foreach (var record in _work.Deleted)
                    if (!record.HasGuid)
                    {
                        var key = Path.Combine(Path.GetDirectoryName(record.Path) ?? "", record.Name)
                            .Replace(Path.DirectorySeparatorChar, '/');
                        if (_work.IdeByPath.TryGetValue(key, out var deletedGuid)) { record.Guid = deletedGuid; record.HasGuid = true; }
                    }
                foreach (var record in _work.Deleted)
                    if (string.IsNullOrEmpty(record.Guid)) return Refused(_call, _work.Data, "cannot identify IDE object to delete: " + record.Name);
                _work.AddedItems = _work.StRecords.Where(record => record.Category == "added")
                    .Select(record => new AddedText { Record = record, Item = FindViewObject(_work.Parsed, record) })
                    .Where(pair => pair.Item == null || pair.Item.Kind != "GET" && pair.Item.Kind != "SET")
                    .OrderBy(pair => pair.Item?.Path.Length ?? int.MaxValue).ToList();
                if (_work.AddedItems.Any(pair => pair.Item == null)) return Refused(_call, _work.Data, "cannot parse a new .st object");
                _work.Created = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                _work.CreatedAccessorNames = new List<string>();
                _work.Writes = new List<TextWrite>();
                _work.Updated = new List<string>();
                _work.ForcedDeletes = new List<string>();
                _work.ForcedDeletedNames = new List<string>();
                _work.CreatedFolders = new List<string>();
                _work.ForcedCreateItems = new List<StViewObject>();
                _work.ForcedCreated = new List<string>();
                // New directories need no marker file: infer their missing ancestors from added objects;
                // an ancestor this import creates as an object (a new POU's method) is no folder.
                _addedKeys = new HashSet<string>(_work.AddedItems.Select(pair => pair.Item.Key), StringComparer.OrdinalIgnoreCase);
                foreach (var pair in _work.AddedItems)
                {
                    var item = pair.Item;
                    for (var depth = 1; depth < item.Path.Length; depth++)
                    {
                        var key = string.Join("/", item.Path.Take(depth));
                        if (!_work.IdeByPath.ContainsKey(key) && !_addedKeys.Contains(key) && !_work.FolderRecords.Any(record => string.Equals(FolderKey(record.Path), key, StringComparison.OrdinalIgnoreCase))
                            && !_work.FolderRecords.Any(record => record.Category == "added" && string.Equals(FolderKey(record.Path), key, StringComparison.OrdinalIgnoreCase)))
                    _work.FolderRecords.Add(new CompareRecord { Category = "added", Path = key + "/.cds-object.xml", Name = Path.GetFileName(key) });
                    }
                }
                _folderCreateKeys = _work.FolderRecords.Where(record => record.Category == "added").Select(record => FolderKey(record.Path)).ToList();
                // Complete every refusal check before the first agent mutation.
                foreach (var key in _folderCreateKeys.OrderBy(key => key.Count(ch => ch == '/')))
                {
                    var parent = ParentKey(key);
                    if (parent.Length > 0 && !_work.IdeByPath.ContainsKey(parent) && !_folderCreateKeys.Contains(parent, StringComparer.OrdinalIgnoreCase))
                        return Refused(_call, _work.Data, "no IDE parent for new folder " + key);
                }
                foreach (var pair in _work.AddedItems)
                {
                    var item = pair.Item;
                    if (CreateKind(pair.Record.Kind ?? item.Kind) == null) return Refused(_call, _work.Data, "cannot create object kind " + item.Kind + " for " + pair.Record.Name);
                    var parent = string.Join("/", item.Path.Take(item.Path.Length - 1));
                    if (parent.Length > 0 && !_work.IdeByPath.ContainsKey(parent) && !_addedKeys.Contains(parent) && !_folderCreateKeys.Contains(parent, StringComparer.OrdinalIgnoreCase))
                        return Refused(_call, _work.Data, "no IDE parent for new object " + item.Key);
                }
                return null;
            }

            // Text objects new in the IDE, which sync writes to disk.
            IDictionary<string, object> PlanIdeNew()
            {
                _work.Conflicts = new List<IDictionary<string, object>>();
                _work.MergeFiles = new List<MergeFileEdit>();
                _work.IdeToDisk = new List<MergeFileEdit>();
                _work.IdeNewTextFiles = new List<string>();
                _work.IdeNewTextObjects = new List<StViewObject>();
                if (_work.Syncing)
                {
                    var diskPaths = new HashSet<string>(_work.Parsed.Objects.Select(item => item.Key), StringComparer.OrdinalIgnoreCase);
                    var basePaths = new HashSet<string>((_baseObjects ?? new List<StViewObject>()).Select(item => item.Key), StringComparer.OrdinalIgnoreCase);
                    foreach (var item in (_work.IdeObjects ?? new List<StViewObject>()).Where(item => !diskPaths.Contains(item.Key)
                        && !basePaths.Contains(item.Key)))
                    {
                        if (_work.IdeFiles == null || !_work.IdeFiles.ContainsKey(item.File))
                            return Refused(_call, _work.Data, "cannot find exported IDE text for " + item.Key);
                        if (!IsStMember(item.Kind) && File.Exists(Path.Combine(_work.View, item.File.Replace('/', Path.DirectorySeparatorChar))))
                            return Refused(_call, _work.Data, item.Key + " is new in the IDE and its file " + item.File + " holds something else on disk; rename one of them");
                        if (!_work.IdeNewTextFiles.Contains(item.File, StringComparer.OrdinalIgnoreCase)) _work.IdeNewTextFiles.Add(item.File);
                        _work.IdeNewTextObjects.Add(item);
                    }
                }
                return null;
            }

            // Each modified text object: written as the disk has it, or merged with the IDE's edit, or a conflict.
            IDictionary<string, object> PlanModified()
            {
                foreach (var record in _work.StRecords.Where(record => record.Category == "modified"))
                {
                    var item = FindViewObject(_work.Parsed, record);
                    if (item == null && _call.Options.Params.ContainsKey("force") && record.IdeChanged)
                    {
                        var pathKey = record.ObjectPath;
                        var deletedGuid = record.Guid;
                        if (string.IsNullOrEmpty(deletedGuid) && pathKey != null) _work.IdeByPath.TryGetValue(pathKey, out deletedGuid);
                        if (string.IsNullOrEmpty(deletedGuid)) return Refused(_call, _work.Data, "cannot identify IDE object to delete: " + record.Name);
                        _work.ForcedDeletes.Add(deletedGuid); _work.ForcedDeletedNames.Add(record.Name);
                        continue;
                    }
                    if (item == null) return Refused(_call, _work.Data, "cannot identify disk text for " + record.Name);
                    var guid = record.Guid;
                    if (string.IsNullOrEmpty(guid) && !_work.IdeByPath.TryGetValue(item.Key, out guid))
                        return Refused(_call, _work.Data, "cannot identify IDE object for " + record.Name);
                    if (record.IdeChanged && !_call.Options.Params.ContainsKey("force"))
                    {
                        var originalItem = item;
                        var key = item.Key;
                        var ideItem = At(_work.IdeObjects, key);
                        var baseItem = At(_baseObjects, key);
                        if (ideItem == null || baseItem == null) return Refused(_call, _work.Data, "cannot identify merge text for " + record.Name);
                        var mergedItem = MergeObject(item, baseItem, ideItem);
                        if (mergedItem == null && _tool && _take == null) mergedItem = SideBySide(item, ideItem);
                        if (mergedItem == null && _take == "ide")
                        {
                            _work.IdeToDisk.Add(new MergeFileEdit { Guid = guid, Original = item, Merged = ideItem });
                            continue;
                        }
                        if (mergedItem == null && _take != "disk")
                        {
                            _work.Conflicts.Add(new Dictionary<string, object> { { "name", record.Name }, { "path", record.Path } });
                            continue;
                        }
                        if (mergedItem == null)
                        {
                            // The disk's text goes in; the IDE's is kept on refs/cts/overwritten first.
                            _work.ForceRecords.Add(record);
                        }
                        else
                        {
                            item = mergedItem;
                            _work.MergeFiles.Add(new MergeFileEdit { Guid = guid, Original = originalItem, Merged = mergedItem });
                            _work.Merged.Add(record.Name);
                        }
                    }
                    _work.Writes.Add(new TextWrite { Guid = guid, Item = item });
                    _work.Updated.Add(record.Name);
                }
                return null;
            }

            // Edits only the IDE made, which sync writes into their files.
            IDictionary<string, object> PlanIdeEdits()
            {
                if (_work.Syncing && !_call.Options.Params.ContainsKey("force"))
                    foreach (var record in _work.StRecords.Where(record => record.Category == "ide_changed" && !ComparePlanner.IdeDeleted(record)))
                    {
                        var key = record.ObjectPath;
                        var diskItem = At(_work.Parsed.Objects, key);
                        var ideItem = At(_work.IdeObjects, key);
                        var baseItem = At(_baseObjects, key);
                        if (diskItem == null && baseItem == null && ideItem != null) continue;
                        if (diskItem == null || ideItem == null) return Refused(_call, _work.Data, "cannot identify IDE text to write for " + record.Name);
                        _work.IdeToDisk.Add(new MergeFileEdit { Guid = record.Guid, Original = diskItem, Merged = ideItem });
                    }
                return null;
            }

            // --force: the disk's text goes back over the IDE's edits; objects the IDE lacks are recreated.
            IDictionary<string, object> PlanForced()
            {
                foreach (var record in _work.ForceRecords.Where(record => record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase)
                    && record.Category != "modified"))
                {
                    var objectPath = record.ObjectPath;
                    var ideObject = _work.IdeObjects?.FirstOrDefault(item => objectPath != null
                        ? string.Equals(item.Key, objectPath, StringComparison.OrdinalIgnoreCase)
                        : item.File.Equals(record.Path, StringComparison.OrdinalIgnoreCase)
                            && string.Equals(item.Path.LastOrDefault(), record.Name, StringComparison.OrdinalIgnoreCase));
                    var diskVersion = At(_work.Parsed.Objects, objectPath);
                    if (ideObject == null)
                    {
                        if (diskVersion == null) return Refused(_call, _work.Data, "cannot identify disk text to restore: " + record.Name);
                        _work.ForcedCreateItems.Add(diskVersion);
                        continue;
                    }
                    diskVersion = diskVersion ?? At(_work.Parsed.Objects, ideObject.Key);
                    var guid = record.Guid;
                    if (string.IsNullOrEmpty(guid) && !_work.IdeByPath.TryGetValue(ideObject.Key, out guid))
                        return Refused(_call, _work.Data, "cannot identify IDE object to force-update: " + record.Name);
                    if (diskVersion == null) _work.ForcedDeletes.Add(guid);
                    else { _work.Writes.Add(new TextWrite { Guid = guid, Item = diskVersion }); _work.Updated.Add(record.Name); }
                }
                foreach (var item in _work.ForcedCreateItems)
                {
                    if (CreateKind(item.Kind) == null) return Refused(_call, _work.Data, "cannot recreate object kind " + item.Kind + " for " + item.Key);
                    var parent = item.Path.Length < 2 ? null : string.Join("/", item.Path.Take(item.Path.Length - 1));
                    var forcedParent = _work.ForcedCreateItems.Any(candidate => candidate.Key.Equals(parent, StringComparison.OrdinalIgnoreCase));
                    if (parent != null && !_work.IdeByPath.ContainsKey(parent) && !_folderCreateKeys.Contains(parent, StringComparer.OrdinalIgnoreCase) && !forcedParent && !_addedKeys.Contains(parent))
                        return Refused(_call, _work.Data, "no IDE parent to restore " + item.Key);
                }
                return null;
            }

            // A deleted and an added object with the same text are one rename.
            internal void MatchRenames()
            {
                var consumedAdded = new HashSet<CompareRecord>();
                var consumedDeleted = new HashSet<CompareRecord>();
                _work.Renames = new List<RenameText>();
                foreach (var pair in _work.AddedItems)
                {
                    var item = pair.Item;
                    var old = _work.Deleted.FirstOrDefault(record => !consumedDeleted.Contains(record)
                        && record.ObjectPath != null
                        && !string.Equals(record.ObjectPath, item.Key, StringComparison.OrdinalIgnoreCase)
                        && At(_work.IdeObjects, record.ObjectPath) is StViewObject oldObject
                        && _work.IdeByPath.ContainsKey(oldObject.Key)
                        && SameRenameText(oldObject, item, record.Name, item.Path.Last()));
                    if (old == null) continue;
                    var oldKey = old.ObjectPath;
                    if (!_work.IdeByPath.TryGetValue(oldKey, out var oldGuid)) continue;
                    _work.Renames.Add(new RenameText { Guid = oldGuid, Item = item, DeletedRecord = old });
                    consumedAdded.Add(pair.Record); consumedDeleted.Add(old);
                }
                _work.AddedItems = _work.AddedItems.Where(pair => !consumedAdded.Contains(pair.Record)).ToList();
                _work.Deleted = _work.Deleted.Where(record => !consumedDeleted.Contains(record)).ToList();
                _work.Deleted = _work.Deleted.Where(record => !_work.Deleted.Any(owner => !ReferenceEquals(owner, record)
                    && owner.Path.Equals(record.Path)
                    && Path.GetFileNameWithoutExtension(owner.Path) == owner.Name
                    && !Path.GetFileNameWithoutExtension(record.Path).Equals(record.Name, StringComparison.OrdinalIgnoreCase))).ToList();
            }

            // The IDE's natives to replace: their MetaObject properties, so only
            // changed ones are set, and their text, to tell a write the IDE took.
            IDictionary<string, object> ReadNativeMeta()
            {
                _work.NativeBefore = new Dictionary<string, IDictionary<string, object>>(StringComparer.OrdinalIgnoreCase);
                if (_work.NativeReplaces.Count > 0)
                {
                    IDictionary<string, object> exported;
                    try { exported = _call.Call("objects.export", new Dictionary<string, object> { { "guids", _work.NativeReplaces.Select(record => Convert.ToString(record.Guid)).ToArray() } }); }
                    catch (AgentException error) { return Refused(_call, _work.Data, "cannot read native MetaObject properties: " + error.Message); }
                    foreach (var item in Items(exported.ContainsKey("objects") ? exported["objects"] : null))
                        if (item.ContainsKey("guid") && item.ContainsKey("meta")) _work.NativeBefore[Convert.ToString(item["guid"]).Trim().Trim('{', '}')] = item;
                }
                // A device's description is not swapped as a property: the IDE's Update Device
                // also changes its parameters, the objects below it and its libraries.
                foreach (var record in _work.NativeReplaces)
                {
                    if (!_work.NativeBefore.TryGetValue(Convert.ToString(record.Guid).Trim().Trim('{', '}'), out var before)) continue;
                    var disk = File.ReadAllText(Path.Combine(_work.View, record.Path.Replace('/', Path.DirectorySeparatorChar)));
                    var wanted = DeviceDescription(disk);
                    if (wanted == DeviceDescription(Convert.ToString(before["meta"]))) continue;
                    var parts = wanted.Split('|');
                    var change = parts.Length == 3
                        ? "cts project change-device --device \"" + Path.GetFileName(FolderKey(record.Path)) + "\" --type " + parts[0]
                            + " --id \"" + parts[1] + "\" --version " + parts[2]
                        : "cts project change-device";
                    return Refused(_call, _work.Data, record.Path + ": the device is another type or version on disk; "
                        + change + " makes the IDE's device that one, then cts sync --take disk writes the rest of its settings");
                }
                return null;
            }

        }
    }
}
