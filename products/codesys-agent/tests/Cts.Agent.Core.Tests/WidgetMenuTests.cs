using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // The quick widget's menu: fixed digits, greyed items with a reason, and
    // one line for what a cts run came to.
    public class WidgetMenuTests
    {
        static readonly string[] Deny = DenyRules.DefaultDeny;

        [Fact]
        public void NoProjectOffersKnownProjectsFilePickerSettingsAndUsefulMoreRows()
        {
            var known = new List<KnownProject>
            {
                new KnownProject { Id = "owner", Name = "Alpha", Folder = "C:\\alpha", Owner = true },
                new KnownProject { Id = "colleague", Name = "Beta", Folder = "C:\\beta", Owner = false },
                new KnownProject { Id = "empty", Name = "Gamma", Folder = "C:\\empty", Owner = true },
            };
            var files = new Dictionary<string, string> { { "owner", "C:\\alpha\\main.project" }, { "colleague", "C:\\beta\\main.project" } };
            var items = WidgetMenu.NoProject(known, files, 7);
            Assert.Equal("123780", new string(items.Select(item => item.Key).ToArray()));
            Assert.Equal("Alpha", items[0].Label);
            Assert.Equal("C:\\alpha", items[0].Hint);
            Assert.Equal("C:\\alpha\\main.project", items[0].OpensProject);
            Assert.Equal(new[] { "project", "update" }, items[1].Args);
            Assert.Equal("C:\\beta", items[1].WorkingFolder);
            Assert.Null(items[2].Args);
            Assert.Equal("no project file in its repository", items[2].Disabled);
            Assert.Equal("any .project file", items[3].Hint);
            Assert.True(items[3].PicksProject);
            Assert.Null(items[4].Disabled);
            Assert.Equal(new[] { "Agent activity", "Copy the line for an AI agent" }, items[5].Choices.Select(row => row.Label));
            Assert.All(items[5].Choices, row => Assert.Null(row.Disabled));
        }

        [Fact]
        public void NoProjectCapsKnownProjectsAtSixAndSettingsDisableOnlyTheSyncFolder()
        {
            var known = Enumerable.Range(1, 8).Select(i => new KnownProject
            {
                Id = i.ToString(), Name = "Project " + i, Folder = "C:\\p" + i,
            }).ToList();
            var items = WidgetMenu.NoProject(known, new Dictionary<string, string>(), 7);
            Assert.Equal(6, items.Count(item => item.Key >= '1' && item.Key <= '6'));
            var settings = WidgetMenu.NoProjectSettings(
                "{\"compare\": {\"uses\": \"desktop\", \"installed\": []}, \"merge\": {\"uses\": \"desktop\", \"installed\": []}}",
                "{\"settings\": {\"quick_key\": {\"value\": \"Alt+Q\", \"source\": \"user\", \"scope\": \"user\"}}}");
            Assert.Equal("open a project first", settings[0].Disabled);
            Assert.Null(settings[1].Disabled);
        }

        [Fact]
        public void TheDigitsNeverMoveWhateverCanRun()
        {
            foreach (var online in new[] { false, true })
                foreach (var folder in new[] { "", "C:\\work" })
                    foreach (var owner in new[] { false, true })
                        Assert.Equal("123456780", new string(WidgetMenu.Items(online, folder, 7, "plant", owner).Select(item => item.Key).ToArray()));
        }

        [Theory]
        [InlineData(true)]
        [InlineData(false)]
        public void WhileACompareRunsOnlyTheSettingsAndTheMorePageStayOpen(bool owner)
        {
            var items = WidgetMenu.Items(false, "C:\\work", 7, "plant", owner);
            Assert.Equal("123456", new string(items.Where(WidgetMenu.WaitsForCompare).Select(item => item.Key).ToArray()));
            Assert.All(WidgetMenu.ForKey(items, '0').Choices, row => Assert.False(WidgetMenu.WaitsForCompare(row)));
        }

        [Fact]
        public void OnlineOnlyWhatWritesTheIdeIsGreyed()
        {
            var items = WidgetMenu.Items(true, "C:\\work", 7, "plant", false);
            Assert.Equal(new[] { '1', '6' }, items.Where(item => item.Disabled == WidgetMenu.Online).Select(item => item.Key));
            Assert.All(items.Where(item => item.Key != '1' && item.Key != '6'), item => Assert.Null(item.Disabled));
            Assert.Equal("on disk", WidgetMenu.ForKey(items, '4').Hint);
            Assert.Equal(WidgetPage.Branches, WidgetMenu.ForKey(items, '4').Opens);
            Assert.Equal(WidgetPage.Compare, WidgetMenu.ForKey(items, '3').Opens);
            Assert.Equal(new[] { "import", "--tool" }, WidgetMenu.ForKey(items, '1').Args);
            Assert.Equal(new[] { "open" }, WidgetMenu.ForKey(items, '7').Args);
        }

        [Fact]
        public void TheOpenRowNamesTheProgramCtsToolSaysItStarts()
        {
            var items = WidgetMenu.Items(false, "C:\\work", 7, "plant", false);
            Assert.Equal("Open the project folder", WidgetMenu.ForKey(items, '7').Label);
            Assert.False(WidgetMenu.NameOpener(items, "not json"));
            Assert.True(WidgetMenu.NameOpener(items, "{\"open\": {\"value\": null, \"uses\": \"zed\", \"installed\": [\"zed\", \"explorer\"]}}"));
            Assert.Equal("Open in Zed", WidgetMenu.ForKey(items, '7').Label);
            WidgetMenu.NameOpener(items, "{\"open\": {\"value\": \"C:\\\\Tools\\\\Fork\\\\Fork.exe\", \"uses\": \"C:\\\\Tools\\\\Fork\\\\Fork.exe\", \"installed\": []}}");
            Assert.Equal("Open in Fork", WidgetMenu.ForKey(items, '7').Label);
        }

        [Fact]
        public void OneAndTwoMergeAndShiftMakesOneSideTheOther()
        {
            var items = WidgetMenu.Items(false, "C:\\work", 7, "plant", false);
            Assert.Equal(new[] { "import", "--tool" }, WidgetMenu.ForKey(items, '1').Args);
            Assert.Equal(new[] { "export", "--tool" }, WidgetMenu.ForKey(items, '2').Args);
            Assert.Equal(new[] { "import", "--force" }, WidgetMenu.ForKey(items, '1').Forced);
            Assert.Equal(new[] { "export", "--force" }, WidgetMenu.ForKey(items, '2').Forced);
            Assert.Equal("Shift: the disk wins, no merge", WidgetMenu.ForKey(items, '1').Hint);
            Assert.All(items.Where(item => item.Key != '1' && item.Key != '2'), item => Assert.Null(item.Forced));
        }

        [Fact]
        public void TheComparePageOpensTheIdeAgainstTheDiskOrABranch()
        {
            var items = WidgetMenu.Comparisons(new[] { "feature/valve", "master", "" }, "master");
            Assert.Equal(new[] { "Disk", "feature/valve", "master" }, items.Select(item => item.Label));
            Assert.Equal("123", new string(items.Select(item => item.Key).ToArray()));
            Assert.Equal(new[] { "compare", "--tool" }, items[0].Args);
            Assert.Equal(new[] { "compare", "--tool", "--against", "feature/valve" }, items[1].Args);
            Assert.Equal("branch", items[1].Hint);
            Assert.True(items[2].Current);
            Assert.Equal("last commit", items[2].Hint);
            Assert.All(items, item => Assert.Null(item.Disabled));

            var many = WidgetMenu.Comparisons(Enumerable.Range(1, 20).Select(i => "b" + i), null);
            Assert.Equal(WidgetMenu.MaxBranches + 1, many.Count);
            Assert.Equal('9', many[8].Key);
            Assert.Equal('\0', many[9].Key);
        }

        [Fact]
        public void WithoutASyncFolderOnlyTheSettingsAndTheMorePageRun()
        {
            var items = WidgetMenu.Items(true, "", 7, "plant", false);
            Assert.Equal(new[] { '8', '0' }, items.Where(item => item.Disabled == null).Select(item => item.Key));
            Assert.Equal(WidgetPage.Settings, WidgetMenu.ForKey(items, '8').Opens);
            Assert.Equal("set the sync folder", WidgetMenu.ForKey(items, '8').Hint);
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(items, '1').Disabled);
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(items, '6').Disabled);
            var more = WidgetMenu.ForKey(items, '0').Choices;
            Assert.All(more.Where(item => item.Key != '5'), item => Assert.Null(item.Disabled));
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(more, '5').Disabled);
        }

        [Fact]
        public void ZeroOpensFormatActivityTheAgentLineAndTheFsmMap()
        {
            var more = WidgetMenu.ForKey(WidgetMenu.Items(false, "C:\\work", 6128, "example_lib", false), '0');
            Assert.Null(more.Args);
            Assert.Equal(WidgetPage.More, more.Opens);
            Assert.Equal("12345", new string(more.Choices.Select(item => item.Key).ToArray()));
            Assert.Equal(WidgetPage.Format, WidgetMenu.ForKey(more.Choices, '1').Opens);
            Assert.Equal(WidgetPage.Activity, WidgetMenu.ForKey(more.Choices, '2').Opens);
            Assert.Equal(WidgetPage.Fsm, WidgetMenu.ForKey(more.Choices, '4').Opens);
            var analysis = WidgetMenu.ForKey(more.Choices, '5');
            Assert.Equal("Static analysis", analysis.Label);
            Assert.Equal(WidgetPage.StaticAnalysis, analysis.Opens);
            Assert.Equal("cts analyze, window", analysis.Hint);
            var closed = WidgetMenu.ForKey(WidgetMenu.Items(false, "C:\\work", 5, "", false), '0').Choices;
            Assert.Equal("no project is open", WidgetMenu.ForKey(closed, '1').Disabled);
            Assert.Equal("no project is open", WidgetMenu.ForKey(closed, '4').Disabled);
            Assert.Null(WidgetMenu.ForKey(closed, '5').Disabled);
        }

        [Fact]
        public void TheAgentLinePointsAnAiAgentAtThisIde()
        {
            var row = Line(6128, "example_lib");
            Assert.Equal("!cts --target ide-6128 --expect-project example_lib --help", row.Copies);
            Assert.Equal("ide-6128 · example_lib", row.Hint);
            Assert.Null(row.Args);
            Assert.Equal(WidgetPage.None, row.Opens);

            Assert.Equal("!cts --target ide-5 --expect-project \"my plant\" --help", Line(5, "my plant").Copies);
            var none = Line(5, "");
            Assert.Equal("!cts --target ide-5 --help", none.Copies);
            Assert.Equal("ide-5", none.Hint);
        }

        static WidgetItem Line(int pid, string project)
        {
            return WidgetMenu.ForKey(WidgetMenu.ForKey(WidgetMenu.Items(false, "", pid, project, false), '0').Choices, '3');
        }

        [Fact]
        public void TheBranchListSwitchesTheDiskToAnotherBranchAndPullsTheCurrentOne()
        {
            var items = WidgetMenu.Branches(new[] { "feature/valve", "master", "", "stable" }, "master", true, false).Skip(1).ToList();
            Assert.Equal(new[] { "feature/valve", "master", "stable" }, items.Select(item => item.Label));
            Assert.Equal("123", new string(items.Select(item => item.Key).ToArray()));
            Assert.Equal(new[] { "checkout", "feature/valve", "--disk-only" }, items[0].Args);
            Assert.True(items[1].Current);
            Assert.Equal(new[] { "project", "update" }, items[1].Args);
            Assert.Null(items[1].Disabled);
            Assert.Equal("pull", items[1].Hint);
            Assert.Null(items[2].Disabled);
        }

        [Fact]
        public void TheCurrentBranchWithoutUpstreamOnlySaysTheWorkIsThere()
        {
            var items = WidgetMenu.Branches(new[] { "tb", "master" }, "tb", false, false).Skip(1).ToList();
            Assert.True(items[0].Current);
            Assert.Null(items[0].Args);
            Assert.Equal(WidgetMenu.Here, items[0].Disabled);
            Assert.Equal("here", items[0].Hint);
            Assert.Equal(new[] { "checkout", "master", "--disk-only" }, items[1].Args);
        }

        [Fact]
        public void TheLastCommitShowsItsSubjectAndTheTimeOfToday()
        {
            var now = new DateTime(2026, 10, 15, 17, 30, 0);
            var today = new DateTimeOffset(new DateTime(2026, 10, 15, 16, 50, 0)).ToUnixTimeSeconds();
            var earlier = new DateTimeOffset(new DateTime(2026, 10, 14, 9, 5, 0)).ToUnixTimeSeconds();
            Assert.Equal("14.10 · 16:50", WidgetMenu.LastCommit("14.10\t" + today, now));
            Assert.Equal("a\tb · 2026-10-14 09:05", WidgetMenu.LastCommit("a\tb\t" + earlier, now));
            Assert.Null(WidgetMenu.LastCommit(null, now));
            Assert.Null(WidgetMenu.LastCommit("no time", now));
        }

        [Fact]
        public void TheCurrentBranchWaitsForTheLogoutToPull()
        {
            var items = WidgetMenu.Branches(new[] { "feature/valve", "master" }, "master", true, true).Skip(1).ToList();
            Assert.Equal(WidgetMenu.Online, items[1].Disabled);
            Assert.Null(items[0].Disabled);
        }

        [Fact]
        public void BranchesPastTheNinthHaveNoDigitAndTheListStopsAtItsLimit()
        {
            var names = Enumerable.Range(1, 20).Select(i => "b" + i);
            var items = WidgetMenu.Branches(names, null, false, false).Skip(1).ToList();
            Assert.Equal(WidgetMenu.MaxBranches, items.Count);
            Assert.Equal('9', items[8].Key);
            Assert.Equal('\0', items[9].Key);
            Assert.Null(WidgetMenu.ForKey(items, '\0'));
        }

        [Fact]
        public void TheFirstBranchRowAsksForANewBranchWhereTheWorkIs()
        {
            var create = WidgetMenu.Branches(new[] { "main" }, "main", false, false)[0];
            Assert.Equal('+', create.Key);
            Assert.Equal("New branch from main", create.Label);
            Assert.Equal("new branch name", create.Asks);
            Assert.Equal(new[] { "branch", "fix/valve" }, WidgetMenu.Answered(create, "  fix/valve "));
            Assert.Null(WidgetMenu.Answered(create, "   "));
            Assert.Equal("New branch here", WidgetMenu.Branches(new string[0], null, false, false)[0].Label);
        }

        [Fact]
        public void CommitAsksForTheMessageAndRunsOnlineToo()
        {
            var commit = WidgetMenu.ForKey(WidgetMenu.Items(true, "C:\\work", 7, "plant", false), '5');
            Assert.Null(commit.Disabled);
            Assert.Equal("commit message", commit.Asks);
            Assert.Equal("the files on disk, not the IDE", commit.Hint);
            Assert.Equal(new[] { "commit", "-m", "valve timing" }, WidgetMenu.Answered(commit, "valve timing"));
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(WidgetMenu.Items(false, "", 7, "plant", false), '5').Disabled);
            Assert.Equal("unavailable", WidgetMenu.ForKey(WidgetMenu.Items(false, "", 7, "plant", false), '5').Hint);
        }

        [Fact]
        public void TheOwnerAlsoCommitsAndPublishesTheProjectFile()
        {
            var items = WidgetMenu.Items(true, "C:\\work", 7, "plant", true);
            Assert.Equal("123456780", new string(items.Select(item => item.Key).ToArray()));
            var publish = WidgetMenu.ForKey(items, '6');
            Assert.Null(publish.Disabled);
            Assert.Equal("commit message", publish.Asks);
            Assert.Equal(new[] { "commit", "--publish", "-m", "new base" }, WidgetMenu.Answered(publish, "new base"));
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(WidgetMenu.Items(false, "", 7, "plant", true), '6').Disabled);
        }

        [Fact]
        public void SettingsStartWithTheSyncFolderPickedInADialog()
        {
            var folder = WidgetMenu.Settings("C:\\work", "", false, null, null, Deny, false)[0];
            Assert.Equal('1', folder.Key);
            Assert.Equal("Sync folder", folder.Label);
            Assert.NotNull(folder.Picks);
            Assert.Equal("C:\\work", folder.Initial);
            Assert.Equal(new[] { "set-sync-folder", "D:\\plant" }, WidgetMenu.Answered(folder, "D:\\plant"));
            var none = WidgetMenu.Settings("", "C:\\plant-cts", false, null, "{}", Deny, false);
            Assert.Single(none);
            Assert.Equal("not set", none[0].Hint);
        }

        [Fact]
        public void WithoutASyncFolderTheRowOffersTheSuggestionToTypeOrPickOrAClonePickedForAKnownProject()
        {
            var folder = WidgetMenu.Settings("", "C:\\plant-cts", false, null, null, Deny, false)[0];
            Assert.NotNull(folder.Picks);
            Assert.NotNull(folder.Asks);
            Assert.Equal("C:\\plant-cts", folder.Initial);
            Assert.Equal(new[] { "set-sync-folder", "C:\\plant-cts" }, WidgetMenu.Answered(folder, folder.Initial));
            var known = WidgetMenu.Settings("", "C:\\plant-cts", true, null, null, Deny, false)[0];
            Assert.Null(known.Asks);
            Assert.NotNull(known.Picks);
            Assert.Equal("C:\\plant-cts", known.Initial);
            Assert.Equal("Enter: pick your clone", known.Hint);
        }

        [Fact]
        public void TheHeaderOfAProjectWithoutASyncFolderSaysWhetherItsRepositoryExistsElsewhere()
        {
            Assert.Equal("repository not connected on this machine", WidgetMenu.Unconnected(true));
            Assert.Equal("no sync folder yet", WidgetMenu.Unconnected(false));
        }

        [Fact]
        public void ThisPcSwitchesBetweenOwnerAndColleague()
        {
            var colleague = WidgetMenu.Settings("C:\\work", "", true, null, "{}", Deny, false).Single(item => item.Label == "This PC");
            Assert.Equal("colleague", colleague.Hint);
            Assert.Equal(new[] { "set-sync-folder", "C:\\work", "--owner" }, colleague.Choices[0].Args);
            Assert.Null(colleague.Choices[0].Disabled);
            Assert.NotNull(colleague.Choices[1].Disabled);
            var owner = WidgetMenu.Settings("C:\\work", "", true, null, "{}", Deny, true).Single(item => item.Label == "This PC");
            Assert.Equal(new[] { "set-sync-folder", "C:\\work", "--colleague" }, owner.Choices[1].Args);
            Assert.True(owner.Choices[0].Current);
            Assert.DoesNotContain(WidgetMenu.Settings("", "C:\\plant-cts", true, null, "{}", Deny, false), item => item.Label == "This PC");
        }

        [Fact]
        public void EveryRowRunsACommandCtsServes()
        {
            const string config = "{\"settings\": {\"quick_key\": {\"value\": \"Alt+Q\", \"source\": \"code\"}}}";
            var pages = new[]
            {
                WidgetMenu.Items(false, "C:\\work", 7, "plant", true),
                WidgetMenu.Items(true, "C:\\work", 7, "plant", false),
                WidgetMenu.NoProject(new List<KnownProject>(), new Dictionary<string, string>(), 7),
                WidgetMenu.Settings("C:\\work", "", true, null, config, Deny, false),
                WidgetMenu.Branches(new[] { "master", "feature" }, "master", true, false),
                WidgetMenu.Comparisons(new[] { "master", "feature" }, "master"),
                WidgetMenu.PermissionGroups(Deny),
            };
            var rows = new List<WidgetItem>();
            void Walk(IEnumerable<WidgetItem> items)
            {
                foreach (var item in items ?? Enumerable.Empty<WidgetItem>()) { rows.Add(item); Walk(item.Choices); }
            }
            foreach (var page in pages) Walk(page);
            var commands = rows.Where(item => item.Args != null && item.Args.Length > 0).Select(item => item.Args).ToList();
            Assert.NotEmpty(commands);
            Assert.All(commands, args => Assert.True(Cts.Cli.CliCommands.Find(args) != null, string.Join(" ", args)));
        }

        [Fact]
        public void SettingsThatCannotBeReadLeaveTheSyncFolderAndThePermissions()
        {
            Assert.Equal(new[] { "Sync folder", "This PC", "Permissions" },
                WidgetMenu.Settings("C:\\work", "", false, "Traceback", "Traceback: not json", Deny, false).Select(item => item.Label));
            var unreadable = WidgetMenu.Settings("C:\\work", "", false, null, null, null, false)[2];
            Assert.Contains("unreadable", unreadable.Disabled);
            Assert.Null(unreadable.Choices);
        }

        [Fact]
        public void SettingsLetsTheUserChooseOnlyTheOpenProgram()
        {
            const string tools = "{\"compare\": {\"value\": null, \"uses\": \"desktop\", \"installed\": [\"desktop\"]}, "
                + "\"merge\": {\"value\": null, \"uses\": \"kdiff3\", \"installed\": [\"kdiff3\"]}, "
                + "\"open\": {\"value\": null, \"uses\": \"explorer\", \"installed\": [\"explorer\"]}}";
            var items = WidgetMenu.Settings("", "C:\\plant-cts", false, tools, null, Deny, false);
            Assert.Equal(new[] { "Sync folder", "Open the folder in" }, items.Select(item => item.Label));
            Assert.Equal(new[] { "tool", "open", "auto" }, items[1].Choices[0].Args);
        }

        [Fact]
        public void TheQuickWindowKeyIsTypedIntoTheUserFileWithOrWithoutASyncFolderAndAnOldFormatKeyIsNoRow()
        {
            const string config = "{\"settings\": {\"layout\": {\"value\": \"flat\", \"source\": \"project\"},"
                + " \"quick_key\": {\"value\": \"Ctrl+Shift+Q\", \"source\": \"user\", \"scope\": \"user\"}}}";
            var items = WidgetMenu.Settings("C:\\work", "", false, null, config, Deny, false);
            Assert.Equal(new[] { "Sync folder", "Quick window key", "This PC", "Permissions" }, items.Select(item => item.Label));
            var key = items[1];
            Assert.Equal('2', key.Key);
            Assert.Equal("Ctrl+Shift+Q · user", key.Hint);
            Assert.Equal("Ctrl+Shift+Q", key.Initial);
            Assert.Equal(new[] { "config", "set", "quick_key", "Alt+W" }, WidgetMenu.Answered(key, "Alt+W"));
            Assert.Equal(new[] { "Sync folder", "Quick window key" }, WidgetMenu.Settings("", "C:\\plant-cts", false, null, config, Deny, false).Select(item => item.Label));
        }

        [Fact]
        public void PermissionsOpenTheGroupsOfCheckBoxesAndASwitchIsTheAgentsNotACommand()
        {
            var row = WidgetMenu.Settings("C:\\work", "", false, null, null, Deny, false)[2];
            Assert.Equal(WidgetPage.Permissions, row.Opens);
            Assert.Null(row.Choices);
            Assert.Equal(string.Format("{0} of {1} blocked", Deny.Length, DenyRules.Catalog.Count), row.Hint);
            var groups = WidgetMenu.PermissionGroups(Deny);
            Assert.Equal(new[] { "The project", "The PLC", "PLC files and logs" }, groups.Select(group => group.Label));
            Assert.All(groups, group => Assert.Equal(WidgetPage.Permissions, group.Opens));
            Assert.Equal("123", new string(groups.Select(group => group.Key).ToArray()));
            var boxes = groups.SelectMany(group => group.Choices).ToList();
            Assert.Equal(DenyRules.Catalog.Select(entry => entry.Key), boxes.Select(box => box.Toggles));
            Assert.All(boxes, box => Assert.Null(box.Args));
            Assert.Equal("1 of 9 blocked", groups[0].Hint);
            var delete = boxes.Single(box => box.Toggles == "delete_pou");
            Assert.True(delete.Current);
            Assert.Null(delete.Disabled);
            Assert.Equal("delete_pou", delete.Hint);
            Assert.False(boxes.Single(box => box.Toggles == "build").Current);
            Assert.Equal("123456789", new string(groups[1].Choices.Take(9).Select(box => box.Key).ToArray()));
            Assert.Equal('\0', groups[1].Choices[9].Key);
        }

        [Fact]
        public void AKeyAPrefixEntryBlocksIsTickedAndGreyedWithThatEntry()
        {
            var origin = WidgetMenu.PermissionGroups(new[] { "reset_plc" }).SelectMany(group => group.Choices)
                .Single(box => box.Toggles == "reset_plc --kind origin");
            Assert.True(origin.Current);
            Assert.Equal("blocked by reset_plc: allow that first", origin.Disabled);
        }

        [Fact]
        public void AColleaguesSixPullsAndUpdatesTheProjectOffline()
        {
            var update = WidgetMenu.ForKey(WidgetMenu.Items(false, "C:\\work", 7, "plant", false), '6');
            Assert.Equal(new[] { "project", "update" }, update.Args);
            Assert.Null(update.Asks);
            Assert.Null(update.Disabled);
            Assert.Equal(WidgetMenu.Online, WidgetMenu.ForKey(WidgetMenu.Items(true, "C:\\work", 7, "plant", false), '6').Disabled);
            Assert.Equal(WidgetMenu.NoSyncFolder, WidgetMenu.ForKey(WidgetMenu.Items(true, "", 7, "plant", false), '6').Disabled);
            Assert.True(WidgetMenu.MovesState(update.Args));
        }

        [Fact]
        public void ACommitAsksWhetherTheBranchGoesToTheTeam()
        {
            string question;
            var answers = WidgetMenu.Pushing("ok commit branch=main commit=1a2b3c4d", out question);
            Assert.Equal("ok commit branch=main commit=1a2b3c4d\nPush the branch to the team's repository?", question);
            Assert.Equal(new[] { "push" }, Assert.Single(answers).Args);
            Assert.Equal('1', answers[0].Key);
            Assert.False(WidgetMenu.MovesState(answers[0].Args));
        }

        [Fact]
        public void APushTheTeamRefusedOffersToPullFirst()
        {
            string question;
            var line = "error push cause=\"origin/main has commits this branch lacks: pull them first "
                + "(cts project update), then push; ! [rejected]\"";
            var answers = WidgetMenu.Pulling(line, false, out question);
            Assert.Equal(line + "\nPull the team's commits into the project first?", question);
            Assert.Equal(new[] { "project", "update" }, Assert.Single(answers).Args);
            Assert.Null(answers[0].Disabled);
            Assert.Equal(WidgetMenu.Online, Assert.Single(WidgetMenu.Pulling(line, true, out _)).Disabled);
            Assert.Null(WidgetMenu.Pulling("error push cause=\"no remote\"", false, out _));
        }

        [Theory]
        [InlineData("2\t13", 2)]
        [InlineData("0\t3", 0)]
        [InlineData(null, 0)]
        [InlineData("fatal: no upstream", 0)]
        public void AheadCountsTheCommitsTheUpstreamLacks(string counts, int ahead)
        {
            Assert.Equal(ahead, WidgetMenu.Ahead(counts));
        }

        [Fact]
        public void TheOwnersPublishRowHasAShortHint()
        {
            var publish = WidgetMenu.Items(false, "C:\\work", 1, "plant", true).Single(item => item.Key == '6');
            Assert.Equal("+ the saved project file", publish.Hint);
        }

        [Fact]
        public void AStageLineOfStderrIsTheProgressNotTheOutcome()
        {
            Assert.Equal("reading native objects 120/412", WidgetMenu.Stage("progress: reading native objects 120/412\r"));
            Assert.Null(WidgetMenu.Stage("[INFO] something"));
            Assert.Null(WidgetMenu.Stage(null));
            Assert.Equal("Cannot reach the IDE", WidgetMenu.Outcome("", "[ERROR] Cannot reach the IDE\nprogress: reading the project tree\n", 1));
        }

        [Theory]
        [InlineData("ok compare unchanged=46 modified=0 added=0 deleted=0 not_importable=0", "in sync", WidgetTone.InSync)]
        [InlineData("ok compare unchanged=44 modified=1 added=1 deleted=0 not_importable=0 ide_changed=1", "changed: disk 2 · IDE 1", WidgetTone.Changed)]
        [InlineData("ok compare unchanged=45 modified=1 added=0 deleted=0 not_importable=0 both=1", "changed: both 1", WidgetTone.Both)]
        [InlineData("ok compare base=none unchanged=0 modified=0 added=0 deleted=0 not_importable=0 ide_changed=46", "not on disk yet — 2 writes it", WidgetTone.Changed)]
        [InlineData("ok compare base=other unchanged=279 modified=5 added=12 deleted=0 not_importable=0 ide_changed=1", "the disk was synced with another project file — 2 writes this one, 1 takes the disk", WidgetTone.Changed)]
        [InlineData("error compare cause=\"no sync base\"", "state unknown", WidgetTone.Unknown)]
        [InlineData(null, "state unknown", WidgetTone.Unknown)]
        public void TheHeaderSaysWhatChangedOnEachSideFromTheCompare(string verdict, string state, WidgetTone tone)
        {
            WidgetTone read;
            Assert.Equal(state, WidgetMenu.State(verdict, out read));
            Assert.Equal(tone, read);
        }

        [Fact]
        public void TheCommandsThatCarryEditsReadTheStateAgain()
        {
            Assert.True(WidgetMenu.MovesState(new[] { "import", "--force" }));
            Assert.True(WidgetMenu.MovesState(new[] { "checkout", "dev", "--disk-only" }));
            Assert.False(WidgetMenu.MovesState(new[] { "compare", "--tool" }));
            Assert.False(WidgetMenu.MovesState(new[] { "tool", "merge", "auto" }));
        }

        [Theory]
        [InlineData(new[] { "commit", "-m", "fix the valve" }, "commit")]
        [InlineData(new[] { "checkout", "feature", "--disk-only" }, "checkout --disk-only")]
        [InlineData(new[] { "import", "--force" }, "import --force")]
        public void ARunIsTimedAsItsCommandAndFlags(string[] args, string kind)
        {
            Assert.Equal(kind, WidgetMenu.Kind(args));
        }

        [Fact]
        public void TheProgressIsTheLastRunsTimeWhenThereWasOne()
        {
            double? share;
            Assert.Equal("12 s", WidgetMenu.Elapsed(12400, null, out share));
            Assert.Null(share);
            Assert.Equal("10 s of ~40 s", WidgetMenu.Elapsed(10000, 39600, out share));
            Assert.Equal(10000.0 / 39600, share.Value, 6);
            Assert.Equal("0 s of ~1 s", WidgetMenu.Elapsed(100, 300, out share));
            Assert.Equal(1.0 / 3, share.Value, 6);
        }

        [Fact]
        public void ARunPastTheLastOnesTimeWaitsNearTheEndOfTheBar()
        {
            double? share;
            Assert.Equal("90 s of ~40 s", WidgetMenu.Elapsed(90000, 40000, out share));
            Assert.Equal(0.97, share.Value, 6);
        }

        [Theory]
        [InlineData("main", null, null, "main")]
        [InlineData("main", null, "0\t0", "main")]
        [InlineData("main", null, "2\t0", "main ↑2")]
        [InlineData("main", null, "0\t3", "main ↓3")]
        [InlineData("main", null, "2\t13", "main ↑2 ↓13")]
        [InlineData("main", null, "fatal: no upstream", "main")]
        [InlineData(null, "1bcc3807", null, "detached at 1bcc3807")]
        [InlineData(null, null, null, "no git repository")]
        public void WhereNamesTheBranchAndItsDistanceFromUpstreamElseTheDetachedCommit(string branch, string detached,
            string counts, string where)
        {
            Assert.Equal(where, WidgetMenu.Where(branch, detached, counts));
        }

        [Theory]
        [InlineData("note\r\nok import written=1\r\nmore\r\n", "", 0, "ok import written=1")]
        [InlineData("error build cause=x\n", "[ERROR] x\n", 1, "error build cause=x")]
        [InlineData("error export cause=refused\n", "[ERROR] no sync folder\n", 1, "error export cause=refused — no sync folder")]
        [InlineData("", "noise\n[ERROR] no agent\n\n", 2, "no agent")]
        [InlineData("", "", 3, "cts exited 3")]
        public void TheOutcomeIsTheVerdictElseTheLastErrorElseTheExitCode(string stdout, string stderr, int code, string outcome)
        {
            Assert.Equal(outcome, WidgetMenu.Outcome(stdout, stderr, code));
        }

        [Theory]
        [InlineData("ok compare unchanged=10 ide_changed=2 both=1", 3)]
        [InlineData("ok compare unchanged=10 modified=4", 0)]
        [InlineData("ok compare base=other unchanged=1089 modified=0 added=0 deleted=0 not_importable=0 ide=cached", 0)]
        [InlineData("ok compare base=other unchanged=9 modified=2 added=1", 3)]
        [InlineData(null, 0)]
        public void IdeEditsCountsWhatACommitOfTheDiskLeavesOut(string verdict, int edits)
        {
            Assert.Equal(edits, WidgetMenu.IdeEdits(verdict));
            Assert.Equal(edits > 0, WidgetMenu.CommitNote(edits).Length > 0);
        }
    }
}
