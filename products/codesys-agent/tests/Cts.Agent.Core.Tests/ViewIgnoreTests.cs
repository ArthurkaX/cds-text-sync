using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    // An engineer leaves parts of the project to its owner with Git's ignore
    // rules: export, compare and import leave those files as they are.
    [Collection("Local command settings")]
    public sealed class ViewIgnoreTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-view-ignore-" + Guid.NewGuid().ToString("N"));
        readonly string _oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
        readonly string _snapshot = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml");
        const string Tasks = "project-view/PLC_Stabur/Plc Logic/Application/Task Configuration";
        const string Valve = "project-view/PLC_Stabur/Plc Logic/Application/FB_Valve.st";

        public ViewIgnoreTests()
        {
            Directory.CreateDirectory(_root);
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
            Git("init --quiet");
            File.Copy(Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "cds-text-sync.json"), Path.Combine(_root, "cds-text-sync.json"));
            ExportCommand.WriteToDisk(_snapshot, _root, "C:\\projects\\demo.project", false);
            // The owner's task cycle, other than this IDE's, pulled after the last sync.
            var task = Path.Combine(_root, Tasks, "Task.xml");
            File.WriteAllText(task, File.ReadAllText(task).Replace("</Single>", "</Single><!-- owner -->"));
            Git("add -A");
            Git("-c user.name=Fixture -c user.email=fixture@localhost commit -qm \"the owner's export\"");
        }

        public void Dispose()
        {
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", _oldXdg);
            Directory.Delete(_root, true);
        }

        [Fact]
        public void AnExportLeavesWhatTheRulesMatchAsItIs()
        {
            var owners = File.ReadAllText(Path.Combine(_root, Tasks, "Task.xml"));
            File.Delete(Path.Combine(_root, Valve));
            Exclude("**/Task Configuration/", "FB_Valve.st");

            var result = ExportCommand.WriteToDisk(_snapshot, _root, "C:\\projects\\demo.project", false);

            Assert.Equal(owners, File.ReadAllText(Path.Combine(_root, Tasks, "Task.xml")));
            Assert.False(File.Exists(Path.Combine(_root, Valve)));
            Assert.Empty(result.PendingImport);
            Assert.Empty(result.KeptOrphans);
            Assert.Equal(new[] { "FB_Valve.st", ".cds-object.xml", "Task.xml", "VISU_TASK.xml" }.OrderBy(name => name), result.Ignored.Select(Path.GetFileName).OrderBy(name => name));
            Assert.DoesNotContain(result.Natives, native => result.Ignored.Contains(native.Path));
        }

        [Fact]
        public void ACompareDoesNotReportWhatTheRulesMatch()
        {
            File.Delete(Path.Combine(_root, Valve));
            Exclude("**/Task Configuration/", "FB_Valve.st");

            var result = Compare();

            var summary = (IDictionary<string, object>)result["summary"];
            Assert.Equal(0, Convert.ToInt32(summary["deleted"]));
            Assert.Equal(0, Convert.ToInt32(summary["modified"]));
            Assert.False(summary.ContainsKey("ide_changed"));
            Assert.Contains(ViewIgnore.Note(4), (IEnumerable<string>)result["info"]);
        }

        [Fact]
        public void WithoutRulesTheOwnersChangeIsADifference()
        {
            var summary = (IDictionary<string, object>)Compare()["summary"];

            Assert.Equal(1, Convert.ToInt32(summary["modified"]));
        }

        [Fact]
        public void OnceTheRuleGoesTheImportCarriesTheOwnersFile()
        {
            Exclude("**/Task Configuration/");
            ExportCommand.WriteToDisk(_snapshot, _root, "C:\\projects\\demo.project", false);
            File.WriteAllText(Path.Combine(_root, ".git", "info", "exclude"), "");

            var objects = (IDictionary<string, object>)Compare()["objects"];

            Assert.Equal("Task.xml", Path.GetFileName(Convert.ToString(((IEnumerable<IDictionary<string, object>>)objects["modified"]).Single()["path"])));
            Assert.False(objects.ContainsKey("ide_changed"));
        }

        // The owner's Task.xml is ignored but not the IDE's: the line names it.
        [Fact]
        public void ACompareNamesAnIgnoredFileTheIdeHoldsOtherwise()
        {
            Exclude("**/Task Configuration/");

            var info = (IEnumerable<string>)Compare()["info"];

            Assert.Contains(ViewIgnore.StaleNote(new[] { "PLC_Stabur/Plc Logic/Application/Task Configuration/Task.xml" }), info);
        }

        [Fact]
        public void IncludeIgnoredComparesThatFileLikeAnyOther()
        {
            Exclude("**/Task Configuration/Task.xml");

            var result = Compare("import", "--include-ignored", Path.Combine(_root, Tasks, "Task.xml"));

            var objects = (IDictionary<string, object>)result["objects"];
            Assert.Equal("Task.xml", Path.GetFileName(Convert.ToString(((IEnumerable<IDictionary<string, object>>)objects["modified"]).Single()["path"])));
            Assert.False(result.ContainsKey("info"));
        }

        [Fact]
        public void IncludeIgnoredRefusesAFileTheRulesDoNotMatch()
        {
            var refused = Assert.Throws<CliFailure>(() => Compare("import", "--include-ignored", Path.Combine(_root, Valve)));

            Assert.Contains("FB_Valve.st is not a file of the view that Git's ignore rules match; cts import carries it without --include-ignored", refused.Message);
        }

        // Linux keeps both spellings apart; Windows would hold them as one folder.
        [Fact]
        public void FoldersThatDifferOnlyInCaseAreNamedOncePerPair()
        {
            var twin = Path.Combine(_root, "project-view", "PLC_Stabur", "PLC Logic", "Application");
            Directory.CreateDirectory(twin);
            File.WriteAllText(Path.Combine(twin, "notes.txt"), "old spelling");
            Git("add -A");

            Assert.Equal(new[] { "project-view/PLC_Stabur/PLC Logic and project-view/PLC_Stabur/Plc Logic" }, ComparePlanner.CaseTwins(_root, "project-view"));
            Assert.Empty(ComparePlanner.CaseTwins(_root, "project-view/PLC_Stabur/Plc Logic"));
        }

        [Fact]
        public void ARuleOverTheApplicationIsRefused()
        {
            Exclude("**/Application/");

            var refused = Assert.Throws<InvalidOperationException>(() => ExportCommand.WriteToDisk(_snapshot, _root, "C:\\projects\\demo.project", false));

            Assert.StartsWith("Git's ignore rules cover the application PLC_Stabur/Plc Logic/Application/; nothing was done", refused.Message);
            Assert.Contains("<!-- owner -->", File.ReadAllText(Path.Combine(_root, Tasks, "Task.xml")));
        }

        [Fact]
        public void ARuleOverAFolderButNotWhatIsBelowItIsRefused()
        {
            Exclude("**/Task Configuration/.cds-object.xml");

            var refused = Assert.Throws<CliFailure>(() => Compare());

            Assert.Contains("leave out a folder object but not what is below it: PLC_Stabur/Plc Logic/Application/Task Configuration/Task.xml, "
                + "PLC_Stabur/Plc Logic/Application/Task Configuration/VISU_TASK.xml; nothing was done", refused.Message);
        }

        // The base keeps an ignored file's entry, but for one the import
        // carried into the IDE: that one the IDE now holds as the disk does.
        [Fact]
        public void TheBaseTakesAnIgnoredFileOnlyWhenTheImportCarriedIt()
        {
            const string task = Tasks + "/Task.xml";
            SyncBase.Record(_root, "project-view", new List<string>());
            var synced = Git("rev-parse refs/cts/base:\"" + task + "\"");
            Exclude("**/Task Configuration/");
            File.AppendAllText(Path.Combine(_root, task), "<!-- carried -->");

            SyncBase.Record(_root, "project-view", new List<string>());
            Assert.Equal(synced, Git("rev-parse refs/cts/base:\"" + task + "\""));

            SyncBase.Record(_root, "project-view", new List<string>(), null, new HashSet<string>(new[] { task }, StringComparer.OrdinalIgnoreCase));
            Assert.Equal(Git("hash-object \"" + task + "\""), Git("rev-parse refs/cts/base:\"" + task + "\""));
        }

        void Exclude(params string[] rules)
        {
            File.AppendAllText(Path.Combine(_root, ".git", "info", "exclude"), string.Concat(rules.Select(rule => rule + "\n")));
        }

        IDictionary<string, object> Compare() => Compare("compare", "--full");

        IDictionary<string, object> Compare(string verb, params string[] args)
        {
            var command = CliCommands.Find(new[] { verb });
            var options = CliOptions.Parse(new[] { verb, "--sync-folder", _root }.Concat(args).ToArray(), null, command);
            var hello = new Hello(42, new Dictionary<string, object>
            {
                { "project", new Dictionary<string, object> { { "path", "C:\\projects\\demo.project" }, { "sync_folder", _root } } },
            });
            return ComparePlanner.Plan(new CliCall(command, options, hello, 30, (method, args) =>
            {
                Assert.Equal("project.export", method);
                File.Copy(_snapshot, Convert.ToString(args["path"]), true);
                return new Dictionary<string, object>();
            }));
        }

        string Git(string args) => GitRepository.Run(_root, args).Trim();
    }
}
