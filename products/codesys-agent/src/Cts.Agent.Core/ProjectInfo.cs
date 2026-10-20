// The project's sync folder.  A .project file is copied, mailed and opened
// from anywhere, so it carries no path: only its id, `cts-project-id` in
// Project Information, the same in every copy.  The sync folder's
// cds-text-sync.json names the id it belongs to (`project_id`), and where it
// is on this machine is the user's: %LOCALAPPDATA%\cds-text-sync\projects.json,
// written by `cts set-sync-folder`.  The folder is the sync root the project
// file lies in when that root is the project's, else the one registered for
// its id while it still names the id.
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Xml.Linq;

namespace Cts.Agent
{
    public sealed class KnownProject
    {
        public string Id { get; set; }
        public string Name { get; set; }
        public string Folder { get; set; }
        public bool Owner { get; set; }
    }

    public static class ProjectInfo
    {
        public const string IdProperty = "cts-project-id";
        // The commit the IDE's code came from, "<branch>@<commit>[ +uncommitted] · <when>":
        // for a person who finds the project file elsewhere.  Only a label, never read back by a sync.
        public const string SourceProperty = "cts-source";
        const string SourceWhen = " · ";

        // The label *source* written at *when*, as the property holds it.
        public static string Source(string source, string when) { return source + SourceWhen + when; }

        // Whether *entry* of the Properties dictionary is the project's id or
        // its `cts-source` label: both belong to the .project, not to the view.
        // The view and its compare leave them out, so writing them changes
        // nothing on disk, and a copy's import cannot carry the original's id.
        internal static bool IsOwnEntry(XElement entry)
        {
            var key = entry.Elements().FirstOrDefault(e => e.Name.LocalName == "Key");
            return key != null && IsOwnKey(key.Value.Trim());
        }
        internal static bool IsOwnKey(string key) => key == SourceProperty || key == IdProperty;

        // Whether *xml*, a view file the IDE wrote, is a Library Manager or the
        // Project Settings, which stay off the disk of *folder*: a team
        // project's libraries and environment are its owner's, and another
        // PC's CODESYS resolves its own system libraries and, told to "Set All
        // to Newest", writes its compiler version.  The owner, and a project
        // without an id, write them as any other object.
        internal static bool OwnerKeeps(string folder, byte[] xml)
        {
            if (xml == null) return false;
            var text = Encoding.UTF8.GetString(xml);
            if (!OwnersTypes.Any(type => text.IndexOf(">" + type + "</Single>", StringComparison.OrdinalIgnoreCase) >= 0)) return false;
            var id = IdOf(folder);
            return id != "" && !IsOwner(id);
        }
        // Library Manager, Project Settings.
        static readonly string[] OwnersTypes = { "adb5cb65-8e1d-4a00-b70a-375ea27582f3", "8753fe6f-4a22-4320-8103-e553c4fc8e04" };

        // The label of a `cts-source` *value*, without when it was written.
        public static string SourceOf(string value)
        {
            var at = (value ?? "").LastIndexOf(SourceWhen, StringComparison.Ordinal);
            return at < 0 ? value ?? "" : value.Substring(0, at);
        }
        const string SettingsFile = "cds-text-sync.json";

        public static string RegistryPath()
        {
            var root = Path.DirectorySeparatorChar == '\\' ? Environment.GetEnvironmentVariable("LOCALAPPDATA") : null;
            if (root == null || root == "") root = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            if (root == "") root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share");
            if (Path.DirectorySeparatorChar != '\\')
            {
                var dataHome = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
                if (!string.IsNullOrEmpty(dataHome)) root = dataHome;
            }
            return Path.Combine(root,
                "cds-text-sync", "projects.json");
        }

        public static IList<KnownProject> Known(string registry = null)
        {
            var projects = Field(Read(registry ?? RegistryPath()), "projects") as IDictionary<string, object>;
            if (projects == null) return new List<KnownProject>();
            return projects.Select(pair =>
            {
                var entry = pair.Value as IDictionary<string, object>;
                var folder = Field(entry, "folder") as string ?? "";
                return new KnownProject
                {
                    Id = pair.Key,
                    Name = Field(entry, "name") as string ?? "",
                    Folder = folder,
                    Owner = Equals(Field(entry, "owner"), true),
                };
            }).Where(project => Directory.Exists(project.Folder))
                .OrderBy(project => project.Name, StringComparer.OrdinalIgnoreCase).ToList();
        }

