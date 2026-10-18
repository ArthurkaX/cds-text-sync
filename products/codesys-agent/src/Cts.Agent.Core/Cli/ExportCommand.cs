using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using System.Xml.Linq;
using Cts.Agent;
using Cts.Sync;

namespace Cts.Cli
{
    // The IDE supplies one snapshot; this process writes its view and advances
    // cts' private base without touching the user's git index.
    public static class ExportCommand
    {
        public static IDictionary<string, object> Execute(CliCall call)
        {
            try { return Run(call); }
            catch (Exception error) when (error is InvalidOperationException || error is IOException || error is ArgumentException)
            {
                throw new CliFailure("export", "refused", error.Message, "cts export --help", 1);
            }
        }

        static IDictionary<string, object> Run(CliCall call)
        {
            var started = Stopwatch.StartNew();
            var namedFolder = call.Options.Params.ContainsKey("sync_folder") ? Convert.ToString(call.Options.Params["sync_folder"]) : null;
            var projectFolder = call.Hello.SyncFolder;
            if (string.IsNullOrWhiteSpace(projectFolder))
            {
                var status = call.Call("project.status", new Dictionary<string, object>());
                projectFolder = status.ContainsKey("sync_folder") ? Convert.ToString(status["sync_folder"]) : null;
            }
            if (string.IsNullOrWhiteSpace(projectFolder)) throw new InvalidOperationException("no sync folder: cts set-sync-folder chooses one");
            var folder = string.IsNullOrWhiteSpace(namedFolder) ? projectFolder : namedFolder;
            folder = GitRepository.Repository(folder);
            if (!string.IsNullOrWhiteSpace(call.Hello.SyncFolder)
                && !string.Equals(Path.GetFullPath(folder).TrimEnd(Path.DirectorySeparatorChar), Path.GetFullPath(call.Hello.SyncFolder).TrimEnd(Path.DirectorySeparatorChar), Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal))
                throw new InvalidOperationException("--sync-folder does not match the open project's sync folder");

            var gitDir = GitRepository.Run(folder, "rev-parse --absolute-git-dir").Trim();
            var stampPath = Path.Combine(gitDir, "cts", "ide-stamp.json");
            var ideStamp = call.Hello.Data.TryGetValue("ide_stamp", out var stampValue) ? stampValue as string : null;
            var full = call.Options.Params.ContainsKey("full") || call.Options.Params.ContainsKey("force");
            var currentBase = GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}");
            var baseCommit = currentBase.ExitCode == 0 ? currentBase.Output.Trim() : null;
            if (!full && SyncBase.OtherProject(folder, call.Hello.ProjectPath) == null && StampMatches(call, stampPath, ideStamp, baseCommit))
                return AnswerFromGit(folder, baseCommit, started.Elapsed.TotalSeconds);
            var scratch = Path.Combine(gitDir, "cts", "tmp");
            Directory.CreateDirectory(scratch);
            var snapshot = Path.Combine(scratch, "export-" + Guid.NewGuid().ToString("N") + ".xml");
            var exportStarted = Stopwatch.StartNew();
            try
            {
                var exported = call.Call("project.export", new Dictionary<string, object> { { "path", snapshot } });
                exportStarted.Stop();
                var result = WriteToDisk(snapshot, folder, call.Hello.ProjectPath, call.Options.Params.ContainsKey("force"));
                var finalBase = GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}");
                if (result.BaseRecorded) SyncBase.SaveProject(folder, call.Hello.ProjectPath);
                // The stamp says the IDE is the base; a kept file the IDE may hold otherwise breaks that.
                if (result.BaseRecorded && result.PendingImport.Count == 0 && finalBase.ExitCode == 0 && !string.IsNullOrEmpty(ideStamp))
                    SyncBase.SaveStamp(stampPath, call.Hello.ProjectPath, ideStamp, finalBase.Output.Trim());
                else if (File.Exists(stampPath)) File.Delete(stampPath);
                var data = new Dictionary<string, object>
                {
                    { "size", new FileInfo(snapshot).Length }, { "sync_folder", folder }, { "text_sync", "success" },
                    { "ide", "exported" },
                    { "export_objects", exported.ContainsKey("objects") ? exported["objects"] : null },
                    { "timings", new Dictionary<string, object> { { "export_s", exportStarted.Elapsed.TotalSeconds }, { "total_s", started.Elapsed.TotalSeconds } } },
                };
                if (result.BaseRecorded) data["base"] = result.Base ?? "unchanged";
                if (result.KeptOrphans.Count > 0) data["kept"] = result.KeptOrphans.ToList();
                if (result.OwnerKept.Count > 0) data["owner_kept"] = result.OwnerKept;
                if (result.Ignored.Count > 0) data["ignored"] = result.Ignored.Count;
                if (result.PendingImport.Count > 0) data["pending_import"] = result.PendingImport;
                if (call.Options.Params.ContainsKey("conflict_tool") && !call.Options.Params.ContainsKey("force") && result.PendingImport.Count > 0)
                    Settle(call, folder, data, result.PendingImport);
                return data;
            }
            catch { if (File.Exists(stampPath)) File.Delete(stampPath); throw; }
            finally { if (File.Exists(snapshot)) File.Delete(snapshot); }
        }

        // --tool: an object the disk changed too is merged, or shown side by
        // side with the IDE's text on the right; what lands is the same in
        // the IDE and on disk.  A file still unlike the base stays kept.
        static void Settle(CliCall call, string folder, IDictionary<string, object> data, IList<string> pending)
        {
            try
            {
                var settled = ImportCommand.Settle(call);
                data["merged"] = settled["merged"];
                if (settled.TryGetValue("partial_reason", out var reason)) data["settle_note"] = reason;
            }
            catch (CliFailure refused) { data["settle_note"] = refused.Message; }
            var differs = SyncBase.Changed(folder, Relative(folder, ViewFolder.Of(folder)), "refs/cts/base");
            data["pending_import"] = pending.Where(differs.ContainsKey).ToList();
        }

        internal static bool StampMatches(CliCall call, string stampPath, string ideStamp, string baseCommit)
        {
            var saved = SyncBase.ReadStamp(stampPath);
            return !string.IsNullOrEmpty(ideStamp) && baseCommit != null && saved != null
                && saved.Project == call.Hello.ProjectPath && saved.Value == ideStamp && saved.Base == baseCommit;
        }

        public static Answer Build(IDictionary<string, object> data)
        {
            var kept = data.ContainsKey("kept") ? data["kept"] as IList<string> : null;
            var pending = data.ContainsKey("pending_import") ? data["pending_import"] as IList<string> : null;
            var answer = new Answer().Add("text_sync", data["text_sync"]);
            if (data.ContainsKey("size")) answer.Add("bytes", data["size"]);
            answer.Add("folder", data["sync_folder"]).Add("ide", data["ide"]);
            if ((kept?.Count ?? 0) + (pending?.Count ?? 0) > 0) answer.Add("kept", (kept?.Count ?? 0) + (pending?.Count ?? 0));
            var merged = data.TryGetValue("merged", out var mergedValue) ? ((System.Collections.IEnumerable)mergedValue).Cast<object>().ToList() : new List<object>();
            if (merged.Count > 0) answer.Add("merged", merged.Count);
            foreach (var name in merged) answer.Detail("merged " + name + " (changed on disk too; the IDE and the file now hold the result)");
            if (data.TryGetValue("settle_note", out var note)) answer.Detail(note);
            if (pending != null) foreach (var path in pending) answer.Detail("kept " + path + " (changed on disk since the last sync)");
            if (kept != null) foreach (var path in kept) answer.Detail("kept " + path + " (not the IDE's, new or changed on disk)");
            if (data.TryGetValue("owner_kept", out var ownerKept) && ((IList<string>)ownerKept).Count > 0) answer.Detail(ComparePlanner.OwnerKeptNote((IList<string>)ownerKept));
            if (data.TryGetValue("ignored", out var ignored)) answer.Detail(ViewIgnore.Note(Convert.ToInt32(ignored)));
            if (pending?.Count > 0 || kept?.Count > 0) answer.Detail("Next: cts import or cts sync carries them, cts export --force overwrites them");
            return answer;
        }

        static IDictionary<string, object> AnswerFromGit(string folder, string baseCommit, double elapsed)
        {
            var view = ViewFolder.Of(folder);
            var relative = Relative(folder, view);
            var prefix = relative == "." ? "" : relative + "/";
            var gitDir = GitRepository.Run(folder, "rev-parse --absolute-git-dir").Trim();
            var index = Path.Combine(gitDir, "cts", "base-index");
            var env = GitRepository.PrivateIndex(index);
            GitRepository.Run(folder, "read-tree " + baseCommit, env);
            var trackedRun = GitRun.In(folder, "diff --name-only -z --no-renames -- " + ProcessArgs.Quote(relative), env);
            var untrackedRun = GitRun.In(folder, "ls-files --others --full-name -z -- " + ProcessArgs.Quote(relative), env);
            if (trackedRun.ExitCode != 0) throw new InvalidOperationException(trackedRun.Message);
            if (untrackedRun.ExitCode != 0) throw new InvalidOperationException(untrackedRun.Message);
            var tracked = trackedRun.Output;
            var untracked = untrackedRun.Output;
            var pending = new List<string>();
            var kept = new List<string>();
            foreach (var path in tracked.Split('\0').Where(p => p.Length > 0))
            {
                var full = Path.Combine(folder, path.Replace('/', Path.DirectorySeparatorChar));
                if (!ViewExtension(full)) continue;
                pending.Add(relative == "." ? path : path.Substring(prefix.Length));
            }
            foreach (var path in untracked.Split('\0').Where(p => p.Length > 0))
            {
                var full = Path.Combine(folder, path.Replace('/', Path.DirectorySeparatorChar));
                if (!ViewExtension(full)) continue;
                kept.Add(relative == "." ? path : path.Substring(prefix.Length));
            }
            var ignored = ViewIgnore.Match(folder, relative, pending.Concat(kept));
            pending.RemoveAll(ignored.Contains);
            kept.RemoveAll(ignored.Contains);
            return new Dictionary<string, object>
            {
                { "sync_folder", folder }, { "text_sync", "success" }, { "ide", "unchanged" },
                { "pending_import", pending }, { "kept", kept },
                { "timings", new Dictionary<string, object> { { "export_s", 0 }, { "total_s", elapsed } } },
            };
        }

        static bool ViewExtension(string path) => new[] { ".st", ".xml", ".csv" }.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);

        public static ExportResult WriteToDisk(string snapshot, string folder, string project, bool force)
        {
            var view = ViewFolder.Of(folder);
            var relativeView = Relative(folder, view);
            SyncBase.CheckBase(folder);
            if (force) SyncBase.KeepOverwritten(folder, relativeView);
            var baseRef = GitRun.In(folder, "rev-parse -q --verify refs/cts/base^{commit}");
            var headRef = GitRun.In(folder, "rev-parse -q --verify HEAD^{commit}");
            // Another project file's base is no base for this one: only what
            // differs from the commit counts as an edit on disk.
            var hasBase = baseRef.ExitCode == 0 && SyncBase.OtherProject(folder, project) == null;
            var comparison = hasBase ? "refs/cts/base" : "HEAD";
            // Without a base or a commit there is nothing to tell an edit from
            // the IDE's file by: every file the export does not write stays.
            var comparable = hasBase || headRef.ExitCode == 0;
            var changedOnDisk = force || !comparable
                ? new Dictionary<string, byte[]>(StringComparer.OrdinalIgnoreCase) : SyncBase.Changed(folder, relativeView, comparison);
            var result = ViewExport.Write(snapshot, folder, SyncBase.LoadNatives(folder, project));
            // The IDE's stamp says nothing of a file the ignore rules left as it was.
            foreach (var native in result.Natives.Where(native => result.Ignored.Contains(native.Path)).ToList()) result.Natives.Remove(native);
            var against = hasBase ? baseRef : comparable ? headRef : null;
            if (against != null) result.OwnerKept = RestoreOwnerKept(folder, view, relativeView, against.Output.Trim(), result, changedOnDisk);
            var pending = RestorePending(view, changedOnDisk);
            RemoveUnchangedOrphans(view, result, force || comparable ? changedOnDisk : null, force, pending);
            result.PendingImport = pending;
            try { result.Base = SyncBase.Record(folder, relativeView, pending.Concat(result.KeptOrphans).Select(p => RepoPath(relativeView, p)).ToList()); }
            catch (InvalidOperationException) { result.BaseRecorded = false; }
            SyncBase.SaveNatives(folder, project, result.Natives.Where(native => !pending.Contains(native.Path, StringComparer.OrdinalIgnoreCase)
                && !result.OwnerKept.Contains(native.Path, StringComparer.OrdinalIgnoreCase)).ToList(), view);
            return result;
        }

        // What the owner keeps (ProjectInfo.OwnerKeeps) the IDE wrote unlike *commit* goes back to the
        // commit's file on a PC that is not the project's owner; one changed
        // on disk is RestorePending's.
        static List<string> RestoreOwnerKept(string folder, string view, string relativeView, string commit, ExportResult result, IDictionary<string, byte[]> changed)
        {
            var kept = new List<string>();
            var candidates = result.Natives.Select(native => native.Path).Where(path => !changed.ContainsKey(path))
                .Select(path => new { Path = path, Full = Path.Combine(view, path.Replace('/', Path.DirectorySeparatorChar)) })
                .Where(file => File.Exists(file.Full) && ProjectInfo.OwnerKeeps(folder, File.ReadAllBytes(file.Full))).ToList();
            var tree = relativeView == "." ? commit + "^{tree}" : commit + ":" + relativeView;
            if (candidates.Count == 0 || GitRun.In(folder, "cat-file -e " + ProcessArgs.Quote(tree)).ExitCode != 0) return kept;
            using (var committed = new GitTreeViewFiles(folder, commit, relativeView))
                foreach (var file in candidates)
                {
                    var before = committed.Read(file.Path);
                    if (before == null || SameContent(file.Path, before, File.ReadAllBytes(file.Full))) continue;
                    File.WriteAllBytes(file.Full, before);
                    kept.Add(file.Path);
                }
            return kept;
        }

        internal static string Relative(string root, string path)
        {
            var rel = Uri.UnescapeDataString(new Uri(Append(root)).MakeRelativeUri(new Uri(Append(path))).ToString());
            rel = rel.TrimEnd('/').Replace('\\', '/');
            return rel.Length == 0 ? "." : rel;
        }
        static string RepoPath(string view, string path) => view == "." ? path : view + "/" + path;
        static string Append(string path) => Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;

        static List<string> RestorePending(string view, IDictionary<string, byte[]> changed)
        {
            var pending = new List<string>();
            foreach (var item in changed)
            {
                var full = Path.Combine(view, item.Key.Replace('/', Path.DirectorySeparatorChar));
                if (item.Value == null)
                {
                    if (File.Exists(full)) File.Delete(full);
                    pending.Add(item.Key);
                }
                else if (File.Exists(full) && !SameContent(item.Key, item.Value, File.ReadAllBytes(full)))
                {
                    File.WriteAllBytes(full, item.Value);
                    pending.Add(item.Key);
                }
            }
            return pending;
        }

        internal static bool SameContent(string path, byte[] previous, byte[] current)
        {
            return string.Equals(ContentKey(path, previous), ContentKey(path, current), StringComparison.Ordinal);
        }

        internal static string ContentKey(string path, byte[] bytes)
        {
            if (bytes == null) return null;
            string text;
            try { text = new UTF8Encoding(false, true).GetString(bytes).TrimStart('\uFEFF'); }
            catch (DecoderFallbackException) { return "bytes:" + Hash(bytes); }
            var extension = Path.GetExtension(path).ToLowerInvariant();
            if (extension == ".st" || extension == ".csv") return "text:" + Hash(Encoding.UTF8.GetBytes(text.Replace("\r\n", "\n")));
            if (extension != ".xml") return "bytes:" + Hash(bytes);
            try { return "xml:" + Hash(Encoding.UTF8.GetBytes(NormalizeXml(XElement.Parse(text)).ToString(SaveOptions.DisableFormatting))); }
            catch (System.Xml.XmlException) { return "text:" + Hash(Encoding.UTF8.GetBytes(text)); }
        }

        static string Hash(byte[] bytes)
        {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        static XElement NormalizeXml(XElement element)
        {
            var copy = new XElement(element);
            NormalizeElement(copy, true);
            return copy;
        }

        static readonly HashSet<string> IgnoredXmlNames = new HashSet<string>(new[] {
            "Timestamp", "UniqueIdGenerator", "GuidInit", "GuidReInit", "GuidExitX",
            "GeneratedLMMDescriptions", "PositionId", "EditorPositionId", "PlaceholderResolution"
        }, StringComparer.Ordinal);

        static void NormalizeElement(XElement element, bool root)
        {
            foreach (var child in element.Elements().ToList())
            {
                var name = (string)child.Attribute("Name");
                if ((root && name == "Index") || IgnoredXmlNames.Contains(name) || DerivedProperty(element, child)) { child.Remove(); continue; }
                NormalizeElement(child, false);
            }
            foreach (var node in element.Nodes().OfType<XText>().ToList())
            {
                if (node is XCData) continue;
                var trimmed = node.Value.Trim();
                if (trimmed.Length == 0) { node.Remove(); continue; }
                node.Value = Regex.Replace(trimmed, @"VisuStyleDefaultImages_[0-9a-fA-F-]{36}", "VisuStyleDefaultImages_<session>");
            }
            if (!element.Nodes().Any()) element.RemoveNodes();   // <x></x> and <x /> are one empty element
            if (element.Name.LocalName == "Dictionary")
                Reorder(element, element.Elements().OrderBy(e => e.Elements().FirstOrDefault(x => (string)x.Attribute("Name") == "Key")?.ToString(SaveOptions.DisableFormatting) ?? "", StringComparer.Ordinal));
            if ((string)element.Attribute("Name") == "VisualElemMemberList" && element.Elements().All(e => e.Elements().Any(x => (string)x.Attribute("Name") == "Id")))
                Reorder(element, element.Elements().OrderBy(e => e.Elements().First(x => (string)x.Attribute("Name") == "Id").Value.Trim(), StringComparer.Ordinal));
        }

        static bool DerivedProperty(XElement parent, XElement entry)
        {
            if ((string)parent.Attribute("Name") != "Properties") return false;
            var holders = entry.Elements().FirstOrDefault(e => e.Name.LocalName == "Value")?.Elements().ToList();
            return holders != null && holders.Count == 1 && holders[0].Elements().Any()
                && holders[0].Elements().All(e => (string)e.Attribute("Name") == "PlaceholderResolution")
                || ProjectInfo.IsSourceEntry(entry);
        }

        static void Reorder(XElement parent, IEnumerable<XElement> ordered)
        {
            var items = ordered.ToList();
            parent.RemoveNodes();
            foreach (var item in items) parent.Add(item);
        }

        // An orphan (a view file the IDE no longer has) goes when it is as the
        // base left it, or with --force; an edited or new one stays. *changed*
        // is null when there is no base to judge by: then every orphan stays.
        static void RemoveUnchangedOrphans(string view, ExportResult result, IDictionary<string, byte[]> changed, bool force, IList<string> pending)
        {
            foreach (var path in result.KeptOrphans.ToList())
            {
                if (pending.Contains(path, StringComparer.OrdinalIgnoreCase)) continue;
                var full = Path.Combine(view, path.Replace('/', Path.DirectorySeparatorChar));
                if (!force && (changed == null || changed.ContainsKey(path))) continue;
                if (File.Exists(full)) File.Delete(full);
                result.KeptOrphans.Remove(path);
            }
        }

    }
}
