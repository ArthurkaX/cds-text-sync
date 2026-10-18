using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmGrafcetTests
    {
        [Fact]
        public void LaysOutEveryMachineAsThePythonLayoutDid()
        {
            var path = Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "Golden", "fsm-layout.json");
            foreach (var entry in ((List<object>)Json.Parse(File.ReadAllText(path))).Cast<Dictionary<string, object>>())
            {
                var expected = ((List<object>)entry["layouts"]).Select(Json.Serialize).ToList();
                var actual = FsmDetector.Machines((string)entry["text"]).Select(machine => Json.Serialize(FsmGrafcet.Layout(machine))).ToList();
                Assert.True(expected.SequenceEqual(actual), (string)entry["name"] + "\nexpected " + string.Join("\n", expected) + "\nactual " + string.Join("\n", actual));
            }
        }

        [Fact]
        public void TwoPriorityTransitionsIntoOneStepMeetAboveOneChip()
        {
            const string text = "IF a THEN s := S.Halt; END_IF\nIF b THEN s := S.Halt; END_IF\nCASE s OF\nS.Run:\n    s := S.Halt;\nS.Halt:\n    s := S.Run;\nEND_CASE";
            var layout = FsmGrafcet.Layout(FsmDetector.Machines(text)[0]);
            Assert.Single((List<object>)layout["chips"]);
            Assert.Equal("S.", layout["prefix"]);
            Assert.Equal(2, ((List<object>)layout["links"]).Cast<Dictionary<string, object>>().Count(link => (string)link["kind"] == "global"));
        }
    }
}
