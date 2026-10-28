using System;
using System.Collections.Generic;
using System.IO;
using Xunit;
using Cts.Cli;

namespace Cts.Agent.Core.Tests
{
    [CollectionDefinition("Local command settings", DisableParallelization = true)]
    public sealed class LocalCommandSettingsCollection { }

    [Collection("Local command settings")]
    public sealed class LocalCommandsTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-local-" + Guid.NewGuid().ToString("N"));
        readonly string _oldConfig = Environment.GetEnvironmentVariable("XDG_CONFIG_HOME");

        public LocalCommandsTests()
        {
            Directory.CreateDirectory(_root);
            Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", Path.Combine(_root, "config"));
        }

        [Fact]
        public void Guide_is_bundled_and_unknown_config_action_is_not_a_local_command()
        {
            var args = new List<string> { "guide", "visu-svg", "--file", "examples/pid-schematic.svg" };
            var command = CliCommands.Find(args);
            Assert.NotNull(command);
            var options = CliOptions.Parse(args, null, command);
            var answer = LocalCommands.Guide(options);
            Assert.Contains("<svg", (string)answer["text"]);
            Assert.Null(CliCommands.Find(new List<string> { "config", "ui" }));
            Assert.Null(CliCommands.Find(new List<string> { "config" }));
            Assert.Equal("config-show", CliCommands.Find(new List<string> { "config", "show" }).Verb);
        }

        [Fact]
        public void Config_keeps_the_quick_key_in_the_user_file_alone()
        {
            var initialShow = LocalCommands.ConfigShow();
            Assert.Equal("missing", ((IDictionary<string, object>)initialShow["user_defaults"])["status"]);
            Run("config", "show");
            Assert.False(File.Exists(Path.Combine(_root, "config", "cds-text-sync", "defaults.json")));
            Assert.StartsWith("ok config-set key=quick_key value=Ctrl+Shift+Q", Run("config", "set", "quick_key", "ctrl+shift+q"));
            var key = (IDictionary<string, object>)((IDictionary<string, object>)LocalCommands.ConfigShow()["settings"])["quick_key"];
            Assert.Equal("Ctrl+Shift+Q", key["value"]);
            Assert.Equal("user", key["source"]);
            var refused = Cts.Agent.Tests.CliTests.RunLocal("config", "set", "projections", "{}");
            Assert.Equal(1, refused.code);
            Assert.Contains("unknown setting: projections. The one setting is quick_key", refused.output + refused.error);
            Assert.Contains("ok config-unset key=quick_key removed=true", Run("config", "unset", "quick_key"));
            Assert.Equal("code", ((IDictionary<string, object>)((IDictionary<string, object>)LocalCommands.ConfigShow()["settings"])["quick_key"])["source"]);
        }

        [Fact]
        public void Local_commands_print_verdicts_and_json_payloads()
        {
            var index = Run("guide");
            Assert.StartsWith("ok guide rules=5 topics=12", index);
            Assert.Contains("Rules:", index);
            Assert.True(index.IndexOf("Common jobs:", StringComparison.Ordinal) < index.IndexOf("Topics:", StringComparison.Ordinal));
            Assert.Contains("Run ST unit tests: cts test", index);
            Assert.Contains("skip cts import when cts compare is clean", index);
            Assert.Contains("  - Change code: edit the .st files", index);
            Assert.Contains("  visu-svg ", index);
            var help = string.Join(" ", Run("guide", "--help").Split((char[])null, StringSplitOptions.RemoveEmptyEntries));
            Assert.Contains("Topics: ", help);
            Assert.Contains(", visu-svg", help);
            var guideJson = Run("guide", "compare", "--json");
            Assert.StartsWith("{", guideJson);
            Assert.Contains("\"topic\": \"compare\"", guideJson);
            Assert.Contains("ok guide topic=compare", Run("guide", "compare"));
            Assert.Contains("## Folder and IDE Synchronization", Run("guide", "compare"));
            Assert.DoesNotContain("## PLC Lifecycle", Run("guide", "compare"));
            Assert.Contains("\n  Compare tools  ", Run("guide", "compare"));
            Assert.Contains("### Compare tools", Run("guide", "compare", "--section", "Compare tools"));
            var save = Run("guide", "save");
            Assert.Contains("`cts save` persists", save);
            Assert.DoesNotContain("### Import", save);
            var args = new List<string> { "guide", "conflicts" };
            var error = new StringWriter();
            Assert.Equal(1, CliRun.Run(CliCommands.Find(args), args, null, null, _root, new StringWriter(), error));
            Assert.Contains("unknown guide topic 'conflicts'; the guides that mention conflict: ", error.ToString());
            Assert.Contains("import", error.ToString());
            Assert.StartsWith("ok config-show keys=1", Run("config", "show"));
            Assert.Contains("\"settings\"", Run("config", "show", "--json"));
        }

