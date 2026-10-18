using System;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        // An agent answering one `plc.*` method; the parameters it was sent.
        static FakeHost PlcAgent(string expected, IDictionary<string, object> answer, List<IDictionary<string, object>> sent)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                Assert.Equal(expected, method);
                sent.Add(p);
                return answer;
            });
            return host;
        }

        [Fact]
        public void Plc_info_names_each_application_with_its_state_and_project()
        {
            var host = PlcAgent("plc.info", new Dictionary<string, object>
            {
                { "runtime", "3.5.19.61" }, { "device", "CODESYS Control for Linux SL" }, { "vendor", "CODESYS" }, { "node", "LINE1" },
                { "applications", new List<object>
                    {
                        new Dictionary<string, object> { { "name", "Application" }, { "state", "run" }, { "project", "plant" }, { "last_change", "2026-10-17 21:15:16" }, { "compiler", "3.5.22.30" } },
                        new Dictionary<string, object> { { "name", "Spare" }, { "state", "stop" } },
                    } },
            }, new List<IDictionary<string, object>>());
            var (code, output, _) = Run(host, "plc", "info");
            Assert.Equal(0, code);
            Assert.Contains("ok plc-info runtime=3.5.19.61 device=\"CODESYS Control for Linux SL\" node=LINE1 applications=2", output);
            Assert.Contains("\nApplication run, from project plant, changed 2026-10-17 21:15:16, compiler 3.5.22.30\n", output);
            Assert.Contains("\nSpare stop\n", output);
        }

        [Fact]
        public void Plc_ls_lists_directories_first_then_files_with_size_and_time()
        {
            var sent = new List<IDictionary<string, object>>();
            var host = PlcAgent("plc.files", new Dictionary<string, object>
            {
                { "path", "PlcLogic" },
                { "files", new List<object>
                    {
                        new Dictionary<string, object> { { "name", "App.ret" }, { "is_directory", false }, { "size", 387736L }, { "last_write_time", "2026-10-14T20:29:00Z" } },
                        new Dictionary<string, object> { { "name", "visu" }, { "is_directory", true }, { "size", 0L }, { "last_write_time", "2026-10-17T17:15:31Z" } },
                    } },
                { "count", 2L },
            }, sent);
            var (code, output, _) = Run(host, "plc", "ls", "PlcLogic");
            Assert.Equal(0, code);
            Assert.Equal("PlcLogic", sent[0]["path"]);
            Assert.Contains("ok plc-ls path=PlcLogic count=2\nvisu/\nApp.ret  387736  2026-10-14 20:29:00\n", output);
        }

        [Fact]
        public void Plc_get_into_a_folder_names_the_copy_after_the_plc_file()
        {
            var folder = Path.Combine(Path.GetTempPath(), "cts-plc-get-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(folder);
            try
            {
                var sent = new List<IDictionary<string, object>>();
                var host = PlcAgent("plc.fetch", new Dictionary<string, object>
                {
                    { "file", "PlcLogic/Application/Application.crc" }, { "saved_to", "x" }, { "size", 20L }, { "crc32", "9171f120" },
                }, sent);
                var (code, output, _) = Run(host, "plc", "get", "PlcLogic/Application/Application.crc", "--output", folder);
                Assert.Equal(0, code);
                Assert.Equal(Path.Combine(folder, "Application.crc"), sent[0]["output"]);
                Assert.Contains("crc32=9171f120", output);
            }
            finally { Directory.Delete(folder, true); }
        }

        [Fact]
        public void Plc_put_sends_the_full_source_path_and_says_when_the_plc_gave_no_crc()
        {
            var sent = new List<IDictionary<string, object>>();
            var host = PlcAgent("plc.upload", new Dictionary<string, object>
            {
                { "source", "s" }, { "destination", "recipes/a.csv" }, { "size", 3L }, { "unchecked", "this IDE cannot ask the PLC for a file's CRC" },
            }, sent);
            var (code, output, _) = Run(host, "plc", "put", "a.csv", "recipes/a.csv");
            Assert.Equal(0, code);
            Assert.Equal(Path.GetFullPath("a.csv"), sent[0]["src"]);
            Assert.Equal("recipes/a.csv", sent[0]["dest"]);
            Assert.Contains("crc32=unchecked", output);
            Assert.Contains("unchecked: this IDE cannot ask the PLC for a file's CRC", output);
        }

        [Fact]
        public void Plc_rm_needs_a_path_and_sends_recursive_only_when_asked()
        {
            var sent = new List<IDictionary<string, object>>();
            var host = PlcAgent("plc.remove", new Dictionary<string, object> { { "removed", "old" }, { "is_directory", true }, { "entries", 3L } }, sent);
            var (usage, _, error) = Run(host, "plc", "rm");
            Assert.Equal(2, usage);
            Assert.Contains("expected PATH", error);
            Assert.Empty(sent);
            Run(host, "plc", "rm", "old");
            var (code, output, _) = Run(host, "plc", "rm", "--recursive", "old");
            Assert.Equal(0, code);
            Assert.Equal(false, sent[0]["recursive"]);
            Assert.Equal(true, sent[1]["recursive"]);
            Assert.Contains("ok plc-rm removed=old directory=true entries=3", output);
        }

        [Fact]
        public void Plc_mv_sends_both_paths()
        {
            var sent = new List<IDictionary<string, object>>();
            var host = PlcAgent("plc.move", new Dictionary<string, object> { { "from", "a" }, { "to", "b" }, { "is_directory", false } }, sent);
            var (code, _, _) = Run(host, "plc", "mv", "a", "b");
            Assert.Equal(0, code);
            Assert.Equal("a", sent[0]["from"]);
            Assert.Equal("b", sent[0]["to"]);
        }
    }
}
