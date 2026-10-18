using System;
using System.Collections.Generic;
using System.IO;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public class CliHeadlessCrcTests : IDisposable
    {
        readonly string folder = Path.Combine(Path.GetTempPath(), "cts-crc-" + Guid.NewGuid().ToString("N"));

        public CliHeadlessCrcTests()
        {
            Directory.CreateDirectory(folder);
        }

        public void Dispose()
        {
            Directory.Delete(folder, true);
        }

        static CliOptions Options(params (string Key, object Value)[] values)
        {
            var options = new CliOptions();
            foreach (var (key, value) in values) options.Params[key] = value;
            return options;
        }

        [Fact]
        public void A_single_target_names_the_credential_variables_not_their_values()
        {
            Environment.SetEnvironmentVariable("CDS_CRC_PLC_USERNAME", "private-user");
            Environment.SetEnvironmentVariable("CDS_CRC_PLC_PASSWORD", "private-password");
            try
            {
                var target = (IDictionary<string, object>)HeadlessCrcCommand.Targets(Options(("ip", "192.0.2.4")))[0];

                var credentials = (IDictionary<string, object>)target["credentials"];
                Assert.Equal(("CDS_CRC_PLC_USERNAME", "CDS_CRC_PLC_PASSWORD"), (credentials["username_env"], credentials["password_env"]));
                var request = Json.Serialize(target);
                Assert.DoesNotContain("private-user", request);
                Assert.DoesNotContain("private-password", request);
            }
            finally
            {
                Environment.SetEnvironmentVariable("CDS_CRC_PLC_USERNAME", null);
                Environment.SetEnvironmentVariable("CDS_CRC_PLC_PASSWORD", null);
            }
        }

        [Fact]
        public void A_batch_row_gets_the_defaults_it_does_not_set()
        {
            var input = Path.Combine(folder, "targets.json");
            File.WriteAllText(input, "{\"targets\": [{\"ip\": \"192.0.2.1\"}, {\"ip\": \"192.0.2.2\", \"gateway\": \"Gateway-2\"}, \"bad row\"]}");

            var targets = HeadlessCrcCommand.Targets(Options(("input", input), ("application", "App")));

            var first = (IDictionary<string, object>)targets[0];
            Assert.Equal(("Gateway-1", "1", "App"), (first["gateway"], first["request_id"], first["application"]));
            Assert.Equal("Gateway-2", ((IDictionary<string, object>)targets[1])["gateway"]);
            Assert.Equal("bad row", ((IDictionary<string, object>)targets[2])["value"]);
        }

        [Fact]
        public void An_empty_batch_or_no_target_is_refused()
        {
            var input = Path.Combine(folder, "targets.json");
            File.WriteAllText(input, "[]");

            Assert.Throws<ArgumentException>(() => HeadlessCrcCommand.Targets(Options(("input", input))));
            Assert.Throws<ArgumentException>(() => HeadlessCrcCommand.Targets(Options()));
        }

        [Fact]
        public void The_script_comes_from_the_host_root_and_the_profile_is_the_newest_beside_the_ide()
        {
            var script = Path.Combine(folder, "host", "headless", "plc_crc.py");
            Directory.CreateDirectory(Path.GetDirectoryName(script));
            File.WriteAllText(script, "");
            var exe = Path.Combine(folder, "IDE", "CODESYS", "Common", "CODESYS.exe");
            var profiles = Path.Combine(folder, "IDE", "CODESYS", "Profiles");
            Directory.CreateDirectory(Path.GetDirectoryName(exe));
            Directory.CreateDirectory(profiles);
            File.WriteAllText(Path.Combine(profiles, "Vendor 1.2.profile.xml"), "");
            File.WriteAllText(Path.Combine(profiles, "Vendor 1.10.profile.xml"), "");

            Assert.Equal(script, HeadlessCrcCommand.Script(Path.Combine(folder, "host")));
            Assert.Equal("Vendor 1.10", HeadlessCrcCommand.Profile(exe));
        }

        [Fact]
        public void A_run_without_a_result_file_reports_the_ide_stderr()
        {
            var ide = new HeadlessCrcCommand.Ide { Exe = "CODESYS.exe", Profile = "P" };

            var payload = HeadlessCrcCommand.Result(null, "  bad IDE\n", 7, ide);

            Assert.Equal(false, payload["ok"]);
            Assert.Equal(("ide_failed", "bad IDE"), (((IDictionary<string, object>)payload["error"])["code"], ((IDictionary<string, object>)payload["error"])["message"]));
            Assert.Equal(7, ((IDictionary<string, object>)payload["process"])["returncode"]);
            Assert.Equal("CODESYS.exe", ((IDictionary<string, object>)payload["host"])["exe"]);
        }

        [Fact]
        public void A_watch_needs_an_output_and_refuses_an_existing_control_file()
        {
            var output = Path.Combine(folder, "crc.jsonl");

            Assert.Throws<ArgumentException>(() => HeadlessCrcCommand.WatchPaths("", ""));
            Assert.Equal(output + ".control.json", HeadlessCrcCommand.WatchPaths(output, "").Control);
            File.WriteAllText(output + ".control.json", "{}");
            Assert.Throws<ArgumentException>(() => HeadlessCrcCommand.WatchPaths(output, ""));
        }

        [Fact]
        public void A_bad_number_of_seconds_is_an_invalid_request()
        {
            var (code, output, _) = CliTests.RunLocal("plc-crc-headless", "--ip", "192.0.2.4", "--timeout", "soon");

            Assert.Equal(2, code);
            Assert.Contains("\"invalid_request\"", output);
            Assert.Contains("--timeout must be a number of seconds", output);
        }
    }
}
