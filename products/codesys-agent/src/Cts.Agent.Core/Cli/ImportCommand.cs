using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // Import shares compare's single B/D/I snapshot and its object records.
    // Structural writes follow the shared planner's object records and tree view.
    internal static partial class ImportCommand
    {
        internal static Answer Build(IDictionary<string, object> data)
        {
            if (data.ContainsKey("summary"))
            {
                var summary = data["summary"] as IDictionary<string, object>;
                // A rename or move is a deleted and an added file that are one object: shown once, as itself.
                var renames = Items(data.TryGetValue("renames", out var rawRenames) ? rawRenames : null);
                var renamedFiles = new HashSet<string>(renames.SelectMany(rename => new[] { Convert.ToString(rename["from"]), Convert.ToString(rename["to"]) }), StringComparer.OrdinalIgnoreCase);
                var answer = new Answer().Add("modified", JsonMap.Int(summary, "modified")).Add("added", JsonMap.Int(summary, "added") - renames.Count)
                    .Add("deleted", JsonMap.Int(summary, "deleted") - renames.Count).Add("not_importable", JsonMap.Int(summary, "not_importable"))
                    .Add("ide_changed", JsonMap.Int(summary, "ide_changed"));
                if (renames.Count > 0) answer.Add("renamed", renames.Count);
                var conflicts = Items(data.TryGetValue("conflicts", out var rawConflicts) ? rawConflicts : null);
                if (conflicts.Count > 0) answer.Add("conflicts", conflicts.Count);
                if (data.ContainsKey("refused")) answer.Detail("would be refused: " + data["refused"]).Failed().WithExitCode(1);
                foreach (var conflict in conflicts) answer.Detail("conflict " + conflict["name"] + " " + conflict["path"] + ": changed in the IDE and on disk, the same lines");
                foreach (var name in Values(data, "merges")) answer.Detail("merges " + Name(name) + ": changed in the IDE and on disk, apart; the import merges them");
                if (conflicts.Count > 0) answer.Detail(data["conflict_next"]);
                var objects = data["objects"] as IDictionary<string, object>;
                foreach (var category in new[] { "modified", "added", "deleted", "not_importable", "ide_changed" })
                    if (objects != null && objects.TryGetValue(category, out var raw) && Items(raw) is var rows && rows.Any())
                        foreach (var item in rows.Where(row => !renamedFiles.Contains(Convert.ToString(row["path"]))))
                            answer.Detail(category == "ide_changed" ? ComparePlanner.IdeChangedLine(item) : category + " " + item["name"] + " " + item["path"]);
                foreach (var rename in renames) answer.Detail("renamed " + rename["from"] + " -> " + rename["to"] + ": the object keeps its GUID");
                foreach (var name in Values(data, "would_delete")) answer.Detail("would delete " + name + " in the IDE");
                if (objects != null && objects.TryGetValue("ide_changed", out var changed) && Items(changed) is var ideRows && ideRows.Any())
                    answer.Detail(ComparePlanner.IdeChangedNext(ideRows));
                return answer;
            }
            var createdText = Values(data, "created_text_objects");
            var updatedText = Values(data, "updated_text_objects");
            var createdNative = Values(data, "created_native_objects");
            var updatedNative = Values(data, "updated_native_objects");
            var updatedFields = Values(data, "updated_field_objects");
            var deleted = Values(data, "deleted_objects");
            var created = Values(data, "created_objects");
            var output = new Answer().Add("text", updatedText.Count + createdText.Count + updatedFields.Count)
                .Add("native", createdNative.Count + updatedNative.Count);
            if (created.Count > 0) output.Add("created", created.Count);
            if (deleted.Count > 0) output.Add("deleted", deleted.Count);
            var renamed = Values(data, "renamed_objects");
            if (renamed.Count > 0) output.Add("renamed", renamed.Count);
            foreach (var key in new[] { "merged", "to_disk", "overwritten_ide_changes", "changed_meanwhile" })
                if (Values(data, key).Count > 0) output.Add(key == "overwritten_ide_changes" ? "overwritten" : key, Values(data, key).Count);
            if (data.TryGetValue("timings", out var timings) && timings is IDictionary<string, object> times && times.TryGetValue("total_s", out var seconds)) output.Add("s", seconds);
            output.Add("saved", data.ContainsKey("saved") && Equals(data["saved"], true));
            // A sync names the side each change came from.
            var syncing = Equals(data.ContainsKey("syncing") ? data["syncing"] : null, true);
            foreach (var key in new[] { "created_text_objects", "updated_text_objects", "created_native_objects", "updated_field_objects", "updated_native_objects", "deleted_objects", "renamed_objects" })
                foreach (var item in Values(data, key)) output.Detail((syncing ? "disk -> IDE " : "") + Label(key) + " " + Name(item));
            foreach (var key in new[] { "unapplied_objects", "conflicts", "overwritten_ide_changes", "merged", "to_disk", "ide_removed", "ide_new_members" })
                foreach (var item in Values(data, key))
                    output.Detail(Tag(key, syncing) + " " + Name(item)
                        + (key == "conflicts" && item is IDictionary<string, object> conflict && conflict.ContainsKey("path") ? " " + conflict["path"] : ""));
            foreach (var library in Items(data.ContainsKey("libraries_not_loaded") ? data["libraries_not_loaded"] : null))
                output.Detail("library not loaded " + library["name"] + ": " + library["error"] + " (Library Repository: is it installed?)");
            foreach (var path in Values(data, "changed_meanwhile")) output.Detail(ChangedMeanwhile(path));
            if (data.TryGetValue("partial_reason", out var partialReason)) output.Detail(partialReason);
            if (data.TryGetValue("save_dialog", out var saveDialog)) output.Detail("not saved yet: " + saveDialog + "; the save finishes once it is answered (cts dialog answer)");
            else if (data.TryGetValue("save_error", out var saveError)) output.Detail("not saved: " + saveError + "; cts save saves it");
            if (Equals(data.ContainsKey("partial") ? data["partial"] : null, true)) output.Partial().WithExitCode(2);
            return output;
        }

        internal static string ChangedMeanwhile(object path) =>
            "changed-meanwhile " + path + ": changed on disk while cts ran, so cts left that change on disk and out of the sync base; the next cts compare shows it";
        static List<object> Values(IDictionary<string, object> values, string key) => values != null && values.TryGetValue(key, out var value) && value is System.Collections.IEnumerable items && !(value is string) ? items.Cast<object>().ToList() : new List<object>();
        static string Name(object value) => value is IDictionary<string, object> item ? Convert.ToString(item.ContainsKey("name") ? item["name"] : item.ContainsKey("view_path") ? item["view_path"] : item.ContainsKey("guid") ? item["guid"] : "?") : Convert.ToString(value);
        static string Tag(string key, bool syncing) => key == "unapplied_objects" ? "unapplied" : key == "overwritten_ide_changes" ? "overwrote-ide" : key == "conflicts" ? "conflict"
            : key == "ide_removed" ? (syncing ? "IDE -> disk removed" : "ide-removed") : key == "ide_new_members" ? (syncing ? "IDE -> disk new-member" : "ide-new")
            : key == "to_disk" ? (syncing ? "IDE -> disk" : "to-disk") : key;
        static string Label(string key) => key == "created_text_objects" ? "created" : key == "updated_text_objects" || key == "updated_field_objects" ? "updated" : key == "created_native_objects" ? "created-native" : key == "updated_native_objects" ? "updated-native" : key == "renamed_objects" ? "renamed" : "deleted";

        static bool IsFolderRecord(CompareRecord record) => record.Path.EndsWith("/.cds-object.xml", StringComparison.OrdinalIgnoreCase)
            && (record.Category == "added" || record.Category == "deleted" || record.Category == "ide_changed");
        static int FolderDepth(CompareRecord record) => FolderKey(record.Path).Count(ch => ch == '/');
        // The description a device's file or MetaObject names, "type|id|version";
        // "" for any other object.
        static string DeviceDescription(string xml)
        {
            var identification = XDocument.Parse(xml.TrimStart('\uFEFF')).Descendants()
                .FirstOrDefault(element => (string)element.Attribute("Name") == "DeviceIdentification");
            if (identification == null) return "";
            return string.Join("|", new[] { "Type", "Id", "Version" }.Select(name =>
                identification.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == name)?.Value.Trim() ?? ""));
        }

        static string FolderKey(string containerPath) => (Path.GetDirectoryName(containerPath) ?? "").Replace('\\', '/');
        // An objects.create below the object *parentGuid*; "" is the project
        // root, where an object of the view's top (a shared POU) goes.
        static Dictionary<string, object> Below(string parentGuid, Dictionary<string, object> parameters)
        {
            if (parentGuid.Length == 0) parameters["root"] = true;
            else parameters["parent_guid"] = parentGuid;
            return parameters;
        }

        static string ParentKey(string key) => (Path.GetDirectoryName(key) ?? "").Replace('\\', '/');

        // The view key a new native object *key* goes below; "" is the project
        // root, which the view's top stands for, and POUs/ too for the kinds
        // export writes there (a Library Manager, Project Settings).
        static string NativeParentKey(string key, string xml)
        {
            var parent = ParentKey(key);
            return parent.Equals("POUs", StringComparison.OrdinalIgnoreCase) && SnapshotReader.UnderPous(NativeMetaValue(xml, "TypeGuid")) ? "" : parent;
        }

        static IEnumerable<string> EmptiedFolders(string view, IEnumerable<CompareRecord> deleted, IDictionary<string, TreeObject> ideNodes)
        {
            var candidates = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            var deletedKeys = deleted.Select(record => record.ObjectPath
                ?? Path.Combine(Path.GetDirectoryName(record.Path) ?? "", record.Name).Replace('\\', '/')).ToList();
            foreach (var record in deleted)
            {
                var directory = Path.GetDirectoryName(record.Path);
                while (!string.IsNullOrEmpty(directory))
                {
                    var key = directory.Replace('\\', '/');
                    var full = Path.Combine(view, directory.Replace('/', Path.DirectorySeparatorChar));
                    var descendants = ideNodes.Where(pair => pair.Key.StartsWith(key + "/", StringComparison.OrdinalIgnoreCase)
                        && !string.Equals(pair.Value.Type, ObjectKinds.FolderType, StringComparison.OrdinalIgnoreCase)).Select(pair => pair.Key).ToList();
                    var allObjectsDeleted = descendants.Count > 0 && descendants.All(objectKey => deletedKeys.Any(deletedKey =>
                        objectKey.Equals(deletedKey, StringComparison.OrdinalIgnoreCase)
                        || objectKey.StartsWith(deletedKey.TrimEnd('/') + "/", StringComparison.OrdinalIgnoreCase)));
                    // A directory holding no file but folders' own is gone for git (a move leaves it empty on Windows).
                    if (allObjectsDeleted && ideNodes.TryGetValue(key, out var folder) && string.Equals(folder.Type, ObjectKinds.FolderType, StringComparison.OrdinalIgnoreCase)
                        && (!Directory.Exists(full)
                            || !Directory.GetFiles(full, "*", SearchOption.AllDirectories).Any(file => !Path.GetFileName(file).Equals(".cds-object.xml", StringComparison.OrdinalIgnoreCase))))
                        candidates.Add(key);
                    directory = Path.GetDirectoryName(directory);
                }
            }
            return candidates;
        }

        static ComparePlan Plan(CliCall call) => ComparePlanner.TypedPlan(call);

        static bool BesideText(string path, string view) => path.EndsWith(".xml", StringComparison.OrdinalIgnoreCase)
            && File.Exists(Path.Combine(view, Path.ChangeExtension(path, ".st").Replace('/', Path.DirectorySeparatorChar)));

        internal sealed class AddedText
        {
            internal CompareRecord Record;
            internal StViewObject Item;
        }

        internal sealed class TextWrite
        {
            internal string Guid;
            internal StViewObject Item;
        }

        internal sealed class RenameText
        {
            internal string Guid;
            internal StViewObject Item;
            internal CompareRecord DeletedRecord;
            internal string ParentGuid;		// The folder it moves into, "" for the project root; null when it stays in its own
        }

        internal sealed class MergeFileEdit
        {
            internal string Guid;
            internal StViewObject Original;
            internal StViewObject Merged;
        }

        static void Apply(CliCall call, IList<CompareRecord> deleted,
            IEnumerable<string> forcedDeletes, IList<RenameText> renames,
            IList<TextWrite> writes)
        {
            foreach (var record in deleted)
            {
                call.Call("objects.delete", new Dictionary<string, object> { { "guid", record.Guid } });
            }
            foreach (var guid in forcedDeletes.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                call.Call("objects.delete", new Dictionary<string, object> { { "guid", guid } });
            }
            foreach (var rename in renames)
            {
                if (rename.ParentGuid != null)
                    call.Call("objects.move", Below(rename.ParentGuid, new Dictionary<string, object> { { "guid", rename.Guid } }));
                if (!string.Equals(rename.DeletedRecord.Name, rename.Item.Path.Last(), StringComparison.Ordinal))
                    call.Call("objects.rename", new Dictionary<string, object> { { "guid", rename.Guid }, { "name", rename.Item.Path.Last() } });
                writes.Add(new TextWrite { Guid = rename.Guid, Item = rename.Item });
            }
        }

        static string CarryBase(string folder, string view, IList<string> carriedFiles, bool whole, ViewStamps stamps)
        {
            string baseName = null;
            if (carriedFiles.Count > 0 || whole)
            {
                var gitDir = GitRepository.Run(folder, "rev-parse --absolute-git-dir").Trim();
                var current = GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}");
                var viewRelative = ExportCommand.Relative(folder, view);
                var carried = new HashSet<string>(carriedFiles.Select(path => viewRelative == "." ? path : viewRelative.TrimEnd('/') + "/" + path), StringComparer.OrdinalIgnoreCase);
                // Every file the import did not carry keeps its base entry, a new one
                // the IDE did not take too: the base takes nothing else from the disk.
                var tracked = !whole && current.ExitCode == 0
                    ? GitRepository.Run(folder, "ls-tree -r --name-only " + current.Output.Trim()).Split('\n').Select(path => path.Trim()).Where(path => path.Length > 0)
                        .Concat(Directory.Exists(view) ? Directory.EnumerateFiles(view, "*", SearchOption.AllDirectories)
                            .Select(path => (viewRelative == "." ? "" : viewRelative.TrimEnd('/') + "/") + path.Substring(view.TrimEnd(Path.DirectorySeparatorChar).Length + 1).Replace(Path.DirectorySeparatorChar, '/')) : Enumerable.Empty<string>())
                    : Enumerable.Empty<string>();
                baseName = SyncBase.Record(folder, viewRelative, tracked.Where(path => !carried.Contains(path)).Distinct(StringComparer.Ordinal).ToList(), stamps, carried);
                var stampPath = Path.Combine(gitDir, "cts", "ide-stamp.json");
                if (File.Exists(stampPath)) File.Delete(stampPath);
            }
            return baseName;
        }

        static IDictionary<string, object> BuildPayload(CliCall call, IDictionary<string, object> data,
            IList<AddedText> addedItems, IList<string> createdAccessorNames,
            IList<string> createdFolders, IList<string> updated, IList<CompareRecord> deleted,
            IList<string> forcedDeletedNames, IList<StViewObject> forcedCreateItems, IList<string> forcedCreated,
            IList<string> folderDeletes, IList<RenameText> renames,
            IList<string> settings, IList<IDictionary<string, object>> readBack, IList<CompareRecord> forceRecords,
            string baseName)
        {
            var output = new Dictionary<string, object>
            {
                { "created_text_objects", addedItems.Select(pair => pair.Record.Name).Concat(createdAccessorNames).Concat(forcedCreated).ToList() }, { "created_native_objects", createdFolders.Select(Path.GetFileName).ToList() },
                { "updated_text_objects", updated },
                { "updated_field_objects", new List<string>() }, { "updated_native_objects", new List<string>() },
                { "created_objects", addedItems.Select(pair => (object)new Dictionary<string, object> { { "name", pair.Record.Name }, { "path", pair.Record.Path } })
                    .Concat(forcedCreateItems.Select(item => (object)new Dictionary<string, object> { { "name", item.Path.Last() }, { "path", item.File } }))
                    .Concat(createdAccessorNames.Select(name => (object)new Dictionary<string, object> { { "name", name } }))
                    .Concat(createdFolders.Select(key => (object)new Dictionary<string, object> { { "name", Path.GetFileName(key) }, { "path", key } })).ToList() },
                { "deleted_objects", deleted.Select(item => item.Name).Concat(forcedDeletedNames).Concat(folderDeletes.Select(Path.GetFileName)).ToList() },
                { "renamed_objects", renames.Select(rename => rename.Item.Key).ToList() }, { "settings", settings },
                { "saved", false }, { "unapplied_objects", readBack }, { "base", baseName ?? data["base"] },
            };
            if (forceRecords.Count > 0) output["overwritten_ide_changes"] = forceRecords.Select(record => string.IsNullOrEmpty(record.ObjectPath) ? record.Path : record.ObjectPath).Distinct().ToList();
            if (data.TryGetValue("timings", out var resultTimings)) output["timings"] = resultTimings;
            if (data.TryGetValue("libraries_not_loaded", out var notLoaded)) output["libraries_not_loaded"] = notLoaded;
            if (readBack.Count > 0)
            {
                output["partial"] = true;
                output["partial_reason"] = "the IDE did not read back the text written for " + string.Join(", ", readBack.Select(item => item["name"]));
                if (call.Options.Params.ContainsKey("allow_unapplied"))
                {
                    output["partial"] = false;
                    output["partial_acknowledged"] = output["partial_reason"];
                }
            }
            return output;
        }

        static string Refusal(CliCall call, IDictionary<string, object> data, IList<CompareRecord> changed)
        {
            if (changed.Count > 0)
            {
                var status = call.Call("project.status", new Dictionary<string, object>());
                var plc = status.TryGetValue("plc", out var plcValue) ? plcValue as IDictionary<string, object> : null;
                if (plc != null && Equals(plc.ContainsKey("online") ? plc["online"] : null, true))
                {
                    return "The IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat `cts " + call.Command.Words + "`.";
                }
            }

            var notImportable = changed.Where(record => record.Category == "not_importable").ToList();
            if (notImportable.Count > 0)
            {
                var first = notImportable[0];
                var reason = first.Path + ": " + Convert.ToString(first.Reason ?? "not importable");
                return notImportable.Count == 1 ? reason : reason + " (and " + (notImportable.Count - 1) + " more: cts compare lists them)";
            }
            var refused = changed.FirstOrDefault(record => !new[] { "modified", "added", "deleted", "ide_changed" }.Contains(record.Category));
            if (refused != null)
            {
                return "import cannot carry " + refused.Category + " object " + refused.Name;
            }
            var hasBase = Equals(data.ContainsKey("base") ? data["base"] : null, true);
            refused = changed.FirstOrDefault(record => hasBase && record.IdeChanged
                && !record.Path.EndsWith(".xml", StringComparison.OrdinalIgnoreCase)
                && !record.Path.EndsWith(".st", StringComparison.OrdinalIgnoreCase));
            if (refused != null && !call.Options.Params.ContainsKey("force"))
            {
                return "changed in the IDE since the last sync: " + refused.Name + " (cts import --force)";
            }
            if (changed.Count > 0)
            {
                var permissions = call.Call("project.permissions", new Dictionary<string, object>());
                var deny = permissions.TryGetValue("deny", out var rawDeny) && rawDeny is System.Collections.IEnumerable deniedValues
                    ? deniedValues.Cast<object>().Select(Convert.ToString).ToList() : new List<string>();
                if (permissions.TryGetValue("config_error", out var configError)) return Convert.ToString(configError);
                var needsTextWrite = changed.Any(record => record.Category == "modified" || record.Category == "added"
                    || record.Category == "ide_changed" && hasBase && call.Options.Params.ContainsKey("force"));
                var deletedRecords = changed.Where(record => record.Category == "deleted").ToList();
                var addedRecords = changed.Where(record => record.Category == "added").ToList();
                // An added file in the deleted one's folder may be its rename, one of its name elsewhere its move.
                var needsDelete = deletedRecords.Any(deleted => !addedRecords.Any(added =>
                    string.Equals(Path.GetDirectoryName(added.Path), Path.GetDirectoryName(deleted.Path), StringComparison.OrdinalIgnoreCase)
                    || string.Equals(Path.GetFileName(added.Path), Path.GetFileName(deleted.Path), StringComparison.OrdinalIgnoreCase)))
                    || hasBase && call.Options.Params.ContainsKey("force") && changed.Any(record =>
                        record.Category == "ide_changed" && Convert.ToString(record.Reason ?? "").StartsWith("not in the view", StringComparison.Ordinal)
                        || record.Category == "modified" && record.IdeChanged);
                var needsSave = call.Options.Params.ContainsKey("save") && (needsTextWrite || needsDelete);
                var requiredKeys = new List<string>();
                if (needsTextWrite) requiredKeys.Add("sync_import_text");
                if (needsDelete) requiredKeys.Add("delete_pou");
                if (needsSave) requiredKeys.Add("save_project");
                foreach (var key in requiredKeys)
                {
                    var blocked = deny.FirstOrDefault(item => item == key || item.Length > 0 && key.StartsWith(item, StringComparison.Ordinal));
                    if (blocked != null)
                    {
                        var reason = blocked == key ? "Forbidden by the deny list (deny list includes '" + key + "')"
                            : "Forbidden by the deny list (pattern '" + blocked + "' matches '" + key + "')";
                        if (key == "delete_pou" && deletedRecords.Count > 0) reason += ": it would delete " + Names(deletedRecords) + " from the project";
                        if (key == "delete_pou") reason += "; nothing was imported, the other changes neither";
                        return reason + "  See `cts permissions`.";
                    }
                }
            }
            return null;
        }

        internal static IDictionary<string, object> Execute(CliCall call) => Run(call, string.Equals(call.Command.Name, "sync", StringComparison.OrdinalIgnoreCase));

        // `cts import`, or with *syncing* `cts sync`.
        internal static IDictionary<string, object> Run(CliCall call, bool syncing) => new ImportRun(call, syncing, false).Execute();

        // After `cts export --tool`: the text objects the disk changed too,
        // merged, or settled side by side, the IDE's text on the right.
        internal static IDictionary<string, object> Settle(CliCall call) => new ImportRun(call, false, true).Execute();

        // A refusal writes nothing: --dry-run shows it under the plan, an import fails with it.
        // The first few records' names, and how many more there are.
        // What to do with objects both sides changed in the same lines.
        static string ConflictNext(CliCall call) => "Keep the disk text: cts " + call.Command.Words + " --take disk. Keep the IDE text: cts "
            + call.Command.Words + " --take ide. One object: --take KEY=disk or KEY=ide, KEY its file or the key its conflict names; the side's text goes to both.";

        static string Names(IList<CompareRecord> records)
        {
            var names = string.Join(", ", records.Take(5).Select(record => record.Name));
            return records.Count > 5 ? names + " and " + (records.Count - 5) + " more" : names;
        }

        static IDictionary<string, object> Refused(CliCall call, IDictionary<string, object> data, string reason)
        {
            if (!call.Options.Params.ContainsKey("dry_run")) throw new CliFailure("import", "refused", reason, null, 1);
            data["refused"] = reason;
            return data;
        }

        // The rows of a JSON array (the agent's replies carry List<object>).
        static List<IDictionary<string, object>> Items(object raw) => (raw as System.Collections.IEnumerable)?.OfType<IDictionary<string, object>>().ToList() ?? new List<IDictionary<string, object>>();

        // The object at key; none for a null key.
        static StViewObject At(IEnumerable<StViewObject> objects, string key) =>
            key == null ? null : objects?.FirstOrDefault(item => string.Equals(item.Key, key, StringComparison.OrdinalIgnoreCase));

        static StViewObject FindViewObject(StViewResult parsed, CompareRecord record) =>
            At(parsed.Objects, record.ObjectPath) ?? parsed.Objects.FirstOrDefault(candidate =>
                candidate.File.Equals(record.Path, StringComparison.OrdinalIgnoreCase)
                && string.Equals(candidate.Path.LastOrDefault(), record.Name, StringComparison.OrdinalIgnoreCase));

        static int RecordDepth(CompareRecord record, StViewResult parsed) => FindViewObject(parsed, record)?.Path.Length ?? 0;

        // A view file of an object the import wrote, to take from the IDE.
        sealed class IdeFile
        {
            internal string Guid;
            internal string Path;
            //: The object's .csv: a text list's, or an alarm group's with its messages.
            internal bool Csv;
        }

        // The files of the objects the import wrote, as `cts export` writes them
        // from the IDE now: the IDE completes what it was given (a new object's
        // place, computed properties), and the
        // file and the base must hold that.  A file that already is so stays.
        static List<string> WriteIdeFiles(CliCall call, string view, ViewStamps stamps, IList<IdeFile> files)
        {
            var written = new List<string>();
            if (files.Count == 0) return written;
            var snapshot = Path.Combine(Path.GetTempPath(), "cts-import-" + System.Guid.NewGuid().ToString("N") + ".xml");
            try
            {
                var guids = files.Select(file => file.Guid).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
                call.Call("project.export", new Dictionary<string, object> { { "path", snapshot }, { "guids", guids } });
                var entries = SnapshotReader.Read(snapshot).Nodes;
                // An alarm group's .csv needs the text list of its messages too.
                var messages = files.Where(file => file.Csv && entries.ContainsKey(GuidKey(file.Guid))).Select(file => ViewExport.AlarmMessagesGuid(entries[GuidKey(file.Guid)].Entry))
                    .Where(guid => guid != null && !entries.ContainsKey(guid)).Distinct().ToArray();
                if (messages.Length > 0)
                {
                    call.Call("project.export", new Dictionary<string, object> { { "path", snapshot }, { "guids", messages } });
                    foreach (var pair in SnapshotReader.Read(snapshot).Nodes) entries[pair.Key] = pair.Value;
                }
                foreach (var file in files.GroupBy(file => file.Path, StringComparer.OrdinalIgnoreCase).Select(group => group.First()))
                {
                    if (!entries.TryGetValue(GuidKey(file.Guid), out var node)) continue;
                    var full = Path.Combine(view, file.Path.Replace('/', Path.DirectorySeparatorChar));
                    var bytes = file.Csv ? ViewExport.CsvBytes(node.Entry, entries.TryGetValue(ViewExport.AlarmMessagesGuid(node.Entry) ?? "", out var list) ? list.Entry : null)
                        : File.Exists(Path.ChangeExtension(full, ".st")) ? ViewExport.SettingsBytes(node.Entry)
                        : ViewExport.NativeBytes(node.Entry, TextListRows.IsTextList(node.Type) && (File.Exists(Path.ChangeExtension(full, ".csv"))
                            || files.Any(other => other.Csv && string.Equals(other.Path, Path.ChangeExtension(file.Path, ".csv"), StringComparison.OrdinalIgnoreCase))));
                    if (bytes == null) continue;
                    if (File.Exists(full) && File.ReadAllBytes(full).SequenceEqual(bytes)) continue;
                    if (stamps.Write(full, bytes)) written.Add(file.Path);
                }
            }
            finally { File.Delete(snapshot); }
            return written;
        }

        static string GuidKey(string guid) => guid.Trim().Trim('{', '}').ToLowerInvariant();

        static void WriteText(CliCall call, string guid, StViewObject item)
        {
            var parameters = new Dictionary<string, object> { { "guid", guid } };
            if (!string.IsNullOrEmpty(item.Declaration)) parameters["declaration"] = StripPragma(item.Declaration);
            if (item.Implementation != null) parameters["implementation"] = item.Implementation;
            if (parameters.Count > 1) call.Call("objects.settext", parameters);
        }

        static List<IDictionary<string, object>> ReadBack(CliCall call, IList<TextWrite> writes)
        {
            var guids = writes.Select(pair => pair.Guid).ToArray();
            var reply = call.Call("objects.texts", new Dictionary<string, object> { { "guids", guids } });
            var records = reply.ContainsKey("objects") ? Items(reply["objects"]) : null;
            var byGuid = (records ?? Enumerable.Empty<IDictionary<string, object>>()).ToDictionary(item => Convert.ToString(item["guid"]), StringComparer.OrdinalIgnoreCase);
            return writes.Where(pair => !byGuid.TryGetValue(pair.Guid, out var got)
                || !SameText(StripPragma(pair.Item.Declaration), StripPragma(Convert.ToString(got.ContainsKey("declaration") ? got["declaration"] : null)))
                || !SameText(pair.Item.Implementation, Convert.ToString(got.ContainsKey("implementation") ? got["implementation"] : null)))
                .Select(pair => (IDictionary<string, object>)new Dictionary<string, object>
                {
                    { "guid", pair.Guid }, { "name", pair.Item.Path.LastOrDefault() }, { "path", pair.Item.File },
                    { "parts", new[] { "declaration", "implementation" } },
                }).GroupBy(item => Convert.ToString(item["guid"]), StringComparer.OrdinalIgnoreCase).Select(group => group.First()).ToList();
        }

        static bool SameText(string left, string right) => string.Equals(StText.Lf(left).Trim(),
            StText.Lf(right).Trim(), StringComparison.Ordinal);

        static string CreateKind(string kind)
        {
            switch ((kind ?? "").ToUpperInvariant())
            {
                case "PROGRAM": case "FUNCTION_BLOCK": case "FUNCTION": return "pou";
                case "INTERFACE": return "interface";
                case "VAR_GLOBAL": return "gvl";
                case "TYPE": return "dut";
                case "METHOD": return "method";
                case "PROPERTY": return "property";
                case "ACTION": return "action";
                default: return null;
            }
        }

        static Dictionary<string, string> PropertyAccessors(StViewResult parsed, StViewObject property)
        {
            return parsed.Objects.Where(item => item.Path.Length == property.Path.Length + 1
                    && item.Path.Take(property.Path.Length).SequenceEqual(property.Path, StringComparer.OrdinalIgnoreCase)
                    && (item.Kind == "GET" || item.Kind == "SET"))
                .ToDictionary(item => item.Path.Last(), item => item.Implementation ?? "\n", StringComparer.OrdinalIgnoreCase);
        }

        internal sealed class TreeObject
        {
            internal string Guid;
            internal string Type;
        }

        static Dictionary<string, TreeObject> TreeObjects(IDictionary<string, object> tree)
        {
            var result = new Dictionary<string, TreeObject>(StringComparer.OrdinalIgnoreCase);
            Visit(tree, new List<string>(), result);
            return result;
        }

        static void Visit(IDictionary<string, object> node, IList<string> path, IDictionary<string, TreeObject> result)
        {
            if (!node.TryGetValue("children", out var raw) || !(Items(raw) is var children && children.Any())) return;
            foreach (var child in children)
            {
                var name = Convert.ToString(child.ContainsKey("object_name") ? child["object_name"] : child["name"]);
                var type = child.ContainsKey("type") ? Convert.ToString(child["type"]) : null;
                // Keyed by view path: a project-level text list, library manager, ... sits under POUs/ there.
                var childPath = (path.Count == 0 && SnapshotReader.UnderPous(type) ? new[] { "POUs" } : path).Concat(new[] { name }).ToList();
                if (child.ContainsKey("guid")) result[string.Join("/", childPath)] = new TreeObject
                {
                    Guid = Convert.ToString(child["guid"]), Type = type,
                };
                Visit(child, childPath, result);
            }
        }
    }
}