        public static string ProjectFile(string folder)
        {
            string root;
            try { root = GitRepository.Repository(folder); }
            catch (InvalidOperationException) { return ""; }
            var run = GitRun.In(root, "ls-files -z -- \"*.project\"");
            if (run.ExitCode != 0) return "";
            var files = run.Output.Split('\0').Where(path => path.Length > 0).ToList();
            return files.Count == 1 ? Path.GetFullPath(Path.Combine(root, files[0])) : "";
        }

        public static string ProjectIdOf(string folder) { return IdOf(folder); }

        public static string NewProjectId() { return Guid.NewGuid().ToString().ToLowerInvariant(); }

        public static string RegistryFolder(string id, string registry = null)
        {
            return Field(Entry(id, registry ?? RegistryPath()), "folder") as string ?? "";
        }

        public static bool IsOwner(string id, string registry = null)
        {
            return Equals(Field(Entry(id, registry ?? RegistryPath()), "owner"), true);
        }

        public static string ChooseId(string id, string folder, bool newId = false, string registry = null)
        {
            var owner = IdOf(folder);
            if (owner != "" && newId && !CopiedFolder(owner, id, folder, registry))
                throw new InvalidOperationException(folder + " already belongs to project " + owner + ": a copy of the project needs a folder of its own");
            if (owner != "" && newId) return NewProjectId();
            if (owner != "" && id != "" && owner != id) throw new InvalidOperationException(folder + " belongs to another project (" + owner + "; this one is " + id + ")");
            if (owner != "") return owner;
            if (newId || id == "") return NewProjectId();
            var other = RegistryFolder(id, registry);
            if (other != "" && Different(other, folder) && IdOf(other) == id)
                throw new InvalidOperationException("this project's sync folder is " + other + ". Choose it, or pass --new-id when the project is a copy made for another plant and gets a repository of its own");
            return id;
        }

        // Whether *folder*, naming project *owner*, is a copy of that project's
        // folder: *owner* is the open project's *id*, and this machine has the
        // project's own folder elsewhere, still naming it.
        static bool CopiedFolder(string owner, string id, string folder, string registry)
        {
            var original = RegistryFolder(owner, registry);
            return owner == id && original != "" && Different(original, folder) && IdOf(original) == owner;
        }

        // *owner* null keeps what this machine was.
        public static void Record(string id, string folder, string name, bool? owner, string registry = null)
        {
            var path = registry ?? RegistryPath();
            var data = Read(path) as IDictionary<string, object> ?? new Dictionary<string, object>();
            var projects = Field(data, "projects") as IDictionary<string, object> ?? new Dictionary<string, object>();
            var entry = new Dictionary<string, object> { { "folder", Path.GetFullPath(folder) }, { "name", name ?? "" } };
            if (owner ?? IsOwner(id, path)) entry["owner"] = true;
            projects[id] = entry;
            data["version"] = 1L;
            data["projects"] = projects;
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllText(path, Json.Pretty(data) + "\n", new UTF8Encoding(false));
        }

        public static bool Claim(string folder, string id)
        {
            var path = Path.Combine(folder, SettingsFile);
            if (ProjectIdOf(folder) == id) return false;
            var data = Read(path) as IDictionary<string, object> ?? new Dictionary<string, object>();
            data["project_id"] = id;
            SaveSettings(folder, Json.Pretty(data) + "\n");
            return true;
        }

        static bool Different(string a, string b)
        {
            var x = Path.GetFullPath(a).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            var y = Path.GetFullPath(b).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
            return !string.Equals(x, y, Path.DirectorySeparatorChar == '\\' ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal);
        }

        // `project_id`, `sync_folder` when this machine has it, and `owner`
        // when this machine publishes the project file (`cts commit --publish`).
        public static void AddSyncFolder(IDictionary<string, object> result, object id, string projectPath, string registry)
        {
            var text = id == null ? "" : Convert.ToString(id);
            if (text == "") return;
            result["project_id"] = text;
            var folder = SyncFolder(text, projectPath, registry);
            if (folder != "") result["sync_folder"] = folder;
            if (Equals(Field(Entry(text, registry), "owner"), true)) result["owner"] = true;
        }

        // The sync folder of project *id* whose file is *projectPath*, given
        // the registry file *registry*; "" when this machine has none.
        public static string SyncFolder(string id, string projectPath, string registry)
        {
            if (string.IsNullOrEmpty(id)) return "";
            var root = EnclosingRoot(projectPath);
            if (root != "" && IdOf(root) == id) return root;
            var folder = Registered(id, registry);
            return folder != "" && IdOf(folder) == id ? folder : "";
        }

        // The text of *folder*'s cds-text-sync.json, "" without one; a file
        // that cannot be read throws.
        public static string Settings(string folder)
        {
            var path = Path.Combine(folder, SettingsFile);
            return File.Exists(path) ? File.ReadAllText(path) : "";
        }

