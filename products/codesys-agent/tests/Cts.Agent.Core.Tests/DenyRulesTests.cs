using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // The agent enforces the project's deny list for the writes it performs
    // itself (`objects.delete`, `project.save`).  These pin its rules.
    public class DenyRulesTests
    {
        static string Reason(string raw, string method)
        {
            string reason;
            Assert.False(DenyRules.Check(raw, true, method, out reason));
            return reason;
        }

        static void Allowed(string raw, string method)
        {
            string reason;
            Assert.True(DenyRules.Check(raw, true, method, out reason));
            Assert.Equal("", reason);
        }

        [Fact]
        public void NothingStoredMeansTheDefaults()
        {
            // delete_pou is denied by default, so a delete is refused with no
            // property in the project at all.
            Assert.Contains("deny list includes 'delete_pou'", Reason("", "delete_pou"));
            Allowed("", "delete_object");
        }

        [Fact]
        public void AnExplicitEntryIsDenied()
        {
            Assert.Contains("deny list includes 'delete_pou'",
                Reason("{\"deny\":[\"delete_pou\"]}", "delete_pou"));
        }

        [Fact]
        public void AnEmptyListAllowsEverything()
        {
            Allowed("{\"deny\":[]}", "delete_pou");
        }

        [Fact]
        public void AStoredListReplacesTheDefaults()
        {
            // plc_upload is denied by default; storing a list without it
            // allows it.
            Allowed("{\"deny\":[\"reset_plc\"]}", "plc_upload");
            Assert.Contains("deny list includes 'reset_plc'",
                Reason("{\"deny\":[\"reset_plc\"]}", "reset_plc"));
        }

        [Fact]
        public void AConfigWithoutADenyKeyKeepsTheDefaults()
        {
            Assert.Contains("deny list includes 'delete_pou'",
                Reason("{\"poll_ms\":60}", "delete_pou"));
        }

        [Fact]
        public void AVariableWriteAnswersToWriteVariable()
        {
            // Allowed by default, refused once the user denies it; and it is
            // no project write, so the journal does not take it for one.
            Allowed("", DenyRules.WriteVariable);
            Assert.Contains("deny list includes 'write_variable'",
                Reason("{\"deny\":[\"write_variable\"]}", DenyRules.WriteVariable));
            Assert.Null(DenyRules.KeyFor("vars.write"));
        }

        [Fact]
        public void APrefixEntryMatchesToo()
        {
            Assert.Contains("pattern 'reset_plc' matches 'reset_plc --kind origin'",
                Reason("{\"deny\":[\"reset_plc\"]}", "reset_plc --kind origin"));
        }

        [Fact]
        public void InvalidJsonFailsClosed()
        {
            Assert.Contains("unreadable", Reason("{not json", "delete_object"));
        }

        [Fact]
        public void JsonThatIsNotAnObjectFailsClosed()
        {
            Assert.Contains("unreadable", Reason("[\"delete_pou\"]", "delete_object"));
        }

        [Fact]
        public void AConfigThatCannotBeReadFailsClosed()
        {
            string reason;
            Assert.False(DenyRules.Check("", false, "delete_object", out reason));
            Assert.Contains("unreadable", reason);
        }

        [Fact]
        public void RequireThrowsTheForbiddenCode()
        {
            var ex = Assert.Throws<ProtocolException>(
                () => DenyRules.Require("{\"deny\":[\"delete_pou\"]}", true, "delete_pou"));
            Assert.Equal("forbidden", ex.Code);
            Assert.Contains("delete_pou", ex.Message);
        }

        [Fact]
        public void EachAgentWriteAnswersTheCommandItStandsFor()
        {
            // The key is fixed here, never taken from the request: a client
            // cannot route a write through a method mapped to a weaker key.
            Assert.Equal("delete_pou", DenyRules.KeyFor("objects.delete"));
            Assert.Equal("build", DenyRules.KeyFor("app.build"));
            Assert.Equal("save_project", DenyRules.KeyFor("project.save"));
            Assert.Equal("set_sync_folder", DenyRules.KeyFor("project.syncfolder"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("project.source"));
            Assert.Equal("set_simulation_mode", DenyRules.KeyFor("project.simulation"));
            Assert.Equal("project_open", DenyRules.KeyFor("project.open"));
            Assert.Equal("project_close", DenyRules.KeyFor("project.close"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.settext"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.create"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.import"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.rename"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.move"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.setfield"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.listadd"));
            Assert.Equal("sync_import_text", DenyRules.KeyFor("objects.listremove"));
            // A read is not a write and has no key; unknown methods get none.
            Assert.Null(DenyRules.KeyFor("objects.texts"));
            Assert.Null(DenyRules.KeyFor(""));
        }

        [Fact]
        public void AnUnknownWriteMethodIsRefusedRatherThanAllowed()
        {
            // A method the table does not name is a bug on our side, not a
            // license to write: refusing is the safe default.
            var ex = Assert.Throws<ProtocolException>(
                () => DenyRules.RequireWrite("{\"deny\":[]}", true, "objects.mystery"));
            Assert.Equal("internal", ex.Code);
            Assert.Contains("objects.mystery", ex.Message);
        }

        [Fact]
        public void RequireWriteUsesTheMethodsKey()
        {
            // A deny of sync_import_text stops settext/create/setfield, but not
            // the delete, which answers delete_pou.
            const string raw = "{\"deny\":[\"sync_import_text\"]}";
            foreach (var method in new[] { "objects.settext", "objects.create", "objects.setfield", "objects.listadd", "objects.listremove", "objects.replace" })
            {
                var ex = Assert.Throws<ProtocolException>(
                    () => DenyRules.RequireWrite(raw, true, method));
                Assert.Equal("forbidden", ex.Code);
                Assert.Contains("sync_import_text", ex.Message);
            }
            // The delete answers a different key, so this deny does not stop it.
            DenyRules.RequireWrite(raw, true, "objects.delete");
        }

        [Fact]
        public void TheSaveAnswersTheSaveCommand()
        {
            // A save is not a delete and not an import: it answers save_project.
            DenyRules.RequireWrite("{\"deny\":[\"sync_import_text\"]}", true, "project.save");
            var ex = Assert.Throws<ProtocolException>(
                () => DenyRules.RequireWrite("{\"deny\":[\"save_project\"]}", true, "project.save"));
            Assert.Equal("forbidden", ex.Code);
            Assert.Contains("save_project", ex.Message);
        }

        [Fact]
        public void AnEmptyListLetsEveryWriteThrough()
        {
            DenyRules.RequireWrite("{\"deny\":[]}", true, "objects.settext");
            DenyRules.RequireWrite("{\"deny\":[]}", true, "objects.create");
        }

        [Fact]
        public void TheDefaultListIsPinned()
        {
            Assert.Equal(new[]
            {
                "reset_plc",
                "reset_plc --kind origin",
                "create_boot_app",
                "plc_upload",
                "delete_pou",
            }, DenyRules.DefaultDeny);
        }

        [Fact]
        public void DescribeShowsTheDefaultsWhenNothingIsStored()
        {
            var data = DenyRules.Describe("", true);
            Assert.Equal(DenyRules.DefaultDeny, ((System.Collections.Generic.List<object>)data["deny"]).ConvertAll(x => (string)x));
            Assert.Contains("cds-text-sync.json", (string)data["stored_in"]);
            Assert.Contains("repository", (string)data["persistence"]);
            Assert.False(data.ContainsKey("config_error"));
        }

        [Fact]
        public void DescribeShowsTheDenyOfTheSettingsFileAlone()
        {
            var data = DenyRules.Describe("{\"deny\":[\"build\"],\"layout\":\"project-view\"}", true);
            Assert.Equal(new object[] { "build" }, ((System.Collections.Generic.List<object>)data["deny"]).ToArray());
            Assert.False(data.ContainsKey("layout"));
            Assert.False(data.ContainsKey("config_error"));
            var none = DenyRules.Describe("{\"layout\":\"project-view\"}", true);
            Assert.Contains("delete_pou", ((System.Collections.Generic.List<object>)none["deny"]).ConvertAll(x => (string)x));
        }

        [Theory]
        [InlineData("{not json", true)]
        [InlineData("[1]", true)]
        [InlineData("{\"deny\":\"build\"}", true)]
        [InlineData("", false)]
        public void DescribeNamesAnUnreadableConfig(string raw, bool readable)
        {
            var data = DenyRules.Describe(raw, readable);
            Assert.Contains("unreadable", (string)data["config_error"]);
            Assert.Contains("delete_pou", ((System.Collections.Generic.List<object>)data["deny"]).ConvertAll(x => (string)x));
        }

        [Fact]
        public void TheCatalogNamesEveryKeyACommandAnswersTo()
        {
            var keys = DenyRules.Catalog.Select(entry => entry.Key).ToList();
            Assert.Equal(keys.Distinct(), keys);
            Assert.All(DenyRules.DefaultDeny, key => Assert.Contains(key, keys));
            foreach (var method in new[] { "objects.delete", "app.build", "app.login", "project.save", "project.syncfolder",
                         "project.simulation", "project.open", "project.close", "objects.settext" })
                Assert.Contains(DenyRules.KeyFor(method), keys);
        }

        [Fact]
        public void ToggleDeniesAnAllowedKeyAndKeepsTheRestOfTheFile()
        {
            var text = DenyRules.Toggle("{\"project_id\": \"abc\", \"layout\": \"project-view\", \"deny\": [\"delete_pou\"]}", "build");
            Assert.Equal("{\n  \"deny\": [\n    \"delete_pou\",\n    \"build\"\n  ],\n  \"layout\": \"project-view\",\n  \"project_id\": \"abc\"\n}\n", text);
        }

        [Fact]
        public void ToggleAllowsADeniedKeyAndAFileWithoutDenyStartsFromTheDefaults()
        {
            var text = DenyRules.Toggle("{\"layout\": \"flat\"}", "delete_pou");
            Assert.Equal(DenyRules.DefaultDeny.Where(key => key != "delete_pou"), DenyRules.DenyList(text, true));
            Assert.Equal(DenyRules.DefaultDeny.Concat(new[] { "download" }), DenyRules.DenyList(DenyRules.Toggle("", "download"), true));
        }

        [Theory]
        [InlineData("{\"deny\": [\"reset_plc\"]}", "reset_plc --kind origin", "refused by 'reset_plc'")]
        [InlineData("{}", "no_such_key", "no command answers")]
        [InlineData("{not json", "build", "unreadable")]
        [InlineData("{\"deny\": \"build\"}", "build", "unreadable")]
        public void ToggleRefuses(string raw, string key, string why)
        {
            var refused = Assert.Throws<ProtocolException>(() => DenyRules.Toggle(raw, key));
            Assert.Contains(why, refused.Message);
        }

        [Fact]
        public void BlockedByNamesTheExactEntryBeforeAPrefix()
        {
            Assert.Equal("reset_plc --kind origin", DenyRules.BlockedBy(new[] { "reset_plc", "reset_plc --kind origin" }, "reset_plc --kind origin"));
            Assert.Equal("reset_plc", DenyRules.BlockedBy(new[] { "reset_plc" }, "reset_plc --kind origin"));
            Assert.Null(DenyRules.BlockedBy(new[] { "reset_plc --kind origin" }, "reset_plc"));
        }
    }
}
