using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    internal static partial class ImportCommand
    {
        // The planner's text lists, alarm groups and objects kept as XML.
        sealed partial class ImportPlanner
        {
            // Each changed text list (.csv): the rows to remove and insert, read against the IDE's fields;
            // one both sides changed carries their rows merged, or is a conflict --take settles.
            IDictionary<string, object> PlanTextLists()
            {
                _work.CsvPlans = new List<TextListPlan>();
                _work.CsvGone = new List<string>();
                _work.FieldReadBack = new List<IDictionary<string, object>>();
                // A list only the IDE changed goes to disk after the import.
                foreach (var record in _work.CsvRecords.Where(record => record.Category != "ide_changed"))
                {
                    var path = record.Path;
                    // A new object's .csv goes to the IDE with its .xml (a text list's
                    // rows put back), a deleted one's with it.
                    var xml = Path.ChangeExtension(path, ".xml");
                    if ((record.Category == "added" || record.Category == "deleted") && _work.NativeRecords.Any(native => native.Category == record.Category
                            && string.Equals(native.Path, xml, StringComparison.OrdinalIgnoreCase)))
                    {
                        var header = record.Category == "added" ? Csv.Parse(File.ReadAllText(Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar)))).FirstOrDefault() : null;
                        if (record.Category == "added" && TextListRows.IsTextList(NativeMetaValue(File.ReadAllText(Path.Combine(_work.View, xml.Replace('/', Path.DirectorySeparatorChar))), "TypeGuid"))
                            && (header == null || !header.Contains("TextID")))
                            return Refused(_call, _work.Data, "added " + path + ": the csv has no TextID column");
                        if (record.Category == "deleted") _work.CsvGone.Add(path);
                        continue;
                    }
                    // A text list whose .xml is replaced too gets its rows with it, in the
                    // .xml's languages: the IDE's languages are about to change.
                    if (record.Category == "modified" && !record.IdeChanged && _work.NativeRecords.Any(native => native.Category == "modified" && !native.IdeChanged
                            && string.Equals(native.Path, xml, StringComparison.OrdinalIgnoreCase))
                        && TextListRows.IsTextList(NativeMetaValue(File.ReadAllText(Path.Combine(_work.View, xml.Replace('/', Path.DirectorySeparatorChar))), "TypeGuid")))
                        continue;
                    var alarms = record.Category == "modified" ? PlanAlarmGroup(record, path) : null;
                    if (alarms != null)
                    {
                        // Both sides' messages are not merged: the import is refused, a settling sync leaves the group.
                        if (record.IdeChanged && !_call.Options.Params.ContainsKey("force"))
                        {
                            if (_work.Settling) continue;
                            return Refused(_call, _work.Data, "changed in the IDE since the last sync: " + record.Name + " (cts import --force)");
                        }
                        if (alarms.Error != null) return Refused(_call, _work.Data, path + ": " + alarms.Error);
                        if (alarms.DiskLeaves.Count > 0) _work.CsvPlans.Add(alarms);
                        continue;
                    }
                    var key = Path.ChangeExtension(path, null).Replace('\\', '/');
                    if (record.Category != "modified" || !_work.IdeNodes.TryGetValue(key, out var node)
                        || !new[] { "textlist", "global_text_list" }.Contains(TypeKinds.All.Kind(node.Type), StringComparer.OrdinalIgnoreCase))
                        return Refused(_call, _work.Data, record.Category + " " + path + ": not a changed text list");
                    if (!File.Exists(Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar))))
                        return Refused(_call, _work.Data, "cannot read " + path);
                    if (record.IdeChanged && record.Merged == null && !_call.Options.Params.ContainsKey("force"))
                    {
                        record.Guid = node.Guid; record.HasGuid = true;
                        var take = Take(record);
                        if (take == null) { FileConflict(record); continue; }
                        if (take == "ide") { _work.NativeIdeTaken.Add(record); continue; }
                        // The disk's rows go in; the IDE's list is kept on refs/cts/overwritten first.
                        _work.ForceRecords.Add(record);
                    }
                    IDictionary<string, object> fieldsReply;
                    try { fieldsReply = _call.Call("objects.fields", new Dictionary<string, object> { { "guid", node.Guid } }); }
                    catch (CliFailure error) when (error.Declined)
                    {
                        _work.FieldReadBack.Add(new Dictionary<string, object> { { "guid", node.Guid }, { "name", record.Name }, { "path", path }, { "error", error.Message } });
                        continue;
                    }
                    var leaves = FlattenFields(fieldsReply.TryGetValue("fields", out var rawFields) ? rawFields : null);
                    var csvPlan = PlanTextList(record.Merged != null ? new System.Text.UTF8Encoding(false).GetString(record.Merged)
                        : File.ReadAllText(Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar))), leaves);
                    if (csvPlan.Error != null) return Refused(_call, _work.Data, csvPlan.Error);
                    csvPlan.Merged = record.Merged;
                    if (record.Merged != null) _work.Merged.Add(record.Name);
                    csvPlan.Guid = node.Guid;
                    csvPlan.Path = path;
                    csvPlan.Name = Convert.ToString(fieldsReply.ContainsKey("name") ? fieldsReply["name"] : record.Name);
                    if (csvPlan.Removes.Count == 0 && csvPlan.Inserts.Count == 0 && !csvPlan.DiskLeaves.Any(pair =>
                        pair.Value != null && !string.Equals(Convert.ToString(leaves.ContainsKey(pair.Key) ? leaves[pair.Key] : null), pair.Value, StringComparison.Ordinal)))
                        csvPlan.UnappliedError = "the csv differs outside the texts the agent carries";
                    _work.CsvPlans.Add(csvPlan);
                }
                return null;
            }

            // The messages a changed alarm group's .csv (its .xml beside it
            // names the group and its message list) carries; null for a csv of
            // another object.
            TextListPlan PlanAlarmGroup(CompareRecord record, string path)
            {
                var full = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                var xml = Path.ChangeExtension(full, ".xml");
                if (!File.Exists(xml) || !File.Exists(full)) return null;
                var group = XDocument.Parse(File.ReadAllText(xml).TrimStart('\uFEFF')).Root;
                var messages = ViewExport.AlarmMessagesGuid(group);
                if (messages == null || group.Descendants().All(element => (string)element.Attribute("Name") != "Alarms")) return null;
                var reply = _call.Call("objects.fields", new Dictionary<string, object> { { "guid", messages } });
                var plan = PlanAlarmMessages(File.ReadAllText(full), _work.IdeFiles != null && _work.IdeFiles.TryGetValue(path, out var ide) ? ide : null,
                    FlattenFields(reply.TryGetValue("fields", out var fields) ? fields : null));
                plan.Guid = messages;
                plan.Group = NativeMetaValue(File.ReadAllText(xml), "Guid");
                plan.Path = path;
                plan.Name = record.Name;
                plan.XmlPath = Directory.GetFiles(Path.GetDirectoryName(xml), "*.xml")
                    .Where(file => string.Equals(GuidKey(NativeMetaValue(File.ReadAllText(file), "Guid") ?? ""), messages, StringComparison.Ordinal))
                    .Select(file => ExportCommand.Relative(_work.View, file)).FirstOrDefault();
                return plan;
            }

            // Each native (.xml) record: delete, import, replace or refuse; one both sides changed in the same element is a conflict.
            IDictionary<string, object> PlanNatives()
            {
                _work.NativeDeletes = new List<CompareRecord>();
                _work.NativeGone = new List<CompareRecord>();
                _work.NativeImports = new List<CompareRecord>();
                _work.NativeReplaces = new List<CompareRecord>();
                foreach (var record in _work.NativeRecords)
                {
                    var path = record.Path;
                    var fullPath = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                    if (!File.Exists(fullPath) && (record.Category == "ide_changed" || record.Category == "modified"))
                    {
                        var missingKey = NativeKey(path);
                        if (!_work.IdeByPath.TryGetValue(missingKey, out var missingGuid)) { _work.NativeGone.Add(record); continue; }
                        if (!record.HasGuid) { record.Guid = missingGuid; record.HasGuid = true; }
                        if (_call.Options.Params.ContainsKey("force")) { _work.NativeDeletes.Add(record); continue; }
                        // ide_changed without a file is an object the IDE added: import leaves it, sync writes it to disk.
                        // A modified one was deleted on disk and changed in the IDE: sync reports it with the conflicts below.
                        if (record.Category == "ide_changed" || _work.Syncing) continue;
                        return Refused(_call, _work.Data, path + ": deleted on disk, changed in the IDE; cts import --force deletes it, cts sync reports it as a conflict");
                    }
                    var key = NativeKey(path);
                    var textPath = Path.ChangeExtension(path, ".st");
                    var pairedDelete = _work.StRecords.Any(st => st.Category == "deleted"
                        && string.Equals(st.Path, textPath, StringComparison.OrdinalIgnoreCase));
                    // Settings the IDE changed, sync writes or removes after the import.
                    if (!path.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase) && BesideText(path, _work.View)
                        && !(record.Category == "ide_changed" && !_call.Options.Params.ContainsKey("force")))
                    {
                        return Refused(_call, _work.Data, record.Category + " " + path + ": the settings of a text object");
                    }
                    if (!path.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase) && pairedDelete
                        && record.Category == "deleted") continue;
                    if (record.Category == "modified" || record.Category == "added")
                    {
                        var content = File.ReadAllText(fullPath);
                        var invalid = NativeEntryProblem(content);
                        if (invalid != null) return Refused(_call, _work.Data, path + ": " + invalid);
                    }
                    var found = _work.IdeByPath.TryGetValue(key, out var guid);
                    if (record.Category == "deleted")
                    {
                        if (!found) { _work.NativeGone.Add(record); continue; }
                        if (path.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase))
                            return Refused(_call, _work.Data, "removed " + path + ": a container goes with the objects below it");
                        if (_work.IdeByPath.Keys.Any(candidate => candidate.StartsWith(key + "/", StringComparison.OrdinalIgnoreCase)
                            && !string.Equals(_work.IdeNodes[candidate].Type, "413e2a7d-adb1-4d2c-be29-6ae6e4fab820", StringComparison.OrdinalIgnoreCase)))
                            return Refused(_call, _work.Data, "removed " + path + ": objects below it in the IDE");
                        record.Guid = guid; record.HasGuid = true;
                        _work.NativeDeletes.Add(record);
                    }
                    else if (record.Category == "added")
                    {
                        if (found)
                        {
                            record.Guid = guid; record.HasGuid = true;
                            _work.NativeReplaces.Add(record);
                        }
                        else
                        {
                            if (path.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase))
                                return Refused(_call, _work.Data, "added " + path + ": a new container; make it in the IDE");
                            var full = Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar));
                            if (!File.Exists(full)) return Refused(_call, _work.Data, path + ": deleted on disk, changed in the IDE; cts import --force deletes it, cts sync keeps the IDE's");
                            var xml = File.ReadAllText(full);
                            if (string.Equals((NativeMetaValue(xml, "TypeGuid") ?? "").Trim().Trim('{', '}'), ObjectKinds.FolderType, StringComparison.OrdinalIgnoreCase))
                                return Refused(_call, _work.Data, "added " + path + ": a new container; make it in the IDE");
                            var name = NativeMetaValue(xml, "Name");
                            if (!string.Equals(name, Path.GetFileName(key), StringComparison.OrdinalIgnoreCase))
                                return Refused(_call, _work.Data, "added " + path + ": its object is named '" + name + "', not as the file");
                            var parent = NativeParentKey(key, xml);
                            if (parent.Length == 0) record.ParentGuid = "";
                            else if (_work.IdeByPath.TryGetValue(parent, out var parentGuid)) record.ParentGuid = parentGuid;
                            else if (_work.FolderRecords.Any(container => container.Category == "added"
                                && string.Equals(FolderKey(container.Path), parent, StringComparison.OrdinalIgnoreCase)))
                                record.ParentKey = parent;
                            else return Refused(_call, _work.Data, "added " + path + ": none of its folders " + (Path.GetDirectoryName(path) ?? "").Replace('\\', '/') + " is in the IDE");
                            _work.NativeImports.Add(record);
                        }
                    }
                    else if (record.Category == "modified")
                    {
                        if (!found) return Refused(_call, _work.Data, path + ": not in the IDE");
                        record.Guid = guid; record.HasGuid = true;
                        _work.NativeReplaces.Add(record);
                        if (record.Merged != null) _work.Merged.Add(record.Name);
                    }
                    else if (record.Category == "ide_changed" && _work.HasBase && _call.Options.Params.ContainsKey("force")
                        && !path.EndsWith(".cds-object.xml", StringComparison.OrdinalIgnoreCase))
                    {
                        // --force: the file's object goes back into the IDE as the disk holds it.
                        if (!found) return Refused(_call, _work.Data, path + ": deleted in the IDE; cts sync removes the file");
                        record.Guid = guid; record.HasGuid = true;
                        if (File.Exists(Path.Combine(_work.View, path.Replace('/', Path.DirectorySeparatorChar)))) _work.NativeReplaces.Add(record);
                        else _work.NativeDeletes.Add(record);
                    }
                }
                // --take: a disk side goes into the IDE as the other replaces do, after the IDE's
                // went on refs/cts/overwritten; an IDE side is written to its file.  The rest stays.
                if (!_call.Options.Params.ContainsKey("force"))
                    foreach (var record in _work.NativeReplaces.Where(record => record.IdeChanged && record.Merged == null).ToList())
                    {
                        var take = Take(record);
                        if (take == "disk") { _work.ForceRecords.Add(record); continue; }
                        _work.NativeReplaces.Remove(record);
                        if (take == "ide") _work.NativeIdeTaken.Add(record);
                        else FileConflict(record);
                    }
                return null;
            }

            // The IDE path of the object a native file holds: a member of a POU
            // kept as XML lies beside it as Owner.Member.xml, the object
            // Owner/Member, which the IDE has or whose owner it has.
            string NativeKey(string path)
            {
                if (path.EndsWith("/.cds-object.xml", StringComparison.OrdinalIgnoreCase)) return FolderKey(path);
                var key = Path.ChangeExtension(path, null).Replace('\\', '/');
                var directory = ParentKey(key);
                var dotted = (directory.Length == 0 ? "" : directory + "/") + Path.GetFileName(key).Replace('.', '/');
                return _work.IdeByPath.ContainsKey(key) || dotted == key || !_work.IdeByPath.ContainsKey(dotted) && !_work.IdeByPath.ContainsKey(ParentKey(dotted)) ? key : dotted;
            }
        }
    }
}
