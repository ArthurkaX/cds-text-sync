using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        static object Texts() => new Dictionary<string, object> { { "objects", new object[]
        {
            new Dictionary<string, object> { { "name", "Pair" }, { "declaration", "TYPE Pair : STRUCT x : INT; y : BOOL; END_STRUCT END_TYPE" } },
            new Dictionary<string, object> { { "name", "GVL" }, { "declaration", "VAR_GLOBAL pair : Pair; points : ARRAY[0..1] OF Pair; n : WORD; END_VAR" } },
            new Dictionary<string, object> { { "name", "MAIN" }, { "declaration", "PROGRAM MAIN VAR fb : FB; END_VAR" } },
            new Dictionary<string, object> { { "name", "FB" }, { "declaration", "FUNCTION_BLOCK FB VAR_INPUT input : REAL; END_VAR VAR_OUTPUT output : BOOL; END_VAR" } },
            // The IDE's declaration of an FB has no END_FUNCTION_BLOCK; its method's variables are not the FB's.
            new Dictionary<string, object> { { "name", "Run" }, { "declaration", "METHOD Run : BOOL VAR_INPUT k : INT; END_VAR VAR temp : INT; END_VAR" } },
        } } };

        [Fact]
        public void Snapshooter_tree_lists_typed_structure_and_scalar_leaves_without_login()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, _) =>
            {
                Assert.Equal("objects.texts", method);
                return Texts();
            });
            var (code, output, _) = Run(host, "snapshooter", "tree", "--json");
            Assert.Equal(0, code);
            Assert.Contains("GVL.pair.x", output);
            Assert.Contains("\"type\": \"INT\"", output);
            Assert.Contains("GVL.n", output);
            Assert.Contains("GVL.points[1].y", output);
            Assert.Contains("MAIN.fb.input", output);
            Assert.DoesNotContain("MAIN.fb.k", output);
            Assert.DoesNotContain("MAIN.fb.temp", output);
        }

        [Fact]
        public void Snapshooter_take_writes_the_python_preset_format_and_json_keeps_payload()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "objects.texts") return Texts();
                if (method == "project.status") return new Dictionary<string, object> { { "path", @"C:\work\Demo.project" } };
                Assert.Equal("vars.read", method);
                var names = ((IEnumerable<object>)p["names"]).Cast<string>().ToArray();
                return new Dictionary<string, object> { { "logged_in", true }, { "results", names.Select(n => (object)new Dictionary<string, object> { { "name", n }, { "ok", true }, { "text", "1" } }).ToArray() } };
            });
            var (code, output, _) = Run(host, "snapshooter", "take", "--path", "GVL.n", "--json");
            Assert.Equal(0, code);
            Assert.Contains("\"format_version\": 1", output);
            Assert.Contains("\"variables\"", output);
            Assert.Contains("\"type\": \"WORD\"", output);
        }

        [Fact]
        public void Snapshooter_loads_a_python_preset_for_diff_and_restore()
        {
            var path = Path.GetTempFileName();
            try
            {
                File.WriteAllText(path, "{\"meta\":{\"format_version\":1},\"variables\":[{\"path\":\"GVL.n\",\"type\":\"WORD\",\"value\":\"WORD#5\",\"read_ok\":true}]}");
                var writes = 0;
                var host = new FakeHost();
                host.Agents[1] = Agent(null, null, (method, p) =>
                {
                    if (method == "objects.texts") return Texts();
                    if (method == "vars.read") return new Dictionary<string, object> { { "logged_in", true }, { "results", new object[] { new Dictionary<string, object> { { "name", "GVL.n" }, { "ok", true }, { "text", writes > 0 ? "WORD#5" : "WORD#8" } } } } };
                    Assert.Equal("vars.write", method); writes++;
                    Assert.Equal("WORD#5", ((IDictionary<string, object>)p["values"])["GVL.n"]);
                    return new Dictionary<string, object> { { "logged_in", true }, { "results", new object[] { new Dictionary<string, object> { { "name", "GVL.n" }, { "ok", true } } } } };
                });
                var (diffCode, diff, _) = Run(host, "snapshooter", "diff", "--input", path, "--json");
                Assert.Equal(0, diffCode);
                Assert.Contains("GVL.n", diff);
                Assert.Contains("WORD#5", diff);
                var (dryCode, dry, _) = Run(host, "snapshooter", "restore", "--input", path, "--json");
                Assert.Equal(0, dryCode);
                Assert.Contains("\"would_write\": 1", dry);
                Assert.Equal(0, writes);
                var (applyCode, applied, _) = Run(host, "snapshooter", "restore", "--input", path, "--apply", "--json");
                Assert.Equal(0, applyCode);
                Assert.Contains("\"written\": 1", applied);
                // Read back before the command ends, so a diff right after it sees the value.
                Assert.Contains("\"confirmed\": 1", applied);
                Assert.Equal(1, writes);
            }
            finally { File.Delete(path); }
        }
    }
}
