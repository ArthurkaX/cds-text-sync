using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // Applies the planned changes to the IDE and disk.
        sealed class ImportApply
        {
            readonly CliCall _call;
            readonly ImportWork _work;
            List<IDictionary<string, object>> _readBack, _nativeApplyMisses;
            List<NativeWrite> _nativeWrites;
            List<string> _folderDeletes, _emptiedFolders, _settings, _updatedFieldObjects;

            internal ImportApply(CliCall call, ImportWork work)
            {
                _call = call;
                _work = work;
            }

            // What the IDE deleted leaves the disk: its .xml and .csv go; a .st
            // only the IDE changed goes with its last object, or becomes the
            // IDE's render of it when that holds the rest of the file's objects.
            // Returns the files it wrote or removed.
            List<string> RemoveIdeDeleted()
            {
                var touched = new List<string>();
                foreach (var record in _work.NativeRecords.Concat(_work.CsvRecords).Concat(_work.FolderRecords).Where(ComparePlanner.IdeDeleted))
                {
                    if (_work.Stamps.Delete(record.Path)) touched.Add(record.Path);
                }
                foreach (var file in _work.StRecords.Where(ComparePlanner.IdeDeleted).Select(record => record.Path).Distinct(StringComparer.OrdinalIgnoreCase).ToList())
                {
                    if (_work.StRecords.Any(record => record.Path.Equals(file, StringComparison.OrdinalIgnoreCase) && record.Category != "ide_changed")) continue;
                    var gone = new HashSet<string>(_work.StRecords.Where(record => ComparePlanner.IdeDeleted(record) && record.Path.Equals(file, StringComparison.OrdinalIgnoreCase)).Select(record => record.ObjectPath), StringComparer.OrdinalIgnoreCase);
                    var kept = _work.Parsed.Objects.Where(item => item.File.Equals(file, StringComparison.OrdinalIgnoreCase) && !gone.Contains(item.Key)).Select(item => item.Key).ToList();
                    if (kept.Count == 0 ? _work.Stamps.Delete(file)
                        : _work.IdeFiles != null && _work.IdeFiles.TryGetValue(file, out var bytes)
                            && new HashSet<string>(kept, StringComparer.OrdinalIgnoreCase).SetEquals((_work.IdeObjects ?? new List<StViewObject>()).Where(item => item.File.Equals(file, StringComparison.OrdinalIgnoreCase)).Select(item => item.Key))
                            && _work.Stamps.Write(file, bytes))
                        touched.Add(file);
                }
                // A folder the IDE deleted goes once its files did.
                foreach (var record in _work.FolderRecords.Where(ComparePlanner.IdeDeleted).OrderByDescending(record => record.Path.Count(ch => ch == '/')))
                {
                    var folder = Path.Combine(_work.View, FolderKey(record.Path).Replace('/', Path.DirectorySeparatorChar));
                    if (Directory.Exists(folder) && !Directory.EnumerateFileSystemEntries(folder).Any()) Directory.Delete(folder);
                }
                return touched;
            }

            // --force keeps the IDE's text on refs/cts/overwritten before anything is written.
            internal IDictionary<string, object> Preserve()
            {
                if (_work.ForceRecords.Count > 0)
                {
                    if (_work.IdeFiles == null) return Refused(_call, _work.Data, "cannot preserve the IDE's text before --force");
                    var viewRelative = ExportCommand.Relative(_work.Folder, _work.View);
                    var preserve = new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase);
                    foreach (var record in _work.ForceRecords)
                    {
                        var objectPath = record.ObjectPath;
                        var ide = objectPath == null ? null : At(_work.IdeObjects, objectPath);
                        // An object the IDE deleted (or moved away) has no text here to keep.
                        if (objectPath != null && ide == null) continue;
                        var path = string.IsNullOrEmpty(ide?.File) ? record.Path : ide.File;
                        if (!_work.IdeFiles.TryGetValue(path, out var bytes)) return Refused(_call, _work.Data, "cannot preserve the IDE's text for " + record.Name);
                        preserve[viewRelative == "." ? path : viewRelative.TrimEnd('/') + "/" + path] = bytes;
                    }
                    try { SyncBase.KeepOverwritten(_work.Folder, viewRelative, preserve); }
                    catch (Exception error) when (error is InvalidOperationException || error is IOException || error is UnauthorizedAccessException)
                    { return Refused(_call, _work.Data, "the IDE's text could not be saved to refs/cts/overwritten: " + error.Message); }
                }
                return null;
            }

            // The new folders, outer ones first, so objects can be created or moved into them.
            void CreateFolders()
            {
                foreach (var record in _work.FolderRecords.Where(record => record.Category == "added").OrderBy(record => FolderDepth(record)))
                {
                    var key = FolderKey(record.Path);
                    var parent = ParentKey(key);
                    var parentGuid = parent.Length == 0 ? "" : _work.Created.TryGetValue(parent, out var newlyCreatedParent) ? newlyCreatedParent
                        : _work.IdeByPath.TryGetValue(parent, out var existingParent) ? existingParent : null;
                    if (parentGuid == null) throw new InvalidOperationException("validated new folder parent is missing: " + key);
                    var reply = _call.Call("objects.create", Below(parentGuid, new Dictionary<string, object>
                    {
                        { "kind", "folder" }, { "name", Path.GetFileName(key) },
                    }));
                    _work.Created[key] = Convert.ToString(reply["guid"]);
                    _work.CreatedFolders.Add(key);
                }
            }

            // The text objects: new folders, deletes, renames and moves, recreated
            // and new objects, every text write and build flag, then the read-back.
            internal void ApplyTexts()
            {
                CreateFolders();
                foreach (var rename in _work.Renames)
                {
                    var parent = ParentKey(rename.Item.Key);
                    if (string.Equals(ParentKey(Convert.ToString(rename.DeletedRecord.ObjectPath)), parent, StringComparison.OrdinalIgnoreCase)) continue;
                    rename.ParentGuid = parent.Length == 0 ? "" : _work.Created.TryGetValue(parent, out var created) ? created
                        : _work.IdeByPath.TryGetValue(parent, out var existing) ? existing
                        : throw new InvalidOperationException("validated move target is missing: " + parent);
                }
                Apply(_call, _work.Deleted, _work.ForcedDeletes, _work.Renames, _work.Writes);
                _emptiedFolders = EmptiedFolders(_work.View, _work.Deleted.Concat(_work.NativeDeletes).Concat(_work.Renames.Select(rename => rename.DeletedRecord)).ToList(), _work.IdeNodes).ToList();
                _folderDeletes = _work.FolderRecords.Where(record => record.Category == "deleted"
                        || record.Category == "ide_changed" && _work.HasBase && _call.Options.Params.ContainsKey("force"))
                    .Select(record => FolderKey(record.Path))
                    .Concat(_emptiedFolders)
                    .Distinct(StringComparer.OrdinalIgnoreCase).OrderByDescending(key => key.Count(ch => ch == '/')).ToList();
                _nativeWrites = new List<NativeWrite>();
                foreach (var item in _work.ForcedCreateItems.OrderBy(item => item.Path.Length))
                {
                    _work.Writes.Add(new TextWrite { Guid = Convert.ToString(Create(item, "restore")["guid"]), Item = item });
                    _work.ForcedCreated.Add(item.Path.Last());
                }
                foreach (var item in _work.AddedItems.Select(pair => pair.Item))
                {
                    var reply = Create(item, "new object");
                    _work.Writes.Add(new TextWrite { Guid = Convert.ToString(reply["guid"]), Item = item });
                    if (reply.TryGetValue("accessors", out var rawAccessors) && Items(rawAccessors) is var accessors && accessors.Any())
                        foreach (var accessor in accessors)
                        {
                            _work.CreatedAccessorNames.Add(Convert.ToString(accessor["name"]));
                            var accessorView = _work.Parsed.Objects.FirstOrDefault(candidate => candidate.Path.Length == item.Path.Length + 1
                                && candidate.Path.Take(item.Path.Length).SequenceEqual(item.Path, StringComparer.OrdinalIgnoreCase)
                                && string.Equals(candidate.Path.Last(), Convert.ToString(accessor["name"]), StringComparison.OrdinalIgnoreCase));
                            if (accessorView != null) _work.Writes.Add(new TextWrite { Guid = Convert.ToString(accessor["guid"]), Item = accessorView });
                        }
                }
                foreach (var pair in _work.Writes) WriteText(_call, pair.Guid, pair.Item);
                // The pragma's settings the IDE does not have yet, a removed one
                // back to its default.
                _settings = new List<string>();
                foreach (var pair in _work.Writes)
                {
                    var ide = At(_work.IdeObjects, pair.Item.Key);
                    foreach (var setting in StPragma.Settings)
                    {
                        var value = StPragma.Value(pair.Item.Settings, setting);
                        if (value == StPragma.Value(ide?.Settings, setting)) continue;
                        _call.Call("objects.setfield", new Dictionary<string, object> { { "guid", pair.Guid }, { "prop", setting.Prop }, { "path", setting.Name }, { "value", value } });
                        _settings.Add(setting.Name);
                    }
                }
                _readBack = _work.Writes.Count == 0 ? new List<IDictionary<string, object>>() : ReadBack(_call, _work.Writes);
            }

            // Creates *item* with its text below its parent, one this run made or
            // one the IDE has; the planning checked both exist.
            IDictionary<string, object> Create(StViewObject item, string what)
            {
                var key = item.Key;
                var parent = item.Path.Length < 2 ? null : string.Join("/", item.Path.Take(item.Path.Length - 1));
                var parentGuid = parent == null ? "" : _work.Created.TryGetValue(parent, out var newParent) ? newParent
                    : _work.IdeByPath.TryGetValue(parent, out var existingParent) ? existingParent : null;
                if (parentGuid == null) throw new InvalidOperationException("validated " + what + " parent is missing: " + key);
                var kind = CreateKind(item.Kind);
                if (kind == null) throw new InvalidOperationException("validated " + what + " kind is missing: " + item.Kind);
                var parameters = Below(parentGuid, new Dictionary<string, object> { { "kind", kind }, { "name", item.Path.Last() } });
                var declaration = StripPragma(item.Declaration);
                if (!string.IsNullOrWhiteSpace(declaration)) parameters["declaration"] = declaration;
                if (item.Implementation != null) parameters["implementation"] = item.Implementation;
                if (kind == "property") parameters["accessors"] = PropertyAccessors(_work.Parsed, item);
                var reply = _call.Call("objects.create", parameters);
                _work.Created[key] = Convert.ToString(reply["guid"]);
                return reply;
            }

            // The native objects: deletes, imports, replaces.
            internal void ApplyNatives()
            {
                foreach (var record in _work.NativeDeletes)
                    _call.Call("objects.delete", new Dictionary<string, object> { { "guid", record.Guid } });
                _nativeApplyMisses = new List<IDictionary<string, object>>();
                foreach (var record in _work.NativeImports)
                {
                    var path = record.Path;
                    var full = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                    var content = File.ReadAllText(full);
                    var csv = CsvOf(path);
                    var parentGuid = record.ParentKey != null && _work.Created.TryGetValue(Convert.ToString(record.ParentKey), out var createdParent)
                        ? createdParent : Convert.ToString(record.ParentGuid);
                    IDictionary<string, object> reply;
                    try
                    {
                        reply = _call.Call("objects.import", new Dictionary<string, object>
                        {
                            { "parent_guid", parentGuid }, { "xml", WithRows(csv, content) },
                        });
                    }
                    catch (CliFailure error) when (error.Declined)
                    {
                        _nativeApplyMisses.Add(new Dictionary<string, object> { { "guid", "" }, { "name", record.Name }, { "path", path }, { "error", error.Message } });
                        continue;
                    }
                    var guid = Convert.ToString(reply["guid"]);
                    parentGuid = Convert.ToString(reply.ContainsKey("parent_guid") ? reply["parent_guid"] : parentGuid);
                    content = PlaceNative(_work.Stamps, full, content, NativeMetaValue(content, "Guid"), guid, parentGuid);
                    _nativeWrites.Add(new NativeWrite { Guid = guid, Name = NativeMetaValue(content, "Name"), Path = path, Content = content, Created = true, Csv = csv });
                }
                foreach (var record in _work.NativeReplaces)
                {
                    var path = record.Path;
                    var full = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                    // Both sides' edits, merged: the file gets them first, unless it changed
                    // meanwhile; then the object waits for the next sync.
                    if (record.MergedXml != null && !_work.Stamps.Write(full, (byte[])record.MergedXml)) continue;
                    var csv = CsvOf(path);
                    var content = WithRows(csv, File.ReadAllText(full));
                    var parameters = new Dictionary<string, object> { { "guid", record.Guid }, { "xml", content } };
                    _work.NativeBefore.TryGetValue(Convert.ToString(record.Guid).Trim().Trim('{', '}'), out var before);
                    if (before != null)
                    {
                        var properties = NativePropertyChangesFromMeta(content, Convert.ToString(before["meta"]));
                        if (properties.Count > 0) parameters["properties"] = properties;
                    }
                    IDictionary<string, object> replaced;
                    try { replaced = _call.Call("objects.replace", parameters); }
                    catch (CliFailure error) when (error.Declined)
                    {
                        _nativeApplyMisses.Add(new Dictionary<string, object> { { "guid", Convert.ToString(record.Guid) }, { "name", record.Name }, { "path", path }, { "error", error.Message } });
                        continue;
                    }
                    // A Library Manager's libraries the IDE could not load: the build names what is missing.
                    foreach (var library in Items(replaced != null && replaced.ContainsKey("libraries") ? replaced["libraries"] : null))
                    {
                        if (!_work.Data.ContainsKey("libraries_not_loaded")) _work.Data["libraries_not_loaded"] = new List<object>();
                        ((List<object>)_work.Data["libraries_not_loaded"]).Add(library);
                    }
                    _nativeWrites.Add(new NativeWrite { Guid = Convert.ToString(record.Guid), Name = record.Name, Path = path, Content = content, Before = JsonMap.Text(before, "object"), Csv = csv });
                }
            }

            // The .csv beside the .xml at *path*, null when it has none.
            string CsvOf(string path)
            {
                var csv = Path.ChangeExtension(path, ".csv").Replace('\\', '/');
                return File.Exists(Path.Combine(_work.View, csv.Replace('/', Path.DirectorySeparatorChar))) ? csv : null;
            }

            // *content* as the IDE is given it: a text list's with the rows of its *csv*.
            string WithRows(string csv, string content) => csv == null || !TextListRows.IsTextList(NativeMetaValue(content, "TypeGuid")) ? content
                : TextListRows.With(content, File.ReadAllText(Path.Combine(_work.View, csv.Replace('/', Path.DirectorySeparatorChar)))) ?? content;

            // The text lists, row by row, each read back.
            internal void ApplyTextLists()
            {
                _updatedFieldObjects = new List<string>();
                foreach (var planFields in _work.CsvPlans)
                {
                    if (planFields.UnappliedError != null)
                    {
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", planFields.Guid }, { "name", planFields.Name }, { "path", planFields.Path }, { "error", planFields.UnappliedError } });
                        continue;
                    }
                    try
                    {
                    // Planned again against the IDE as it is now: the object's .xml, imported
                    // above, may already hold the rows the csv adds.
                    var text = File.ReadAllText(Path.Combine(_work.View, planFields.Path.Replace('/', Path.DirectorySeparatorChar)));
                    var ideLeaves = FlattenFields(JsonMap.Value(_call.Call("objects.fields", new Dictionary<string, object> { { "guid", planFields.Guid } }), "fields"));
                    var plan = planFields.Group != null ? PlanAlarmMessages(text, _work.IdeFiles[planFields.Path], ideLeaves) : PlanTextList(text, ideLeaves);
                    if (plan.Error != null)
                    {
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", planFields.Guid }, { "name", planFields.Name }, { "path", planFields.Path }, { "error", plan.Error } });
                        continue;
                    }
                    foreach (var index in plan.Removes)
                        _call.Call("objects.listremove", new Dictionary<string, object> { { "guid", planFields.Guid }, { "path", "TextList" }, { "index", index } });
                    foreach (var insert in plan.Inserts)
                        _call.Call("objects.listadd", new Dictionary<string, object> { { "guid", planFields.Guid }, { "path", "TextList" }, { "at", insert.At }, { "fields", insert.Fields } });
                    var currentLeaves = FlattenFields(JsonMap.Value(_call.Call("objects.fields", new Dictionary<string, object> { { "guid", planFields.Guid } }), "fields"));
                    var currentPlan = planFields.Group != null ? plan : PlanTextList(text, currentLeaves);
                    if (currentPlan.Error != null)
                    {
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", planFields.Guid }, { "name", planFields.Name }, { "path", planFields.Path }, { "error", currentPlan.Error } });
                        continue;
                    }
                    foreach (var pair in currentPlan.DiskLeaves)
                        if (pair.Value != null && !string.Equals(Convert.ToString(currentLeaves.ContainsKey(pair.Key) ? currentLeaves[pair.Key] : null), pair.Value, StringComparison.Ordinal))
                            _call.Call("objects.setfield", new Dictionary<string, object> { { "guid", planFields.Guid }, { "path", pair.Key }, { "value", pair.Value } });
                    _updatedFieldObjects.Add(planFields.Name);
                    var readReply = _call.Call("objects.fields", new Dictionary<string, object> { { "guid", planFields.Guid } });
                    var readLeaves = FlattenFields(readReply.TryGetValue("fields", out var readFields) ? readFields : null);
                    var miss = currentPlan.DiskLeaves.FirstOrDefault(pair => pair.Value != null
                        && !string.Equals(Convert.ToString(readLeaves.ContainsKey(pair.Key) ? readLeaves[pair.Key] : null), pair.Value, StringComparison.Ordinal));
                    if (miss.Key != null)
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", planFields.Guid }, { "name", planFields.Name }, { "path", planFields.Path }, { "parts", new[] { miss.Key } } });
                    }
                    catch (CliFailure error) when (error.Declined)
                    {
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", planFields.Guid }, { "name", planFields.Name }, { "path", planFields.Path }, { "error", error.Message } });
                    }
                }
            }

            // What landed goes to disk and the sync base; the answer names it all.
            internal IDictionary<string, object> Finish()
            {
                var nativeReadBack = ReadBackNative(_call, _nativeWrites);
                _readBack.AddRange(nativeReadBack);
                _readBack.AddRange(_nativeApplyMisses);
                _readBack.AddRange(_work.FieldReadBack);
                foreach (var key in _folderDeletes)
                    if (_work.IdeByPath.TryGetValue(key, out var folderGuid)) _call.Call("objects.delete", new Dictionary<string, object> { { "guid", folderGuid } });
                // A folder its last object's delete emptied keeps only its own file on disk; that goes with it.
                foreach (var key in _emptiedFolders.OrderByDescending(key => key.Count(ch => ch == '/')))
                {
                    var folder = Path.Combine(_work.View, key.Replace('/', Path.DirectorySeparatorChar));
                    _work.Stamps.Delete(key + "/.cds-object.xml");
                    if (!Directory.EnumerateFileSystemEntries(folder).Any()) Directory.Delete(folder);
                }
                var unappliedGuids = new HashSet<string>(_readBack.Select(item => Convert.ToString(item["guid"])), StringComparer.OrdinalIgnoreCase);
                var landedLists = _work.CsvPlans.Where(item => !_work.FieldReadBack.Any(miss => Equals(miss["guid"], item.Guid))).ToList();
                // A container the IDE changed or added (a new device, its application)
                // has its .cds-object.xml like any native object.
                var ideNativeFiles = _work.Syncing
                    ? _work.NativeRecords.Concat(_work.FolderRecords).Where(record => record.Category == "ide_changed" && !string.IsNullOrEmpty(record.Guid))
                        .Concat(_work.NativeIdeTaken).Select(record => new IdeFile { Guid = record.Guid, Path = record.Path }).ToList()
                    : new List<IdeFile>();
                if (_work.Syncing)
                    ideNativeFiles.AddRange(_work.CsvRecords.Where(record => record.Category == "ide_changed" && !string.IsNullOrEmpty(record.Guid))
                        .Select(record => new IdeFile { Guid = record.Guid, Path = record.Path, Csv = true }));
                var landedFiles = _nativeWrites.Where(item => !unappliedGuids.Contains(item.Guid)).Select(item => new IdeFile { Guid = item.Guid, Path = item.Path })
                    .Concat(_nativeWrites.Where(item => item.Csv != null && !unappliedGuids.Contains(item.Guid)).Select(item => new IdeFile { Guid = item.Guid, Path = item.Csv, Csv = true }))
                    .Concat(landedLists.Where(item => item.Group == null || item.XmlPath != null)
                        .Select(item => new IdeFile { Guid = item.Guid, Path = item.XmlPath ?? Path.ChangeExtension(item.Path, ".xml") }))
                    .Concat(landedLists.Select(item => new IdeFile { Guid = item.Group ?? item.Guid, Path = item.Path, Csv = true }))
                    .ToList();
                // A folder the import made gets its file as export writes it, so the next export adds none;
                // a file already there (a renamed folder's) still names the old folder's guid and name.
                var newFolders = _work.CreatedFolders.Select(key => key + "/.cds-object.xml")
                    .Select(path => new IdeFile { Guid = _work.Created[FolderKey(path)], Path = path });
                var toDisk = WriteIdeFiles(_call, _work.View, _work.Stamps, landedFiles.Concat(ideNativeFiles).Concat(newFolders).ToList());
                foreach (var path in _work.IdeNewTextFiles)
                {
                    var full = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                    var members = _work.IdeNewTextObjects.Where(item => item.File.Equals(path, StringComparison.OrdinalIgnoreCase)
                        && IsStMember(item.Kind)
                        && (!(item.Kind == "GET" || item.Kind == "SET") || !_work.IdeNewTextObjects.Any(parent => parent.Kind == "PROPERTY"
                            && parent.Path.Length + 1 == item.Path.Length && item.Path.Take(parent.Path.Length).SequenceEqual(parent.Path, StringComparer.OrdinalIgnoreCase))))
                        .OrderBy(item => item.DeclarationLine).ToList();
                    if (File.Exists(full) && members.Count > 0)
                        foreach (var member in members) AppendNewMember(_work.Stamps, full, _work.IdeFiles[path], member);
                    else _work.Stamps.Write(full, _work.IdeFiles[path]);
                }
                foreach (var edit in _work.MergeFiles.Where(edit => !unappliedGuids.Contains(edit.Guid)))
                    ReplaceObjectParts(_work.View, _work.Stamps, edit.Original, edit.Merged);
                foreach (var edit in _work.IdeToDisk.Where(edit => !unappliedGuids.Contains(edit.Guid)))
                    ReplaceObjectParts(_work.View, _work.Stamps, edit.Original, edit.Merged);
                var ideRemovedFiles = _work.Syncing && !_call.Options.Params.ContainsKey("force") ? RemoveIdeDeleted() : new List<string>();
                var carriedFiles = _work.Writes.Where(pair => !unappliedGuids.Contains(pair.Guid)).Select(pair => pair.Item.File)
                    .Concat(_nativeWrites.Where(item => !unappliedGuids.Contains(item.Guid)).SelectMany(item => new[] { item.Path, item.Csv }).Where(path => path != null))
                    .Concat(_work.CsvGone)
                    .Concat(_work.CsvPlans.Where(item => !_work.FieldReadBack.Any(miss => Equals(miss["guid"], item.Guid))).Select(item => item.Path))
                    .Concat(_work.Deleted.Select(record => record.Path))
                    .Concat(_work.NativeDeletes.Select(record => record.Path))
                    .Concat(_work.NativeGone.Select(record => record.Path))
                    .Concat(ideNativeFiles.Select(item => item.Path))
                    .Concat(ideRemovedFiles)
                    .Concat(_work.Renames.Select(rename => rename.DeletedRecord.Path))
                    .Concat(_work.ForceRecords.Where(record => _work.ForcedDeletedNames.Contains(record.Name)).Select(record => record.Path))
                    .Concat(_work.FolderRecords.Select(record => record.Path))
                    .Concat(_emptiedFolders.Select(key => key + "/.cds-object.xml"))
                    .Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                foreach (var partialFile in _work.Writes.Where(pair => unappliedGuids.Contains(pair.Guid)).Select(pair => pair.Item.File))
                    carriedFiles.RemoveAll(path => path.Equals(partialFile, StringComparison.OrdinalIgnoreCase));
                foreach (var partialFile in _nativeWrites.Where(item => unappliedGuids.Contains(item.Guid)).Select(item => item.Path))
                    carriedFiles.RemoveAll(path => path.Equals(partialFile, StringComparison.OrdinalIgnoreCase));
                foreach (var partialFile in _work.CsvPlans.Where(item => _work.FieldReadBack.Any(miss => Equals(miss["guid"], item.Guid))).Select(item => item.Path))
                    carriedFiles.RemoveAll(path => path.Equals(partialFile, StringComparison.OrdinalIgnoreCase));
                foreach (var conflictFile in _work.Conflicts.Select(conflict => Convert.ToString(conflict["path"]))
                    .Distinct(StringComparer.OrdinalIgnoreCase))
                    carriedFiles.RemoveAll(path => path.Equals(conflictFile, StringComparison.OrdinalIgnoreCase));
                carriedFiles.AddRange(toDisk);
                carriedFiles.AddRange(_work.IdeNewTextFiles);
                carriedFiles.AddRange(_work.IdeToDisk.Select(edit => edit.Original.File));
                // From another project file's sync, an import that carried every
                // difference makes the disk this project's base.
                var takesOver = _work.OtherProject != null && _work.Conflicts.Count == 0 && unappliedGuids.Count == 0;
                // A file changed on disk meanwhile keeps its base: the IDE did not get that change.
                carriedFiles.RemoveAll(_work.Stamps.Moved);
                var baseName = CarryBase(_work.Folder, _work.View, carriedFiles, takesOver && _work.Stamps.Changed.Count == 0);
                if (takesOver) SyncBase.SaveProject(_work.Folder, _call.Hello.ProjectPath);
                var output = BuildPayload(_call, _work.Data, _work.AddedItems, _work.CreatedAccessorNames, _work.CreatedFolders, _work.Updated, _work.Deleted,
                    _work.ForcedDeletedNames, _work.ForcedCreateItems, _work.ForcedCreated, _folderDeletes, _work.Renames, _settings, _readBack,
                    _work.ForceRecords, baseName);
                output["syncing"] = _work.Syncing;
                if (_work.Stamps.Changed.Count > 0) output["changed_meanwhile"] = _work.Stamps.Changed.ToList();
                output["to_disk"] = toDisk;
                if (_work.IdeToDisk.Count > 0) output["to_disk"] = toDisk.Concat(_work.IdeToDisk.Select(edit => edit.Original.File)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                if (_work.IdeNewTextObjects.Count > 0) output["to_disk"] = ((IEnumerable<string>)output["to_disk"])
                    .Concat(_work.IdeNewTextObjects.Select(item => item.Key)).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                // The .xml beside a .st the IDE needs no more removes settings, not the object.
                var ideRemoved = _work.Changed.Where(record => ComparePlanner.IdeDeleted(record) && !BesideText(record.Path, _work.View)).Select(record => record.Name).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
                if (_work.Syncing && ideRemoved.Count > 0) output["ide_removed"] = ideRemoved;
                output["merged"] = _work.Merged;
                if (_work.Conflicts.Count > 0)
                {
                    output["conflicts"] = _work.Conflicts;
                    output["partial"] = true;
                    output["partial_reason"] = _work.Conflicts.Count + " object(s) changed both in the IDE and on disk since the last sync, left as they are: "
                        + string.Join(", ", _work.Conflicts.Select(item => item["name"]))
                        + ". " + ConflictNext + (_work.ToolNote == null ? "" : " " + _work.ToolNote + ".");
                }
                output["created_native_objects"] = _work.CreatedFolders.Select(Path.GetFileName).Concat(_nativeWrites.Where(item => item.Created).Select(item => item.Name)).ToList();
                output["updated_native_objects"] = _nativeWrites.Where(item => !item.Created).Select(item => item.Name).ToList();
                output["updated_field_objects"] = _updatedFieldObjects;
                output["deleted_objects"] = _work.Deleted.Select(item => item.Name).Concat(_work.NativeDeletes.Select(item => item.Name)).Concat(_work.ForcedDeletedNames).Concat(_folderDeletes.Select(Path.GetFileName)).ToList();
                var createdObjects = output["created_objects"] as IList<object>;
                if (createdObjects != null)
                    createdObjects = createdObjects.Concat(_nativeWrites.Where(item => item.Created).Select(item => (object)new Dictionary<string, object>
                        { { "name", item.Name }, { "path", item.Path } })).ToList();
                if (createdObjects != null) output["created_objects"] = createdObjects;
                if (_work.Conflicts.Count == 0 && unappliedGuids.Count == 0 && !_work.Settling) ProjectSource.Mark(_call, _work.Folder, _work.View, output);
                if (_call.Options.Params.ContainsKey("save") && _readBack.Count == 0
                    && (_work.Writes.Count > 0 || _work.Deleted.Count > 0 || _work.ForcedDeletes.Count > 0 || _folderDeletes.Count > 0 || _work.Renames.Count > 0 || _settings.Count > 0
                        || _nativeWrites.Count > 0 || _work.NativeDeletes.Count > 0 || _work.CreatedFolders.Count > 0 || _updatedFieldObjects.Count > 0))
                {
                    try { _call.Call("project.save", new Dictionary<string, object>()); output["saved"] = true; }
                    catch (CliFailure error) when (error.Declined) { output["save_error"] = error.Message; }
                }
                return output;
            }

        }
    }
}
