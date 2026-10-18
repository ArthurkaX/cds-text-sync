using System;
using Cts.Cli;
using System.Collections.Generic;
using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Theory]
        [InlineData("close", "project.close")]
        [InlineData("list", "project.list")]
        public void Project_simple_commands_call_the_agent(string sub, string method)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, name =>
            {
                Assert.Equal(method, name);
                if (method == "project.close") return new Dictionary<string, object> { { "closed", "Demo" } };
                return new Dictionary<string, object>
                {
                    { "count", 2 },
                    { "projects", new List<object>
                        {
                            new Dictionary<string, object> { { "path", "C:/Demo.project" }, { "primary", true } },
                            new Dictionary<string, object> { { "path", "C:/Library.project" }, { "primary", false } },
                        } },
                };
            });
            var output = Run(host, "project", sub).output;
            if (sub == "close") Assert.Equal("ok project-close closed=Demo\nide-1 · no project\n", output);
            else Assert.Equal("ok project-list count=2\nC:/Demo.project (primary)\nC:/Library.project\nide-1 · no project\n", output);
        }

        [Fact]
        public void Project_open_asks_the_agent_to_open_the_file()
        {
            var file = Path.Combine(Path.GetTempPath(), "Plant.project");
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (name, parameters) =>
            {
                Assert.Equal("project.open", name);
                Assert.Equal(file, parameters["path"]);
                return new Dictionary<string, object> { { "opened", file }, { "already_open", true }, { "name", "Plant" } };
            });
            Assert.StartsWith("ok project-open opened=" + Verdict.Quote(file) + " already_open=true\n", Run(host, "project", "open", "--path", file).output);
        }

        [Fact]
        public void Project_open_launch_uses_the_IDE_that_already_has_the_file_open()
        {
            var file = Path.Combine(Path.GetTempPath(), "cts-launch-" + Guid.NewGuid().ToString("N") + ".project");
            File.WriteAllText(file, "");
            try
            {
                var host = new FakeHost();
                host.Agents[7] = Agent(file, null, name => throw new InvalidOperationException("only hello is expected"));
                var (code, output, _) = Run(host, "project", "open", "--path", file, "--launch");
                Assert.Equal(0, code);
                Assert.Equal("ok project-open already_open=true launched=false agent=ide-7 project=" + Verdict.Quote(file) + "\n", output);
            }
            finally { File.Delete(file); }
        }

        [Fact]
        public void Project_open_launch_refuses_a_missing_file()
        {
            var file = Path.Combine(Path.GetTempPath(), "cts-missing-" + Guid.NewGuid().ToString("N") + ".project");
            var (code, output, error) = Run(new FakeHost(), "project", "open", "--path", file, "--launch");
            Assert.Equal(2, code);
            Assert.StartsWith("error project-open cause=refused\n", output);
            Assert.Contains("no project file at " + file, error);
        }

        [Fact]
        public void Project_open_launch_starts_the_newest_CODESYS_with_the_profile_quoted_for_it()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-pf-" + Guid.NewGuid().ToString("N"));
            try
            {
                foreach (var version in new[] { "3.5.9.0", "3.5.22.30", "3.5.20.0" })
                {
                    var common = Path.Combine(root, "CODESYS " + version, "CODESYS", "Common");
                    Directory.CreateDirectory(common);
                    File.WriteAllText(Path.Combine(common, "CODESYS.exe"), "");
                }
                Directory.CreateDirectory(Path.Combine(root, "CODESYS 3.5.23.0"));
                var newest = ProjectOpenCommand.Newest(ProjectOpenCommand.Executables(new[] { root, Path.Combine(root, "absent") }));
                Assert.Equal(Path.Combine(root, "CODESYS 3.5.22.30", "CODESYS", "Common", "CODESYS.exe"), newest);
            }
            finally { Directory.Delete(root, true); }
            // The agent opens the project, so its load dialogs can be answered.
            Assert.Equal("--profile=\"CODESYS V3.5 SP22\" \"--runscript=C:\\S b\\cds-text-sync.py\"",
                ProjectOpenCommand.CommandLine(@"C:\a b\P.project", @"C:\S b\cds-text-sync.py", "CODESYS V3.5 SP22"));
            Assert.Equal("--project=P", ProjectOpenCommand.CommandLine("P", null, null));
        }

        [Fact]
        public void Project_open_launch_passes_the_one_profile_its_installation_ships()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-profile-" + Guid.NewGuid().ToString("N"));
            try
            {
                var common = Path.Combine(root, "CODESYS", "Common");
                var profiles = Path.Combine(root, "CODESYS", "Profiles");
                Directory.CreateDirectory(common);
                Directory.CreateDirectory(profiles);
                var exe = Path.Combine(common, "CODESYS.exe");
                Assert.Null(ProjectOpenCommand.InstallProfile(exe));
                File.WriteAllText(Path.Combine(profiles, "CODESYS V3.5 SP16 Patch 9.profile.xml"), "");
                File.WriteAllText(Path.Combine(profiles, "GLOBAL.dependencies"), "");
                Assert.Equal("CODESYS V3.5 SP16 Patch 9", ProjectOpenCommand.InstallProfile(exe));
                File.WriteAllText(Path.Combine(profiles, "Other.profile.xml"), "");
                Assert.Null(ProjectOpenCommand.InstallProfile(exe));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Project_open_launch_takes_the_first_installed_stub()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-sd-" + Guid.NewGuid().ToString("N"));
            try
            {
                var second = Path.Combine(root, "machine");
                Directory.CreateDirectory(Path.Combine(second, "cds-text-sync"));
                File.WriteAllText(Path.Combine(second, "cds-text-sync", "cds-text-sync.py"), "");
                var dirs = new[] { Path.Combine(root, "user"), second };
                Assert.Equal(Path.Combine(second, "cds-text-sync", "cds-text-sync.py"), ProjectOpenCommand.InstalledStub(dirs));
                Assert.Null(ProjectOpenCommand.InstalledStub(new[] { Path.Combine(root, "user") }));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Project_simulation_requires_a_mode_and_online_refusal_names_the_command()
        {
            var usageHost = new FakeHost();
            usageHost.Agents[1] = Agent(null, null, method => throw new InvalidOperationException("agent call not expected"));
            var (usageCode, usageOutput, _) = Run(usageHost, "project", "simulate");
            Assert.Equal(2, usageCode);
            Assert.StartsWith("error project-simulate cause=usage\n", usageOutput);

            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => throw new ProtocolException("bad_params", "refused: the project is online"));
            var (_, refusal, _) = Run(host, "project", "simulate", "on");
            Assert.Contains("repeat `cts project simulate`", refusal);
        }

        [Fact]
        public void Project_device_commands_build_the_shared_device_verdict()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (name, parameters) =>
            {
                Assert.Equal("project.devices", name);
                if (parameters.ContainsKey("device")) Assert.Equal("PLC", parameters["device"]);
                return new Dictionary<string, object>
                {
                    { "devices", new List<object> { new Dictionary<string, object>
                        {
                            { "name", "PLC" }, { "simulation", true },
                            { "description", new Dictionary<string, object> { { "type", 4102 }, { "id", "0000 0005" }, { "version", "4.11.0.0" } } },
                            { "applications", new List<object> { new Dictionary<string, object>
                                { { "name", "App" }, { "active", true }, { "online", true }, { "application_state", "run" } } } },
                        } } },
                };
            });
            Assert.StartsWith("ok project-list-devices devices=1 online=1\nPLC [4102 \"0000 0005\" 4.11.0.0] simulation App*=run\n", Run(host, "project", "list-devices").output);
            Assert.StartsWith("ok project-list-devices devices=1 online=1\n", Run(host, "project", "list-devices", "--device", "PLC").output);
        }

        [Theory]
        [InlineData("on", true)]
        [InlineData("off", false)]
        public void Project_simulation_requires_mode_and_sends_enable(string mode, bool enabled)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (name, parameters) =>
            {
                Assert.Equal("project.simulation", name);
                Assert.Equal(enabled, parameters["enable"]);
                return new Dictionary<string, object>
                {
                    { "device", "PLC" }, { "simulation", enabled }, { "before", !enabled },
                    { "after", enabled }, { "saved", true },
                };
            });
            Assert.StartsWith("ok project-simulate device=PLC simulation=" + enabled.ToString().ToLowerInvariant()
                + " changed=true saved=true\n", Run(host, "project", "simulate", mode).output);
        }

        [Fact]
        public void Project_credentials_require_username_and_never_print_password()
        {
            IDictionary<string, object> received = null;
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (name, parameters) =>
            {
                Assert.Equal("project.credentials", name);
                received = parameters;
                return new Dictionary<string, object> { { "username", "operator" }, { "credentials_set", true } };
            });
            var output = Run(host, "project", "set-credentials", "--username", "operator", "--password", "secret").output;
            Assert.Equal("operator", received["username"]);
            Assert.Equal("secret", received["password"]);
            Assert.DoesNotContain("secret", output);
            Assert.StartsWith("ok project-set-credentials username=operator\n", output);
        }
    }
}