        [Fact]
        public void A_long_guide_prints_its_opening_and_a_map_and_a_section_on_request()
        {
            var opening = Run("guide", "visu-svg");
            Assert.StartsWith("ok guide topic=visu-svg", opening);
            Assert.Contains("shown=opening", opening);
            Assert.Contains("## Short path", opening);
            Assert.DoesNotContain("## Layout rules\n", opening);
            Assert.Contains("\n  Layout rules  ", opening);
            Assert.Contains("\n      Approval rule  ", opening);
            Assert.Contains("Next: cts guide visu-svg --section \"<title>\"", opening);
            Assert.True(opening.Length < 6000);
            var section = Run("guide", "visu-svg", "--section", "layout rules");
            Assert.StartsWith("ok guide topic=visu-svg section=\"Layout rules\"", section);
            Assert.Contains("## Layout rules", section);
            Assert.DoesNotContain("## Colour classes", section);
            var withSubsections = Run("guide", "visu-svg", "--section", "GVL variable declarations");
            Assert.Contains("### What must be declared", withSubsections);
            Assert.DoesNotContain("## Text & Text-IDs", withSubsections);
            Assert.Contains("## Example — Pump Station sketch", Run("guide", "visu-svg", "--all"));
            Assert.Contains("\"sections\"", Run("guide", "visu-svg", "--json"));
            Assert.DoesNotContain("shown=opening", Run("guide", "workflow"));
            var args = new List<string> { "guide", "visu-svg", "--section", "Example" };
            var error = new StringWriter();
            Assert.Equal(1, CliRun.Run(CliCommands.Find(args), args, null, null, _root, new StringWriter(), error));
            Assert.Contains("'Example' matches 2 sections of guide visu-svg; its sections: Example — GVL_HMI.st", error.ToString());
        }

        [Fact]
        public void A_json_failure_carries_its_message_and_next_line()
        {
            var args = new List<string> { "guide", "conflicts", "--json" };
            var output = new StringWriter();
            Assert.Equal(1, CliRun.Run(CliCommands.Find(args), args, null, null, _root, output, new StringWriter()));
            var answer = (IDictionary<string, object>)Json.Parse(output.ToString());
            Assert.Equal(false, answer["ok"]);
            Assert.StartsWith("unknown guide topic 'conflicts'", (string)answer["message"]);
            Assert.Equal("cts guide --help", answer["next"]);
        }

        string Run(params string[] values)
        {
            var args = new List<string>(values);
            var command = CliCommands.Find(args);
            Assert.NotNull(command);
            var output = new StringWriter();
            var error = new StringWriter();
            var code = CliRun.Run(command, args, null, null, _root, output, error);
            Assert.Equal(0, code);
            Assert.Equal("", error.ToString());
            return output.ToString();
        }

        public void Dispose()
        {
            Environment.SetEnvironmentVariable("XDG_CONFIG_HOME", _oldConfig);
            try { Directory.Delete(_root, true); } catch (IOException) { }
        }
    }
}
