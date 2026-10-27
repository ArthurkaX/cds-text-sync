using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmWatchTests
    {
        static readonly Dictionary<string, string> Objects = new Dictionary<string, string>
        {
            ["FB_Base"] = "FUNCTION_BLOCK FB_Base\nVAR\n    iState : INT;\n    aiLink : ARRAY[1..N_LINKS] OF INT;\nEND_VAR\nVAR CONSTANT\n    ST_IDLE : INT := 0;\n    ST_RUN : INT := 16#A;\n    N_LINKS : INT := 2;\nEND_VAR\n",
            ["FB_Motor"] = "FUNCTION_BLOCK FB_Motor EXTENDS FB_Base\nVAR_INPUT\n    xStart : BOOL;\nEND_VAR\n",
            ["FB_Line"] = "FUNCTION_BLOCK FB_Line\nVAR\n    fbFeed : FB_Motor;\n    aPumps : ARRAY[1..2] OF FB_Base;\nEND_VAR\nVAR_TEMP\n    fbScratch : FB_Base;\nEND_VAR\n",
            ["ST_Cell"] = "TYPE ST_Cell :\nSTRUCT\n    fbDrive : FB_Base;\nEND_STRUCT\nEND_TYPE\n",
            ["E_Mode"] = "TYPE E_Mode :\n(\n    Off := 0,\n    Auto := 5\n);\nEND_TYPE\n",
            ["PRG_Main"] = "PROGRAM PRG_Main\nVAR\n    fbLine : FB_Line;\n    stCell : ST_Cell;\n    eMode : E_Mode;\nEND_VAR\n",
            ["GVL"] = "VAR_GLOBAL\n    fbSpare : FB_Motor;\n    eShared : E_Mode;\nEND_VAR\nVAR_GLOBAL CONSTANT\n    N_LAST : INT := 7;\nEND_VAR\n",
            ["FB_Base.Step"] = "METHOD Step : BOOL\nVAR\n    iLocal : INT;\nEND_VAR\n",
        };

        static FsmWatch Watch() => new FsmWatch(Objects.Where(item => !item.Key.Contains(".")));

        [Fact]
        public void A_function_blocks_variable_is_read_in_every_instance_the_programs_and_lists_hold()
        {
            var paths = Watch().Paths("FB_Base", Objects["FB_Base"], "iState");
            Assert.Equal(new[]
            {
                "PRG_Main.fbLine.aPumps[1].iState", "PRG_Main.fbLine.aPumps[2].iState", "PRG_Main.stCell.fbDrive.iState",
                "PRG_Main.fbLine.fbFeed.iState", "GVL.fbSpare.iState",
            }.OrderBy(path => path), paths.OrderBy(path => path));
            // A method of the block reads its block's variable; THIS^ is the instance.
            Assert.Equal(5, Watch().Paths("FB_Base.Step", Objects["FB_Base.Step"], "THIS^.iState").Count);
            // An array indexed by a variable: a machine per element of each instance.
            var links = Watch().Paths("FB_Base", Objects["FB_Base"], "aiLink[iK]");
            Assert.Equal(10, links.Count);
            Assert.Contains("GVL.fbSpare.aiLink[2]", links);
            // A VAR_TEMP instance holds nothing between cycles and is no place to read.
            Assert.DoesNotContain(paths, path => path.Contains("fbScratch"));
        }

        [Fact]
        public void A_program_a_list_and_a_local_are_read_where_they_live_or_not_at_all()
        {
            var watch = Watch();
            Assert.Equal(new[] { "PRG_Main.eMode" }, watch.Paths("PRG_Main", Objects["PRG_Main"], "eMode"));
            Assert.Equal(new[] { "GVL.eShared" }, watch.Paths("PRG_Main", Objects["PRG_Main"], "eShared"));
            Assert.Equal(new[] { "GVL.eShared" }, watch.Paths("PRG_Main", Objects["PRG_Main"], "GVL.eShared"));
            Assert.Empty(watch.Paths("FB_Base.Step", Objects["FB_Base.Step"], "iLocal"));
            Assert.Empty(watch.Paths("PRG_Main", Objects["PRG_Main"], "aSteps[i]"));
            Assert.Empty(watch.Paths("PRG_Main", Objects["PRG_Main"], "pState^"));
        }

        [Fact]
        public void A_states_label_stands_for_the_numbers_of_its_constants_literals_and_enumeration_members()
        {
            var watch = Watch();
            Assert.Equal(new[] { "0", "10" }, watch.Values("ST_IDLE, ST_RUN", "FB_Motor", ""));
            Assert.Equal(new[] { "7", "0..7" }, watch.Values("N_LAST, ST_IDLE..N_LAST", "FB_Base", Objects["FB_Base"]));
            Assert.Equal(new[] { "5", "16" }, watch.Values("E_Mode.Auto, 16#10", "PRG_Main", Objects["PRG_Main"]));
            Assert.Empty(watch.Values("Unknown", "PRG_Main", Objects["PRG_Main"]));
        }

        static FsmMachine Machine()
        {
            var json = @"{""items"": [{""label"": ""FB_Base"", ""machines"": [{""selector"": ""iState"", ""watch"": [""PRG_Main.fbLine.fbFeed.iState""],
                ""states"": [{""label"": ""ST_IDLE"", ""values"": [""0""]}, {""label"": ""ST_RUN, ST_WAIT"", ""values"": [""10"", ""11..12""]}, {""label"": ""E_Mode.Auto""}],
                ""transitions"": [{""source"": ""ST_IDLE"", ""target"": ""ST_RUN, ST_WAIT""}, {""source"": """", ""target"": ""ST_IDLE""}],
                ""layout"": {""steps"": [], ""chips"": [], ""links"": [], ""metrics"": {}}}]}]}";
            return FsmMap.Parse(json)[0].Machines[0];
        }

        [Fact]
        public void A_value_read_online_finds_its_state_and_the_transition_that_led_there()
        {
            var machine = Machine();
            Assert.Equal(new[] { "PRG_Main.fbLine.fbFeed.iState" }, machine.Watch);
            Assert.Equal("ST_IDLE", FsmMap.StateOf(machine, "0"));
            Assert.Equal("ST_RUN, ST_WAIT", FsmMap.StateOf(machine, "INT#10"));
            Assert.Equal("ST_RUN, ST_WAIT", FsmMap.StateOf(machine, "12"));
            Assert.Equal("ST_RUN, ST_WAIT", FsmMap.StateOf(machine, "ST_WAIT"));
            Assert.Equal("E_Mode.Auto", FsmMap.StateOf(machine, "Auto"));
            Assert.Null(FsmMap.StateOf(machine, "99"));
            Assert.Equal(new[] { 0 }, FsmMap.Taken(machine, "ST_IDLE", "ST_RUN, ST_WAIT"));
            // No transition of its own: the one written outside the CASE.
            Assert.Equal(new[] { 1 }, FsmMap.Taken(machine, "ST_RUN, ST_WAIT", "ST_IDLE"));
        }

        [Fact]
        public void A_read_answer_gives_the_IDEs_spelling_or_why_there_is_none()
        {
            var answer = new Dictionary<string, object>
            {
                ["online"] = true, ["logged_in"] = true,
                ["results"] = new List<object> { new Dictionary<string, object> { ["ok"] = true, ["value"] = 5, ["text"] = "E_Mode.Auto" } },
            };
            Assert.Equal("E_Mode.Auto", FsmMap.LiveValue(answer, out var failure));
            Assert.Null(failure);
            answer["logged_in"] = false;
            Assert.Null(FsmMap.LiveValue(answer, out failure));
            Assert.Equal("not logged in", failure);
            answer["logged_in"] = true;
            answer["results"] = new List<object> { new Dictionary<string, object> { ["ok"] = false, ["error"] = new Dictionary<string, object> { ["code"] = "not_exported" } } };
            Assert.Null(FsmMap.LiveValue(answer, out failure));
            Assert.StartsWith("not in the application on the PLC", failure);
        }
    }
}
