using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Fact]
        public void Diag_reports_counts_and_settings_and_names_no_file_branch_or_path()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-diag-" + Guid.NewGuid().ToString("N"), "PlantSecret");
            Directory.CreateDirectory(root);
            try
            {
                Git(root, "init --quiet");
                Git(root, "config core.autocrlf false");
                File.WriteAllText(Path.Combine(root, ".gitattributes"), "* -text\n");
                File.WriteAllText(Path.Combine(root, "MainSecret.st"), "PROGRAM MainSecret\nEND_PROGRAM\n");
                Git(root, "add -A");
                Git(root, "-c user.name=t -c user.email=t@localhost commit --quiet -m first");
                Git(root, "checkout --quiet -b branch-secret");
                File.WriteAllText(Path.Combine(root, "MainSecret.st"), "PROGRAM MainSecret\r\nEND_PROGRAM\r\n");
                File.WriteAllText(Path.Combine(root, "NewSecret.st"), "x\n");

                var host = new FakeHost();
                host.Agents[7] = (method, _) => new System.Collections.Generic.Dictionary<string, object>
                {
                    { "protocol", Protocol.Version }, { "product", "CODESYS" }, { "product_version", "3.5.22.40" }, { "agent_version", "4.0.0" },
                    { "project", new System.Collections.Generic.Dictionary<string, object> { { "path", Path.Combine(root, "PlantSecret.project") } } },
                };
                var (code, json, _) = Run(host, "diag", root, "--json");
                Assert.Equal(0, code);
                foreach (var name in new[] { "Secret", Path.GetTempPath().TrimEnd('/', '\\'), Environment.UserName })
                    Assert.DoesNotContain(name, json, StringComparison.OrdinalIgnoreCase);
                var folder = (System.Collections.Generic.IDictionary<string, object>)((System.Collections.Generic.IDictionary<string, object>)Json.Parse(json))["folder"];
                Assert.Equal(true, folder["at_repository_root"]);
                Assert.Equal("local false", folder["core.autocrlf"]);
                Assert.Equal("unset", folder["text_attribute"]);
                Assert.Equal(2L, Convert.ToInt64(folder["tracked"]));
                Assert.Equal(1L, Convert.ToInt64(folder["untracked"]));
                Assert.Equal("i/lf w/crlf 1, i/lf w/lf 1", folder["line_endings"]);
                Assert.StartsWith("1 file changed", (string)folder["changed"]);
                Assert.Equal("none", folder["changed_but_cr"]);
                Assert.Equal("branch", folder["head"]);
                Assert.Equal("none", folder["settings"]);

                var (_, text, _) = Run(host, "diag", root);
                Assert.StartsWith("ok diag cts=", text);
                Assert.Contains("folder converts_line_endings: yes\n", text);
                Assert.Contains("agent: ide=CODESYS 3.5.22.40  agent=4.0.0  protocol=" + Protocol.Version + "  64bit=  project_open=yes  ui_busy=no  dialogs=0\n", text);
            }
            finally { Directory.Delete(Path.GetDirectoryName(root), true); }
        }

        static void Git(string folder, string args)
        {
            var run = GitRun.In(folder, args);
            Assert.True(run.ExitCode == 0, args + ": " + run.Error);
        }
    }
}
