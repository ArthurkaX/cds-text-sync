using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Cts.Agent;
using Cts.Docs;

namespace Cts.Cli
{
    // `cts install`: the CODESYS side of cts. Into a ScriptDir's cds-text-sync
    // folder go the menu entry (a stub that loads the agent) and the agent
    // with cts.exe beside it; beside the ScriptDir, the same entry as a
    // Script Command a toolbar button can run. The CODESYS script engine lists
    // every .py anywhere under ScriptDir, so nothing else goes there.
    public static class InstallCommand
    {
        const string Verb = "install";
        const string Folder = "cds-text-sync";
        const string Stub = Folder + ".py";
        const string Icon = Folder + ".ico";
        const string AgentFolder = "agent";
        internal const string Marker = "# cds-text-sync generated menu stub - DO NOT EDIT";
        internal const string Description = "Start the cts agent and open the quick window";
        //: The files the agent folder holds: cts.exe goes with the agent, so
        //: the quick window's commands run the same build.
        static readonly string[] AgentFiles = { "Cts.Agent.Core.dll", "Cts.Agent.dll", "cts.exe", "cts.exe.config" };
        //: The command CODESYS gives the n-th Script Commands entry (ExecuteScript1n),
        //: which a toolbar item names.
        static readonly string[] CommandGuids =
        {
            "ea88ff69-1e93-446d-a4db-58718b3f507c", "ac633e0f-4b35-4ba7-9397-c17dae2fab17",
            "b0b9ca45-b3a2-43be-aaba-ffe94dbcb67f", "0e6ddc68-3c42-41b6-9d09-74bd95b46912",
            "a49611f9-5849-4207-8b30-42edb411fc8c", "cf8f02cd-5116-4d79-be09-f3421e2a7157",
            "0a0efe72-fbc8-4100-9355-aab9e39275cf", "e59343ce-24ea-4fe9-b6b2-d4ac4afbe2f3",
            "ebbf03a2-9997-4cc1-93a5-3601cf2995e0", "e27ecef9-c8c6-47a5-85ed-00ea1d10a2cf",
            "0d29f393-3fa0-4bb2-9742-1144a3f12ad8", "222e3ddc-2e90-413b-93ff-eb154a91b26d",
            "50ebb99c-6df0-4ae6-8006-5415f0a1b5fc", "06e8d918-19cb-471a-9e61-5e852e108cb7",
            "0cbc7dbe-6956-482a-ad0f-663aa78bad74", "24baca81-1add-4779-855c-140a89b4c679",
        };
        //: What an older install left in the menu folder: the whole tool,
        //: which the installer moves out with the user's data.
        static readonly string[] FullInstall = { Path.Combine("src", "ide_bridge"), "cds_text_sync", "cli", ".git" };
        //: Menu entries releases before 3.0 wrote as whole scripts, with no
        //: marker: 3.x kept them, and the menu showed their old versions.
        static readonly string[] Retired = { "Project_compare.py", "Project_parameters.py", "Project_perf_test.py" };
        //: How a note names such a script: the install leaves it to the user.
        const string Outdated = "an older release's script, still in Tools > Scripting but no longer working; delete it: ";
        static readonly byte[] LfsPointer = Encoding.ASCII.GetBytes("version https://git-lfs");

        public static readonly CliCommand Command = new CliCommand
        {
            Name = "install",
            Summary = "Install the CODESYS menu entry and the in-IDE agent",
            Description = "Writes Tools > Scripting > Scripts > C > cds-text-sync into the CODESYS ScriptDir with the agent and "
                + "cts.exe beside it (and the mermaid of cts diagram view's page), and the same entry as a Script Command for a toolbar button; --toolbar also puts that button on "
                + "each profile's Standard toolbar. The files come from beside this cts.exe (a download's dist folder, an installed "
                + "agent) or, in a build tree, from the agent built with it. Only files that differ are written; CODESYS must be "
                + "closed while the agent changes. The ScriptDirs are every one that already holds cds-text-sync, or the first found "
                + "(the user's) when none does, unless --script-dir names one or --all takes every one. --check changes nothing "
                + "and says what is out of date (exit 1 when anything is), the files a running CODESYS holds too.",
            Options = new[]
            {
                CliOption.Text("--script-dir", "script_dir", "DIR", "CODESYS ScriptDir (default: each holding cds-text-sync, else the first found)"),
                CliOption.Switch("--all", "all", "Every CODESYS ScriptDir on this machine"),
                CliOption.Switch("--toolbar", "toolbar", "Put the button on each profile's Standard toolbar (CODESYS closed)"),
                CliOption.Switch("--check", "check", "Change nothing; report what is out of date"),
            },
            LocalExecute = (options, host, work) => Execute(options, work),
            Build = BuildAnswer,
        };

