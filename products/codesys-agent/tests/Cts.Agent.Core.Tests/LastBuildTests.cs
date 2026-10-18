using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    // The agent keeps how the last build ended for the last command in
    // `cts status`.
    public class LastBuildTests
    {
        static Dictionary<string, object> Answer(bool compiled)
        {
            return new Dictionary<string, object>
            {
                { "application", "Application" }, { "compiled", compiled },
                { "project_path", @"C:\work\Line.project" }, { "messages", new List<object>() },
            };
        }

        [Fact]
        public void CountMatchesTheQualifiedSeverityWords()
        {
            int errors, warnings;
            LastBuild.Count(new[] { "Compile Error", "error", "Warning", "Text", null }, out errors, out warnings);
            Assert.Equal(2, errors);
            Assert.Equal(1, warnings);
        }

        [Fact]
        public void ACleanBuildIsOk()
        {
            var record = LastBuild.Record(Answer(true), new[] { "Text", "Information" }, new DateTime(2026, 10, 13, 4, 30, 0, DateTimeKind.Utc));
            Assert.Equal(true, record["ok"]);
            Assert.Equal("build", record["method"]);
            Assert.Equal("2026-10-13T04:30:00Z", record["recorded_at"]);
            Assert.Equal(0, record["errors"]);
        }

        [Fact]
        public void ErrorsAndWarningsAreCountedWhateverTheirCasing()
        {
            var record = LastBuild.Record(Answer(false), new[] { "Error", "Compile Error", "WARNING", "Text" }, DateTime.UtcNow);
            Assert.Equal(false, record["ok"]);
            Assert.Equal(2, record["errors"]);
            Assert.Equal(1, record["warnings"]);
        }

        [Fact]
        public void AFailedCompileIsNotOkEvenWithoutAnErrorMessage()
        {
            Assert.Equal(false, LastBuild.Record(Answer(false), new string[0], DateTime.UtcNow)["ok"]);
        }

        [Fact]
        public void TheBriefIsForTheBuiltProjectOnly()
        {
            var record = LastBuild.Record(Answer(true), new[] { "Warning" }, new DateTime(2026, 10, 13, 4, 30, 0, DateTimeKind.Utc));
            var brief = LastBuild.Brief(record, @"c:\WORK\line.project", DateTime.MinValue);
            Assert.Equal("build", brief["method"]);
            Assert.Equal(true, brief["ok"]);
            Assert.Equal(1, brief["warnings"]);
            Assert.Equal("2026-10-13T04:30:00Z", brief["recorded_at"]);
            Assert.False(brief.ContainsKey("project_path"));
            Assert.False(brief.ContainsKey("changed_after"));
            Assert.Null(LastBuild.Brief(record, @"C:\work\Other.project", DateTime.MinValue));
            Assert.Null(LastBuild.Brief(null, @"C:\work\Line.project", DateTime.MinValue));
        }

        [Fact]
        public void AnObjectChangedInALaterSecondMakesTheBuildOld()
        {
            var built = new DateTime(2026, 10, 13, 4, 30, 0, DateTimeKind.Utc);
            var record = LastBuild.Record(Answer(true), new string[0], built.AddMilliseconds(700));
            Assert.False(LastBuild.Brief(record, @"C:\work\Line.project", built.AddMilliseconds(900)).ContainsKey("changed_after"));
            Assert.Equal(true, LastBuild.Brief(record, @"C:\work\Line.project", built.AddSeconds(1))["changed_after"]);
        }

        [Fact]
        public void StatusSaysWhenObjectsChangedAfterTheLastBuild()
        {
            var last = new Dictionary<string, object> { { "method", "build" }, { "ok", true }, { "errors", 0 }, { "changed_after", true } };
            var details = Cts.Cli.StatusCommands.StatusLine(new Dictionary<string, object> { { "last_command", last }, { "edits_allowed", true } }).Details;
            Assert.Equal(new[] { "last build ok errors=0; objects changed after it, so it says nothing about them: cts build again" }, details);
        }

        [Fact]
        public void StatusSaysWhatUnsavedMeans()
        {
            var details = Cts.Cli.StatusCommands.StatusLine(new Dictionary<string, object> { { "unsaved_changes", true }, { "edits_allowed", true } }).Details;
            Assert.Equal(new[] { "unsaved: the IDE holds edits its project file lacks; cts compare shows whether the folder has them, cts save saves the project" }, details);
        }

        [Fact]
        public void StatusOfAProjectWithoutASyncFolderNamesTheCommand()
        {
            var details = Cts.Cli.StatusCommands.StatusLine(new Dictionary<string, object> { { "project", @"C:\p\a.project" } }).Details;
            Assert.Equal("sync_folder none on this machine: cts set-sync-folder chooses one", details[0]);
            var suggested = Cts.Cli.StatusCommands.StatusLine(new Dictionary<string, object> { { "project", @"C:\p\a.project" }, { "suggested_sync_folder", @"C:\p" } }).Details;
            Assert.Equal(@"sync_folder none on this machine: cts set-sync-folder takes C:\p (a PATH picks another)", suggested[0]);
        }
    }
}
