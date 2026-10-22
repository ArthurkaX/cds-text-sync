using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class CliInstallTests : IDisposable
    {
        static readonly string[] Names = { "Cts.Agent.Core.dll", "Cts.Agent.dll", "cts.exe", "cts.exe.config" };
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-install-" + Guid.NewGuid().ToString("N"));

        public void Dispose()
        {
            if (Directory.Exists(_root)) Directory.Delete(_root, true);
        }

        IList<string> Source(string content = "build 1")
        {
            var dist = Path.Combine(_root, "dist");
            Directory.CreateDirectory(dist);
            foreach (var name in Names) File.WriteAllText(Path.Combine(dist, name), name + " " + content);
            return InstallCommand.Sources(dist);
        }

        string ScriptDir(string ide = "CODESYS")
        {
            return Path.Combine(_root, "local", ide, "ScriptDir");
        }

        IDictionary<string, object> Install(IList<string> source, string scriptDir, bool check = false, bool toolbar = false)
        {
            return InstallCommand.Install(source, scriptDir, check, toolbar, Path.Combine(_root, "roaming"));
        }

        static IList<object> List(IDictionary<string, object> result, string key)
        {
            return (IList<object>)result[key];
        }

        [Fact]
        public void Install_writes_the_menu_entry_the_agent_and_the_script_command_then_nothing_more()
        {
            var scriptDir = ScriptDir();
            var first = Install(Source(), scriptDir);
            Assert.Empty(List(first, "problems"));
            var menu = Path.Combine(scriptDir, "cds-text-sync");
            Assert.Equal(new[] { "cds-text-sync.py" }, Directory.GetFiles(menu).Select(Path.GetFileName));
            Assert.Equal(Names.OrderBy(n => n, StringComparer.Ordinal),
                Directory.GetFiles(Path.Combine(menu, "agent")).Select(Path.GetFileName).OrderBy(n => n, StringComparer.Ordinal));
            var stub = File.ReadAllText(Path.Combine(menu, "cds-text-sync.py"));
            Assert.Contains(InstallCommand.Marker, stub);
            Assert.Contains("AGENT = " + InstallCommand.Literal(Path.Combine(menu, "agent")), stub);
            Assert.Contains("AgentHost.Menu()", stub);
            var commands = Path.Combine(_root, "local", "CODESYS", "Script Commands");
            Assert.Equal(stub, File.ReadAllText(Path.Combine(commands, "cds-text-sync", "cds-text-sync.py")));
            Assert.True(File.ReadAllBytes(Path.Combine(commands, "cds-text-sync", "cds-text-sync.ico")).Length > 0);
            var command = (IDictionary<string, object>)first["command"];
            Assert.Equal("ExecuteScript10", command["command"]);
            Assert.Equal("ea88ff69-1e93-446d-a4db-58718b3f507c", command["guid"]);

            var again = Install(Source(), scriptDir);
            Assert.Empty(List(again, "written"));
            Assert.Empty(List(again, "removed"));
            var check = Install(Source("build 2"), scriptDir, check: true);
            Assert.Equal(Names.Select(name => Path.Combine(menu, "agent", name)), List(check, "written").Cast<string>());
            Assert.Equal("cts.exe build 1", File.ReadAllText(Path.Combine(menu, "agent", "cts.exe")));
        }

        [Fact]
        public void Check_says_what_a_fresh_install_writes_and_writes_none_of_it()
        {
            var scriptDir = ScriptDir();
            var result = Install(Source(), scriptDir, check: true);
            Assert.Equal(Names.Length + 4, List(result, "written").Count);
            Assert.False(Directory.Exists(scriptDir));
            Assert.False(Directory.Exists(Path.Combine(_root, "local", "CODESYS", "Script Commands")));
        }

        [Fact]
        public void A_file_a_running_CODESYS_holds_is_still_checked_and_stops_only_the_install()
        {
            var scriptDir = ScriptDir();
            Install(Source(), scriptDir);
            var held = Path.Combine(scriptDir, "cds-text-sync", "agent", "Cts.Agent.Core.dll");
            using (new FileStream(held, FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                var check = Install(Source("build 2"), scriptDir, check: true);
                Assert.Equal(Names.Length, List(check, "written").Count);
                Assert.Contains("CODESYS holds Cts.Agent.Core.dll", (string)List(check, "problems").Single());
                var install = Install(Source("build 2"), scriptDir);
                Assert.Empty(List(install, "written"));
                Assert.Single(List(install, "problems"));
            }
        }

        [Fact]
        public void Without_a_named_ScriptDir_each_one_holding_an_install_is_taken_else_the_first()
        {
            var user = ScriptDir();
            var machine = ScriptDir("Machine");
            var other = ScriptDir("Other");
            foreach (var dir in new[] { user, machine, other }) Directory.CreateDirectory(dir);
            Assert.Equal(new[] { user }, InstallCommand.Installed(new[] { user, machine, other }));
            Install(Source(), machine);
            Install(Source(), other);
            Assert.Equal(new[] { machine, other }, InstallCommand.Installed(new[] { user, machine, other }));
        }

        [Fact]
        public void The_agent_comes_from_beside_cts_exe_or_from_its_build_tree()
        {
            Assert.Null(InstallCommand.Sources(Path.Combine(_root, "src", "Cts.Cli", "bin", "Debug", "net48")));
            var cli = Path.Combine(_root, "src", "Cts.Cli", "bin", "Debug", "net48");
            var agent = Path.Combine(_root, "src", "Cts.Agent", "bin", "Debug", "net48");
            Directory.CreateDirectory(cli);
            Directory.CreateDirectory(agent);
            File.WriteAllText(Path.Combine(cli, "cts.exe"), "");
            File.WriteAllText(Path.Combine(cli, "cts.exe.config"), "");
            File.WriteAllText(Path.Combine(agent, "Cts.Agent.Core.dll"), "");
            File.WriteAllText(Path.Combine(agent, "Cts.Agent.dll"), "");
            Assert.Equal(new[] { Path.Combine(agent, Names[0]), Path.Combine(agent, Names[1]), Path.Combine(cli, Names[2]), Path.Combine(cli, Names[3]) },
                InstallCommand.Sources(cli + Path.DirectorySeparatorChar));
        }

        [Fact]
        public void The_agent_folder_keeps_only_the_agent_and_its_symbols()
        {
            var source = Source();
            var dist = Path.GetDirectoryName(source[0]);
            File.WriteAllText(Path.Combine(dist, "Cts.Agent.pdb"), "symbols");
            var agent = Path.Combine(ScriptDir(), "cds-text-sync", "agent");
            Directory.CreateDirectory(agent);
            File.WriteAllText(Path.Combine(agent, "Cts.Agent.Core.pdb"), "stale");
            var result = Install(source, ScriptDir());
            Assert.Equal(new object[] { Path.Combine(agent, "Cts.Agent.Core.pdb") }, List(result, "removed"));
            Assert.Equal("symbols", File.ReadAllText(Path.Combine(agent, "Cts.Agent.pdb")));
        }

        [Fact]
        public void Older_scripts_stay_named_for_deletion_and_the_users_files_stay_named()
        {
            var scriptDir = ScriptDir();
            var menu = Path.Combine(scriptDir, "cds-text-sync");
            Directory.CreateDirectory(Path.Combine(menu, "__pycache__"));
            File.WriteAllText(Path.Combine(menu, "Project_daemon.py"), "# x\n" + InstallCommand.Marker + "\n");
            File.WriteAllText(Path.Combine(menu, "mine.py"), "print(1)\n");
            File.WriteAllText(Path.Combine(menu, "project_parameters.py"), "# v1.x\n");
            File.WriteAllText(Path.Combine(scriptDir, "Project_export.py"), InstallCommand.Marker + "\n");
            File.WriteAllText(Path.Combine(scriptDir, "own_tool.py"), "print(2)\n");
            var result = Install(Source(), scriptDir);
            Assert.Empty(List(result, "removed"));
            const string older = "an older release's script, still in Tools > Scripting but no longer working; delete it: ";
            Assert.Equal(new object[]
                {
                    "left in place: " + Path.Combine(menu, "__pycache__"), older + Path.Combine(menu, "Project_daemon.py"),
                    "left in place: " + Path.Combine(menu, "mine.py"), older + Path.Combine(menu, "project_parameters.py"),
                    older + Path.Combine(scriptDir, "Project_export.py"),
                },
                List(result, "notes"));
            foreach (var kept in new[] { Path.Combine(menu, "Project_daemon.py"), Path.Combine(scriptDir, "Project_export.py"), Path.Combine(scriptDir, "own_tool.py") })
                Assert.True(File.Exists(kept));
            Assert.Empty(List(result, "problems"));
        }

        [Fact]
        public void A_full_older_installation_in_the_menu_folder_is_left_to_the_installer()
        {
            var menu = Path.Combine(ScriptDir(), "cds-text-sync");
            Directory.CreateDirectory(Path.Combine(menu, "src", "ide_bridge"));
            var result = Install(Source(), ScriptDir());
            Assert.Contains("run the installer", (string)List(result, "problems").Single());
            Assert.False(Directory.Exists(Path.Combine(menu, "agent")));
        }

        [Fact]
        public void The_script_command_keeps_other_entries_and_updates_its_own()
        {
            var commands = Path.Combine(_root, "local", "CODESYS", "Script Commands");
            Directory.CreateDirectory(commands);
            var config = Path.Combine(commands, "config.json");
            File.WriteAllText(config, "[{\"Name\": \"other\", \"Desc\": \"keep\", \"Path\": \"other.py\", \"Icon\": \"other.ico\"},"
                + " {\"Name\": \"cds-text-sync\", \"Desc\": \"old\", \"Path\": \"cds-text-sync\\\\cds-text-sync.py\"}]");
            var result = Install(Source(), ScriptDir());
            var entries = (List<object>)Json.Parse(File.ReadAllText(config));
            var other = (IDictionary<string, object>)entries[0];
            Assert.Equal("keep", other["Desc"]);
            Assert.Equal("other.py", other["Path"]);
            var ours = (IDictionary<string, object>)entries[1];
            Assert.Equal(InstallCommand.Description, ours["Desc"]);
            Assert.Equal("cds-text-sync\\cds-text-sync.ico", ours["Icon"]);
            Assert.Equal("ExecuteScript11", ((IDictionary<string, object>)result["command"])["command"]);
        }

        [Theory]
        [InlineData("{}", "not a JSON array")]
        [InlineData("[{},{},{},{},{},{},{},{},{},{},{},{},{},{},{},{}]", "already has 16 entries")]
        public void An_unusable_script_command_config_is_left_as_it_is(string payload, string problem)
        {
            var commands = Path.Combine(_root, "local", "CODESYS", "Script Commands");
            Directory.CreateDirectory(commands);
            var config = Path.Combine(commands, "config.json");
            File.WriteAllText(config, payload);
            var result = Install(Source(), ScriptDir());
            Assert.Contains(problem, (string)List(result, "problems").Single());
            Assert.Equal(payload, File.ReadAllText(config));
            Assert.False(result["command"] != null);
        }

        string ToolbarFile(string ide, out string text)
        {
            var profile = Path.Combine(_root, "roaming", ide, "UserOptions-test");
            Directory.CreateDirectory(profile);
            var path = Path.Combine(profile, "CODESYS.test.opt.tbar");
            text = ("<?xml version=\"1.0\"?>\n"
                + "<Root>\n"
                + "  <Single Type=\"{66f789cf-103c-4468-9061-8f9f2c328b4f}\" Method=\"IArchivable\">\n"
                + "    <Single Name=\"Name\" Type=\"string\">Standard</Single>\n"
                + "    <Single Name=\"Visible\" Type=\"bool\">True</Single>\n"
                + "    <List Name=\"Items\" Type=\"{3bc3f197-341f-431c-886e-6292b155bc7f}\">\n"
                + "      <Single Type=\"{e16c184c-db87-476b-8425-06ed4e6b0eec}\" Method=\"IArchivable\" />\n"
                + "    </List>\n"
                + "  </Single>\n"
                + "  <Single Type=\"{foreign}\" Method=\"IArchivable\">\n"
                + "    <Single Name=\"Name\" Type=\"string\">Other</Single>\n"
                + "  </Single>\n"
                + "</Root>\n").Replace("\n", "\r\n");
            File.WriteAllBytes(path, Utf16(text));
            return path;
        }

        static byte[] Utf16(string text)
        {
            return new byte[] { 0xFF, 0xFE }.Concat(Encoding.Unicode.GetBytes(text)).ToArray();
        }

        [Theory]
        [InlineData("CODESYS")]
        [InlineData("Astra.IDE")]
        public void The_toolbar_button_goes_on_Standard_once_with_a_backup_of_the_file_before(string ide)
        {
            var path = ToolbarFile(ide, out var original);
            var other = ToolbarFile("Other.IDE", out var otherText);
            var result = Install(Source(), ScriptDir(ide), toolbar: true);
            Assert.Empty(List(result, "problems"));
            Assert.Equal(new object[] { path }, (IList<object>)((IDictionary<string, object>)result["toolbar"])["changed"]);
            Assert.Equal(Utf16(original), File.ReadAllBytes(path + ".cts-backup"));
            var updated = Encoding.Unicode.GetString(File.ReadAllBytes(path).Skip(2).ToArray());
            var entry = "      <Single Type=\"{d7c09fff-b12f-47d8-bd4f-3d60b8672b7f}\" Method=\"IArchivable\">\r\n"
                + "        <Single Name=\"CommandGuid\" Type=\"System.Guid\">ea88ff69-1e93-446d-a4db-58718b3f507c</Single>\r\n"
                + "        <Single Name=\"InfoCache\" Type=\"string\">AQAAAB0+t44NY2RzLXRleHQtc3luYy1TdGFydCB0aGUgY3RzIGFnZW50IGFuZCBvcGVuIHRoZSBxdWljayB3aW5kb3cAAAAA</Single>\r\n"
                + "      </Single>\r\n";
            Assert.Equal(original.Replace("    </List>", entry + "    </List>"), updated);

            var once = File.ReadAllBytes(path);
            var again = Install(Source(), ScriptDir(ide), toolbar: true);
            Assert.Empty((IList<object>)((IDictionary<string, object>)again["toolbar"])["changed"]);
            Assert.Equal(once, File.ReadAllBytes(path));
            Assert.Equal(Utf16(original), File.ReadAllBytes(path + ".cts-backup"));
            Assert.Equal(Utf16(otherText), File.ReadAllBytes(other));
        }

        [Fact]
        public void No_toolbar_settings_yet_is_a_note_to_start_the_ide_once()
        {
            var result = Install(Source(), ScriptDir(), toolbar: true);
            Assert.Equal(new object[] { "no CODESYS toolbar settings yet: start CODESYS once, close it, then run cts install --toolbar again" },
                List(result, "notes"));
            Assert.Empty(List(result, "problems"));
        }

        [Theory]
        [InlineData(@"C:\Users\dev\AppData\Local\CODESYS\ScriptDir\cds-text-sync\agent", @"u""C:\\Users\\dev\\AppData\\Local\\CODESYS\\ScriptDir\\cds-text-sync\\agent""")]
        [InlineData("C:\\Users\\J\u00f6rg \"x\"\\agent", "u\"C:\\\\Users\\\\J\\u00f6rg \\\"x\\\"\\\\agent\"")]
        public void The_agent_folder_is_an_ascii_unicode_literal(string path, string literal)
        {
            Assert.Equal(literal, InstallCommand.Literal(path));
        }
    }
}