        static IDictionary<string, object> Execute(CliOptions options, string work)
        {
            var source = Sources(AppDomain.CurrentDomain.BaseDirectory);
            if (source == null)
                throw Refused("no agent beside this cts.exe or in its build tree; build src/Cts.Agent and src/Cts.Cli, or run the installer");
            var pointer = source.FirstOrDefault(IsLfsPointer);
            if (pointer != null)
                throw Refused(pointer + " is a Git LFS pointer, not the file: run git lfs pull, or the installer");
            IList<string> dirs;
            if (options.Params.TryGetValue("script_dir", out var named))
                dirs = new[] { Path.GetFullPath(Path.Combine(work, Convert.ToString(named, CultureInfo.InvariantCulture))) };
            else
            {
                dirs = ScriptDirs();
                if (dirs.Count == 0) throw Refused("no CODESYS ScriptDir on this machine; name one with --script-dir DIR");
                if (!options.Params.ContainsKey("all")) dirs = Installed(dirs);
            }
            var check = options.Params.ContainsKey("check");
            var toolbar = options.Params.ContainsKey("toolbar");
            var appData = Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData);
            return new Dictionary<string, object>
            {
                { "check", check },
                { "source", Path.GetDirectoryName(source[0]) },
                { "script_dirs", dirs.Select(dir => (object)Install(source, dir, check, toolbar, appData, DiagramView.Mermaid())).ToList() },
            };
        }

        // Of *dirs*, those holding an install, else the first: an IDE loads
        // the agent from whichever of them it reads, so each one holding an
        // install is brought up to date.
        internal static IList<string> Installed(IList<string> dirs)
        {
            var installed = dirs.Where(dir => File.Exists(Path.Combine(dir, Folder, Stub))).ToList();
            return installed.Count > 0 ? installed : dirs.Take(1).ToList();
        }

        // The agent files to copy, in AgentFiles' order, or null: beside
        // *exeDir* when all are there, else from the build tree *exeDir* is
        // the cts.exe output of (src/Cts.Cli/bin/CONFIG/net48) -- the agent of
        // the same configuration.
        internal static IList<string> Sources(string exeDir)
        {
            exeDir = exeDir.TrimEnd('\\', '/');
            var beside = AgentFiles.Select(name => Path.Combine(exeDir, name)).ToList();
            if (beside.All(File.Exists)) return beside;
            var config = Path.GetDirectoryName(exeDir);
            var src = config == null ? null : Path.GetDirectoryName(Path.GetDirectoryName(Path.GetDirectoryName(config)));
            if (src == null) return null;
            var agent = Path.Combine(src, "Cts.Agent", "bin", Path.GetFileName(config), Path.GetFileName(exeDir));
            var built = AgentFiles.Select(name => Path.Combine(name.StartsWith("cts.", StringComparison.Ordinal) ? exeDir : agent, name)).ToList();
            return built.All(File.Exists) ? built : null;
        }

        static bool IsLfsPointer(string path)
        {
            var head = new byte[LfsPointer.Length];
            using (var stream = File.OpenRead(path))
                return stream.Read(head, 0, head.Length) == head.Length && head.SequenceEqual(LfsPointer);
        }

