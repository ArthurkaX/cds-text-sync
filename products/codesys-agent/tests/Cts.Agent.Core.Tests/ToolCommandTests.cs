using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // The git configuration is a file of the test's own (GIT_CONFIG_GLOBAL),
    // and an installed program an empty file where its installer puts it.
    [Collection("Local command settings")]
    public sealed class ToolCommandTests : IDisposable
    {
        static readonly string[] Variables = { "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA" };
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-tool-" + Guid.NewGuid().ToString("N"));
        readonly Dictionary<string, string> _saved = Variables.ToDictionary(name => name, Environment.GetEnvironmentVariable);
        readonly string _work;

        public ToolCommandTests()
        {
            _work = Path.Combine(_root, "work");
            Directory.CreateDirectory(_work);
            foreach (var name in Variables) Environment.SetEnvironmentVariable(name, null);
            Environment.SetEnvironmentVariable("GIT_CONFIG_GLOBAL", Path.Combine(_root, "gitconfig"));
            Environment.SetEnvironmentVariable("GIT_CONFIG_NOSYSTEM", "1");
            Environment.SetEnvironmentVariable("ProgramFiles", Path.Combine(_root, "pf"));
        }

        public void Dispose()
        {
            foreach (var pair in _saved) Environment.SetEnvironmentVariable(pair.Key, pair.Value);
            try { Directory.Delete(_root, true); } catch (IOException) { }
        }

        [Fact]
        public void NothingInstalledSaysSo()
        {
            var (code, output, _) = Run("tool");
            Assert.Equal(0, code);
            Assert.Equal(new[] { "ok tool compare=none merge=none open=explorer chosen=none", "compare: none installed", "merge: none installed" }, output.Take(3));
        }

        [Fact]
        public void TheInstalledProgramsAreUsedUnchosen()
        {
            Install("KDiff3/bin/kdiff3.exe");
            Install("WinMerge/WinMergeU.exe");
            var data = Data();
            Assert.Equal("-|winmerge|winmerge,kdiff3", Side(data, "compare"));
            Assert.Equal("-|kdiff3|kdiff3,winmerge", Side(data, "merge"));
        }

        [Fact]
        public void GitMergeToolSelectsTheMergeProgram()
        {
            Install("KDiff3/bin/kdiff3.exe");
            Install("WinMerge/WinMergeU.exe");
            GitRun.In(_work, "config --global merge.tool winmerge");
            Assert.Equal("winmerge", ((IDictionary<string, object>)Data()["merge"])["uses"]);
        }

        [Fact]
        public void GitDiffToolWinsOverGitHubDesktop()
        {
            Environment.SetEnvironmentVariable("LOCALAPPDATA", Path.Combine(_root, "local"));
            Directory.CreateDirectory(Path.Combine(_root, "local", "GitHubDesktop"));
            File.WriteAllText(Path.Combine(_root, "local", "GitHubDesktop", "GitHubDesktop.exe"), "");
            Assert.Equal("desktop", ((IDictionary<string, object>)Data()["compare"])["uses"]);
            GitRun.In(_work, "config --global diff.tool kdiff3");
            Assert.Equal("kdiff3", ((IDictionary<string, object>)Data()["compare"])["uses"]);
        }

        [Fact]
        public void MergeToolChoiceIsAnUnknownUse()
        {
            var (code, output, errors) = Run("tool", "merge", "kdiff3");
            Assert.Equal(1, code);
            Assert.Contains("choose open, not merge", string.Join("\n", output) + errors);
        }

        [Fact]
        public void WinMergeShowsTwoFilesTheLeftReadOnlyItsOptionsUnquoted()
        {
            Install("WinMerge/WinMergeU.exe");
            GitRun.In(_work, "config --global merge.tool winmerge");
            var arguments = ConflictTool.Arguments(_work, "C:\\t\\F_Scale.st", "IDE (its edit)", "C:\\a b\\F_Scale.st", "Disk -> IDE: edit, save, close");
            Assert.Equal("/e /u /wl /dl \"IDE (its edit)\" /dr \"Disk -> IDE: edit, save, close\" C:\\t\\F_Scale.st \"C:\\a b\\F_Scale.st\"",
                ProcessArgs.Join(arguments.Skip(1)));
        }

        // value|uses|installed of one side, "-" for no value.
        static string Side(IDictionary<string, object> data, string which)
        {
            var side = (IDictionary<string, object>)data[which];
            return (side["value"] ?? "-") + "|" + side["uses"] + "|" + string.Join(",", (IEnumerable<object>)side["installed"]);
        }

        void Install(string relative)
        {
            var exe = Path.Combine(_root, "pf", relative.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(exe));
            File.WriteAllText(exe, "");
        }


        IDictionary<string, object> Data() => (IDictionary<string, object>)Json.Parse(string.Join("\n", Run("tool", "--json").Output));

        (int Code, IList<string> Output, string Errors) Run(params string[] args)
        {
            var list = args.Where(arg => arg.Length > 0 || args.Length == 3).ToList();
            var output = new StringWriter();
            var errors = new StringWriter();
            var code = CliRun.Run(CliCommands.Find(list), list, null, null, _work, output, errors);
            return (code, output.ToString().Replace("\r\n", "\n").TrimEnd('\n').Split('\n'), errors.ToString());
        }
    }
}
