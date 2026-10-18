using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmDetectorTests
    {
        [Fact]
        public void FindsSelfTransitionAndProvidesStateCode()
        {
            const string text = "CASE state OF\nIDLE:\n    state := IDLE;\nEND_CASE";
            var machines = FsmDetector.Machines(text);
            Assert.Single(machines);
            Assert.Equal("state", machines[0]["selector"]);
            Assert.Equal("IDLE", ((List<Dictionary<string, object>>)machines[0]["states"])[0]["label"]);
        }

        [Fact]
        public void KeepsTheCaseOfAStateLabel()
        {
            const string text = "CASE eMode OF\nE_Mode.Idle:\n    eMode := E_Mode.Run_fast;\nE_Mode.Run_fast:\n    eMode := E_Mode.Idle;\nEND_CASE";
            var states = (List<Dictionary<string, object>>)FsmDetector.Machines(text)[0]["states"];
            Assert.Equal(new[] { "E_Mode.Idle", "E_Mode.Run_fast" }, states.Select(state => (string)state["label"]));
        }

        [Fact]
        public void CodeOutsideTheCaseLeavesEveryOtherStateAndElseIsMarked()
        {
            const string text = "IF xRun THEN\n    state := RUN;\nEND_IF\nCASE state OF\nIDLE:\n    state := STOP;\nRUN:\n    ;\nSTOP:\n    ;\nELSE\n    state := IDLE;\nEND_CASE";
            var machine = FsmDetector.Machines(text)[0];
            var warnings = ((List<Dictionary<string, object>>)machine["warnings"]).Select(warning => (string)warning["text"]);
            Assert.Equal(new[] { "state RUN has no outgoing transition" }, warnings);
            var transitions = (List<Dictionary<string, object>>)machine["transitions"];
            Assert.False(transitions[0].ContainsKey("else"));
            Assert.Equal(true, transitions[2]["else"]);
            Assert.Equal("(other value)", FsmMap.SourceLabel(transitions[2]));
            Assert.Equal("(any)", FsmMap.SourceLabel(transitions[0]));
        }

        [Theory]
        [InlineData("VAR\n    nState : INT;\nEND_VAR\nVAR CONSTANT\n    ST_IDLE : INT := 0;\n    ST_RUN : INT := 10;\nEND_VAR", "ST_IDLE", "INT's default 0")]
        [InlineData("VAR\n    nState : INT := ST_RUN; // starts running\nEND_VAR", "ST_RUN", "its declared value")]
        [InlineData("VAR\n    nState : E_State;\nEND_VAR", null, null)]
        [InlineData("VAR\n    nOther : INT;\nEND_VAR", null, null)]
        public void InitialIsTheSelectorsStartValueAsAState(string declaration, string expected, string expectedBasis)
        {
            const string text = "CASE nState OF\nST_IDLE:\n    nState := ST_RUN;\nST_RUN:\n    nState := ST_IDLE;\nEND_CASE";
            Assert.Equal(expected, FsmDetector.Initial(declaration, FsmDetector.Machines(text)[0], out var basis));
            Assert.Equal(expectedBasis, basis);
        }

        [Fact]
        public void MatchesPythonMachineGoldens()
        {
            var path = Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "Golden", "fsm-machines.json");
            var entries = (List<object>)Json.Parse(File.ReadAllText(path));
            foreach (var entry in entries.Cast<Dictionary<string, object>>())
            {
                var expected = (List<object>)entry["machines"];
                var actual = FsmDetector.Machines((string)entry["text"]);
                Assert.True(Json.Serialize(expected) == Json.Serialize(actual), (string)entry["name"] + "\nexpected " + Json.Serialize(expected) + "\nactual " + Json.Serialize(actual));
            }
        }
    }
}