        // The ScriptDirs CODESYS reads that exist, the user's first: the
        // user's (CODESYS, Astra.IDE), the machine's, then each install's.
        internal static IList<string> ScriptDirs()
        {
            var local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            var candidates = new List<string>
            {
                Path.Combine(local, "CODESYS", "ScriptDir"),
                Path.Combine(local, "Astra.IDE", "ScriptDir"),
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "CODESYS", "ScriptDir"),
            };
            foreach (var root in ProjectOpenCommand.ProgramFiles().Where(Directory.Exists))
            {
                candidates.AddRange(Directory.GetDirectories(root, "CODESYS *").OrderBy(d => d, StringComparer.OrdinalIgnoreCase)
                    .Select(install => Path.Combine(install, "CODESYS", "ScriptDir")));
                var delta = Path.Combine(root, "Delta Industrial Automation", "DIAStudio");
                if (Directory.Exists(delta))
                    candidates.AddRange(Directory.GetDirectories(delta).OrderBy(d => d, StringComparer.OrdinalIgnoreCase)
                        .Select(install => Path.Combine(install, "CODESYS", "ScriptDir")));
            }
            return candidates.Where(Directory.Exists).Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        }

        // Install into *scriptDir* from *source* (Sources), or with *check*
        // only say what would change. Each part is written only when its
        // bytes differ, so a second run changes nothing.
        internal static IDictionary<string, object> Install(IList<string> source, string scriptDir, bool check, bool toolbar, string appData, string mermaid)
        {
            var menu = Path.Combine(scriptDir, Folder);
            var agentDir = Path.Combine(menu, AgentFolder);
            var written = new List<object>();
            var removed = new List<object>();
            var notes = new List<object>();
            var problems = new List<object>();
            var result = new Dictionary<string, object>
            {
                { "script_dir", scriptDir }, { "menu", menu },
                { "written", written }, { "removed", removed }, { "notes", notes }, { "problems", problems },
            };
            var full = FullInstall.FirstOrDefault(name => Directory.Exists(Path.Combine(menu, name)));
            if (full != null)
            {
                problems.Add("an older full installation is in " + menu + ": run the installer, which moves it out with your settings");
                return result;
            }

            // The agent first: a running CODESYS holds its DLLs, and a menu
            // entry newer than the agent it loads would call what is not there.
            var copies = new List<KeyValuePair<string, string>>();
            foreach (var file in source.Concat(source.Select(Pdb).Where(File.Exists)))
            {
                var target = Path.Combine(agentDir, Path.GetFileName(file));
                if (!SameBytes(file, target)) copies.Add(new KeyValuePair<string, string>(file, target));
            }
            var keep = new HashSet<string>(source.Concat(source.Select(Pdb).Where(File.Exists)).Select(Path.GetFileName), StringComparer.OrdinalIgnoreCase);
            var strays = Directory.Exists(agentDir) ? Directory.GetFiles(agentDir).Where(file => !keep.Contains(Path.GetFileName(file))).ToList() : new List<string>();
            var locked = copies.Select(pair => pair.Value).Concat(strays).Where(Locked).ToList();
            if (locked.Count > 0)
            {
                problems.Add("CODESYS holds " + string.Join(", ", locked.Select(Path.GetFileName)) + ": close it, then run cts install"
                    + (check ? "" : " again"));
                if (!check) return result;
            }
            foreach (var pair in copies)
            {
                written.Add(pair.Value);
                if (check) continue;
                Directory.CreateDirectory(agentDir);
                File.Copy(pair.Key, pair.Value, true);
            }
            foreach (var stray in strays)
            {
                removed.Add(stray);
                if (!check) File.Delete(stray);
            }
            // The diagram page's mermaid (*mermaid*, the install's), where `cts
            // diagram view` run from this copy, as the quick window runs it, finds it.
            if (mermaid != null) Write(Path.Combine(agentDir, DiagramView.Assets, DiagramView.MermaidFile), File.ReadAllBytes(mermaid), check, written);

            var stub = StubText(agentDir);
            Write(Path.Combine(menu, Stub), Encoding.UTF8.GetBytes(stub), check, written);
            Survey(menu, notes);
            // A stub an older install wrote at the ScriptDir root is still in the menu.
            if (Directory.Exists(scriptDir))
                foreach (var file in Directory.GetFiles(scriptDir, "*.py").Where(HasMarker).OrderBy(f => f, StringComparer.Ordinal))
                    notes.Add(Outdated + file);

            var command = ScriptCommand(scriptDir, stub, check, written, problems);
            result["command"] = command;
            if (toolbar && command != null)
                result["toolbar"] = Toolbar(Path.GetFileName(Path.GetDirectoryName(scriptDir)), appData,
                    CommandGuids[(int)command["index"]], check, written, notes, problems);
            return result;
        }

        static string Pdb(string file)
        {
            return Path.ChangeExtension(file, ".pdb");
        }

        // The menu folder holds the stub and the agent. Whatever else is there
        // stays: scripts an older release wrote are named for the user to
        // delete, anything else is named as left in place.
        static void Survey(string menu, List<object> notes)
        {
            if (!Directory.Exists(menu)) return;
            foreach (var dir in Directory.GetDirectories(menu).OrderBy(d => d, StringComparer.Ordinal))
                if (Path.GetFileName(dir) != AgentFolder) notes.Add("left in place: " + dir);
            foreach (var file in Directory.GetFiles(menu).OrderBy(f => f, StringComparer.Ordinal))
            {
                if (Path.GetFileName(file) == Stub) continue;
                var older = HasMarker(file) || Retired.Contains(Path.GetFileName(file), StringComparer.OrdinalIgnoreCase);
                notes.Add((older ? Outdated : "left in place: ") + file);
            }
        }

        // The menu entry: it loads the agent from *agentDir* into the IDE and
        // hands over to AgentHost.Menu. The CODESYS script engine is
        // IronPython 2.7, which reads a plain literal holding UTF-8 as bytes,
        // so the folder is a unicode literal with escapes outside ASCII.
        internal static string StubText(string agentDir)
        {
            return "# -*- coding: utf-8 -*-\n"
                + Marker + "\n"
                + "# Written by cts install: " + Description.ToLowerInvariant() + ".\n"
                + "import os\n"
                + "\n"
                + "AGENT = " + Literal(agentDir) + "\n"
                + "\n"
                + "\n"
                + "def main():\n"
                + "    try:\n"
                + "        import clr\n"
                + "        clr.AddReferenceToFileAndPath(os.path.join(AGENT, \"Cts.Agent.Core.dll\"))\n"
                + "        clr.AddReferenceToFileAndPath(os.path.join(AGENT, \"Cts.Agent.dll\"))\n"
                + "        from Cts.Agent import AgentHost\n"
                + "    except Exception as error:\n"
                + "        import clr\n"
                + "        clr.AddReference(\"System.Windows.Forms\")\n"
                + "        from System.Windows.Forms import MessageBox\n"
                + "        MessageBox.Show(u\"The cts agent did not start: %s\\n\\nRun cts install again.\" % error, u\"cds-text-sync\")\n"
                + "        return\n"
                + "    said = AgentHost.Menu()\n"
                + "    if said:\n"
                + "        print(said)\n"
                + "\n"
                + "\n"
                + "if __name__ == \"__main__\":\n"
                + "    main()\n";
        }

        // *path* as an ASCII-only Python unicode literal.
        internal static string Literal(string path)
        {
            var sb = new StringBuilder("u\"");
            foreach (var c in path)
            {
                if (c == '\\') sb.Append("\\\\");
                else if (c == '"') sb.Append("\\\"");
                else if (c >= 32 && c < 127) sb.Append(c);
                else sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
            }
            return sb.Append('"').ToString();
        }

        // The Script Commands entry beside *scriptDir*: a copy of the stub, the
        // icon, and its line in config.json, which CODESYS turns into the
        // command ExecuteScript1n a toolbar button runs. Null when the config
        // cannot take it.
        static IDictionary<string, object> ScriptCommand(string scriptDir, string stub, bool check, List<object> written, List<object> problems)
        {
            var commands = Path.Combine(Path.GetDirectoryName(scriptDir), "Script Commands");
            var config = Path.Combine(commands, "config.json");
            List<object> entries;
            try
            {
                var parsed = File.Exists(config) ? Json.Parse(File.ReadAllText(config)) : new List<object>();
                entries = parsed as List<object>;
                if (entries == null)
                {
                    problems.Add(config + " is not a JSON array; left as it is");
                    return null;
                }
            }
            catch (JsonException e)
            {
                problems.Add(config + " is not readable JSON (" + e.Message + "); left as it is");
                return null;
            }
            var path = Folder + "\\" + Stub;
            var index = entries.FindIndex(entry => entry is IDictionary<string, object> map && map.TryGetValue("Path", out var p) && (p as string) == path);
            if (index < 0 && entries.Count >= CommandGuids.Length)
            {
                problems.Add(config + " already has " + CommandGuids.Length + " entries; cds-text-sync is not among them");
                return null;
            }
            if (index < 0)
            {
                index = entries.Count;
                entries.Add(null);
            }
            entries[index] = new Dictionary<string, object> { { "Name", Folder }, { "Desc", Description }, { "Icon", Folder + "\\" + Icon }, { "Path", path } };
            Write(Path.Combine(commands, Folder, Stub), Encoding.UTF8.GetBytes(stub), check, written);
            Write(Path.Combine(commands, Folder, Icon), IconBytes(), check, written);
            Write(config, Encoding.UTF8.GetBytes(Json.Pretty(entries) + "\n"), check, written);
            return new Dictionary<string, object>
            {
                { "index", index },
                { "command", "ExecuteScript" + (0x10 + index).ToString("X", CultureInfo.InvariantCulture) },
                { "guid", CommandGuids[index] },
            };
        }

        static byte[] IconBytes()
        {
            using (var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("Cts.Agent.Install." + Icon))
            using (var copy = new MemoryStream())
            {
                stream.CopyTo(copy);
                return copy.ToArray();
            }
        }

        // The button on the Standard toolbar of each CODESYS profile of *ide*
        // (the folder its ScriptDir is in: CODESYS, Astra.IDE). CODESYS writes
        // these files as it closes, so a running one would undo the change.
        static IDictionary<string, object> Toolbar(string ide, string appData, string guid, bool check, List<object> written, List<object> notes, List<object> problems)
        {
            var root = Path.Combine(appData, ide);
            var files = Directory.Exists(root)
                ? Directory.GetDirectories(root, "UserOptions-*").SelectMany(dir => Directory.GetFiles(dir, "*.opt.tbar")).OrderBy(f => f, StringComparer.Ordinal).ToList()
                : new List<string>();
            var changed = new List<object>();
            var result = new Dictionary<string, object> { { "changed", changed } };
            if (files.Count == 0)
            {
                notes.Add("no " + ide + " toolbar settings yet: start " + ide + " once, close it, then run cts install --toolbar again");
                return result;
            }
            if (Process.GetProcessesByName(ide).Length > 0)
            {
                notes.Add(ide + " is running: close it, then run cts install --toolbar again for the button");
                return result;
            }
            foreach (var file in files)
            {
                var bytes = ToolbarFile.WithButton(File.ReadAllBytes(file), guid, Folder, Description, out var problem);
                if (problem != null) problems.Add(problem + " in " + file);
                if (bytes == null) continue;
                changed.Add(file);
                written.Add(file);
                if (check) continue;
                var backup = file + ".cts-backup";
                if (!File.Exists(backup)) File.Copy(file, backup);
                File.WriteAllBytes(file, bytes);
            }
            return result;
        }

        static void Write(string path, byte[] bytes, bool check, List<object> written)
        {
            if (File.Exists(path) && File.ReadAllBytes(path).SequenceEqual(bytes)) return;
            written.Add(path);
            if (check) return;
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            File.WriteAllBytes(path, bytes);
        }

        static bool SameBytes(string left, string right)
        {
            if (string.Equals(Path.GetFullPath(left), Path.GetFullPath(right), StringComparison.OrdinalIgnoreCase)) return true;
            if (!File.Exists(right) || new FileInfo(left).Length != new FileInfo(right).Length) return false;
            return File.ReadAllBytes(left).SequenceEqual(File.ReadAllBytes(right));
        }

        static bool Locked(string path)
        {
            if (!File.Exists(path)) return false;
            try
            {
                using (new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None)) return false;
            }
            catch (IOException) { return true; }
            catch (UnauthorizedAccessException) { return true; }
        }

        static bool HasMarker(string path)
        {
            try
            {
                using (var reader = new StreamReader(path, Encoding.UTF8))
                {
                    var head = new char[400];
                    var read = reader.ReadBlock(head, 0, head.Length);
                    return new string(head, 0, read).Contains(Marker);
                }
            }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
        }

        static Answer BuildAnswer(IDictionary<string, object> data)
        {
            var check = data["check"] is bool b && b;
            var dirs = ((IEnumerable<object>)data["script_dirs"]).Cast<IDictionary<string, object>>().ToList();
            var written = dirs.Sum(dir => ((IList<object>)dir["written"]).Count);
            var removed = dirs.Sum(dir => ((IList<object>)dir["removed"]).Count);
            var problems = dirs.Sum(dir => ((IList<object>)dir["problems"]).Count);
            var answer = new Answer()
                .Add("script_dirs", dirs.Count)
                .Add(check ? "outdated" : "written", written + removed)
                .Add("problems", problems)
                .Add("source", data["source"]);
            foreach (var dir in dirs)
            {
                answer.Detail("menu " + dir["menu"]);
                foreach (var path in (IList<object>)dir["written"]) answer.Detail((check ? "  would write " : "  wrote ") + path);
                foreach (var path in (IList<object>)dir["removed"]) answer.Detail((check ? "  would remove " : "  removed ") + path);
                if (dir.TryGetValue("command", out var c) && c is IDictionary<string, object> command)
                    answer.Detail("  script command " + command["command"] + " {" + command["guid"] + "}"
                        + (dir.ContainsKey("toolbar") ? "" : "; for a toolbar button: cts install --toolbar, or Tools > Customize > Toolbars > Add Command > ScriptEngine Commands > cds-text-sync"));
                foreach (var note in (IList<object>)dir["notes"]) answer.Detail("  note: " + note);
                foreach (var problem in (IList<object>)dir["problems"]) answer.Detail("  problem: " + problem);
            }
            if (problems > 0) return answer.Failed();
            return check && written + removed > 0 ? answer.Partial() : answer;
        }

        static CliFailure Refused(string message)
        {
            return new CliFailure(Verb, "refused", message, "cts install --help", 2);
        }
    }
}