        // Writes *text* as a folder's cds-text-sync.json the way cts does:
        // UTF-8 without a BOM, LF line ends on every host.
        public static void SaveSettings(string folder, string text)
        {
            File.WriteAllText(Path.Combine(folder, SettingsFile), text, new UTF8Encoding(false));
        }

        // The `project_id` a folder's cds-text-sync.json names, "" without one.
        public static string IdOf(string folder)
        {
            return Field(Read(Path.Combine(folder, SettingsFile)), "project_id") as string ?? "";
        }

        static string Registered(string id, string registry)
        {
            return Field(Entry(id, registry), "folder") as string ?? "";
        }

        static object Entry(string id, string registry)
        {
            return Field(Field(Read(registry), "projects"), id);
        }

        // The sync folder around *workFolder* when it is not *syncFolder*, the
        // one a command works on; "" when there is none or it is that one.
        public static string OtherSyncFolder(string workFolder, string syncFolder)
        {
            if (string.IsNullOrEmpty(workFolder) || string.IsNullOrEmpty(syncFolder) || !Path.IsPathRooted(workFolder)) return "";
            var here = EnclosingRoot(Path.Combine(workFolder, SettingsFile));
            return here != "" && Different(here, syncFolder) ? here : "";
        }

        // The nearest folder at or above the project file's holding
        // cds-text-sync.json, "" for a project not saved or outside one.
        static string EnclosingRoot(string projectPath)
        {
            if (string.IsNullOrEmpty(projectPath) || !Path.IsPathRooted(projectPath)) return "";
            for (var dir = Path.GetDirectoryName(Path.GetFullPath(projectPath)); !string.IsNullOrEmpty(dir); dir = Path.GetDirectoryName(dir))
                if (File.Exists(Path.Combine(dir, SettingsFile))) return dir;
            return "";
        }

        static object Read(string path)
        {
            try { return File.Exists(path) ? Json.Parse(File.ReadAllText(path)) : null; }
            catch (IOException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
            catch (JsonException) { return null; }
        }

        static object Field(object json, string key)
        {
            var map = json as IDictionary<string, object>;
            return map != null && map.ContainsKey(key) ? map[key] : null;
        }

        // The folder `cts set-sync-folder` offers a project without one: the
        // sync root its file lies in, else the git repository it lies in (a
        // folder inside a repository is never one: the sync folder is a
        // repository's root), else a `<project>-cts` folder beside the file.
        // "" for a project not saved.
        public static string Suggested(string projectPath)
        {
            if (string.IsNullOrEmpty(projectPath) || !Path.IsPathRooted(projectPath)) return "";
            var root = EnclosingRoot(projectPath);
            if (root != "") return root;
            for (var dir = Path.GetDirectoryName(Path.GetFullPath(projectPath)); !string.IsNullOrEmpty(dir); dir = Path.GetDirectoryName(dir))
                if (Directory.Exists(Path.Combine(dir, ".git")) || File.Exists(Path.Combine(dir, ".git"))) return dir;
            return Path.Combine(Path.GetDirectoryName(projectPath), FolderName(Path.GetFileNameWithoutExtension(projectPath)));
        }

        // `<project>-cts`: what Windows forbids in a name is dropped and a
        // blank becomes "-".
        public static string FolderName(string project)
        {
            var name = new string(project.Where(c => c >= ' ' && "<>:\"/\\|?*".IndexOf(c) < 0)
                .Select(c => char.IsWhiteSpace(c) ? '-' : c).ToArray());
            while (name.Contains("--")) name = name.Replace("--", "-");
            name = name.Trim(' ', '.', '-');
            return name.Length > 0 ? name + "-cts" : "cts";
        }

        // *path* as an absolute folder: a relative one is anchored to the
        // saved project file's own directory, never to whatever directory
        // the caller happens to run in.
        public static string Anchor(string path, string projectPath)
        {
            var text = (path ?? "").Trim();
            if (text.IndexOf('\0') >= 0) throw new ProtocolException(ErrorCodes.BadParams, "Sync folder path contains a null byte");
            if (Path.IsPathRooted(text)) return Path.GetFullPath(text);
            if (string.IsNullOrEmpty(projectPath) || !Path.IsPathRooted(projectPath))
                throw new ProtocolException(ErrorCodes.BadParams,
                    "Cannot resolve a relative sync folder: the project has not been saved. Save it first, or give an absolute path.");
            return Path.GetFullPath(Path.Combine(Path.GetDirectoryName(projectPath), text));
        }
    }
}
