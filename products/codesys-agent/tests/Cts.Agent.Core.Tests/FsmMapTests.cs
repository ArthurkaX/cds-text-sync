using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmMapTests
    {
        // `cts fsm --layout --json` on IDLE -> RUN (xStart), RUN -> IDLE (xStop).
        const string Answer = @"{""objects"": 2, ""with_fsm"": 1, ""machines"": 1, ""items"": [
            {""guid"": ""g-prg"", ""label"": ""PRG_Main"", ""machines"": [{""selector"": ""state"", ""numeric"": false,
              ""deferred"": [], ""warnings"": [{""line"": 3, ""text"": ""state IDLE is never left""}],
              ""states"": [{""label"": ""IDLE"", ""code"": ""IDLE:\nIF xStart THEN"", ""line"": 2},
                           {""label"": ""RUN"", ""code"": ""RUN:\nnCount := nCount + 1;"", ""line"": 7}],
              ""transitions"": [{""source"": ""IDLE"", ""target"": ""RUN"", ""guard"": ""xStart"", ""code"": ""state := RUN;"", ""line"": 5, ""block"": true},
                                {""source"": """", ""target"": ""IDLE"", ""guard"": """", ""code"": ""state := IDLE;"", ""line"": 9, ""block"": false}],
              ""layout"": {""width"": 280, ""height"": 242, ""prefix"": """", ""any_box"": null,
                ""steps"": [{""number"": 1, ""label"": ""IDLE"", ""full_label"": ""IDLE"", ""x"": 50, ""y"": 24, ""w"": 170, ""h"": 34,
                             ""initial"": true, ""priority"": false, ""inbound"": [2], ""inbound_x"": 24},
                            {""number"": 2, ""label"": ""RUN"", ""full_label"": ""RUN"", ""x"": 50, ""y"": 120, ""w"": 170, ""h"": 34,
                             ""initial"": false, ""priority"": false, ""inbound"": [], ""inbound_x"": 24}],
                ""chips"": [],
                ""links"": [{""kind"": ""chain"", ""transition_index"": 0, ""points"": [[135, 58], [135, 120]], ""bar"": [135, 90, ""h""],
                             ""guard_text"": ""xStart"", ""guard_at"": [162, 83], ""guard_w"": 42, ""arrow"": null,
                             ""note_text"": """", ""note_at"": null, ""note_w"": 0},
                            {""kind"": ""jump"", ""transition_index"": 1, ""points"": [[135, 154], [135, 214], [157, 214], [157, 184]],
                             ""bar"": [135, 174, ""h""], ""guard_text"": ""xStop"", ""guard_at"": [162, 167], ""guard_w"": 35,
                             ""arrow"": [157, 184, ""up""], ""note_text"": ""1  IDLE"", ""note_at"": [167, 186], ""note_w"": 49},
                            {""kind"": ""chain"", ""transition_index"": null, ""points"": [[10, 10], [20, 10]], ""bar"": null,
                             ""guard_text"": """", ""guard_at"": null, ""guard_w"": 0, ""arrow"": null,
                             ""note_text"": """", ""note_at"": null, ""note_w"": 0}],
                ""metrics"": {""num_w"": 34, ""text_h"": 15, ""bar_half"": 15}}}]},
            {""guid"": ""g-fb"", ""label"": ""FB_Valve.Run"", ""machines"": []}]}";

        [Fact]
        public void TheAnswerReadsAsObjectsWithTheirMachinesCodeAndLayout()
        {
            var objects = FsmMap.Parse(Answer);
            Assert.Equal(new[] { "PRG_Main", "FB_Valve.Run" }, objects.Select(item => item.Label));
            Assert.Empty(objects[1].Machines);
            var machine = objects[0].Machines.Single();
            Assert.Equal("state", machine.Selector);
            Assert.Equal(new[] { "line 3: state IDLE is never left" }, machine.Warnings);
            Assert.Equal("RUN", machine.States[1].Title);
            Assert.Equal(7, machine.States[1].Line);
            Assert.Null(machine.States[1].Guard);
            Assert.Equal("IDLE → RUN", machine.Transitions[0].Title);
            Assert.Equal("xStart", machine.Transitions[0].Guard);
            Assert.Equal("(any) → IDLE", machine.Transitions[1].Title);

            var layout = machine.Layout;
            Assert.Equal(280, layout.Width);
            Assert.Null(layout.AnyBox);
            Assert.Equal(34, layout.NumW);
            Assert.True(layout.Steps[0].Initial);
            Assert.Equal(new[] { 2 }, layout.Steps[0].Inbound);
            Assert.Equal(new[] { 0, 1, -1 }, layout.Links.Select(link => link.Transition));
            Assert.Equal("up", layout.Links[1].Arrow.Way);
            Assert.Null(layout.Links[0].Arrow);
            Assert.Equal("h", layout.Links[0].Bar.Way);
            Assert.Equal(new[] { 157, 184 }, layout.Links[1].Points[3]);
            Assert.Throws<JsonException>(() => FsmMap.Parse(@"{""ok"": true}"));
        }

        [Fact]
        public void AClickFindsTheStepOrTheNearestTransition()
        {
            var layout = FsmMap.Parse(Answer)[0].Machines[0].Layout;
            Assert.Equal("RUN", FsmMap.StepAt(layout, 60, 130).FullLabel);
            Assert.Null(FsmMap.StepAt(layout, 10, 10));
            Assert.Equal(0, FsmMap.TransitionAt(layout, 138, 100, 6));
            Assert.Equal(1, FsmMap.TransitionAt(layout, 150, 216, 6));
            Assert.Equal(1, FsmMap.TransitionAt(layout, 170, 172, 6));
            Assert.Equal(-1, FsmMap.TransitionAt(layout, 15, 10, 6));
            Assert.Equal(-1, FsmMap.TransitionAt(layout, 260, 40, 6));
        }

        [Fact]
        public void AnArrowheadPointsItsWay()
        {
            Assert.Equal(new[] { new[] { 10, 10 }, new[] { 5, 18 }, new[] { 15, 18 } }, FsmMap.Arrowhead(10, 10, "up"));
            Assert.Equal(new[] { new[] { 10, 10 }, new[] { 5, 2 }, new[] { 15, 2 } }, FsmMap.Arrowhead(10, 10, "down"));
            Assert.Equal(new[] { new[] { 10, 10 }, new[] { 18, 5 }, new[] { 18, 15 } }, FsmMap.Arrowhead(10, 10, "left"));
            Assert.Equal(new[] { new[] { 10, 10 }, new[] { 2, 5 }, new[] { 2, 15 } }, FsmMap.Arrowhead(10, 10, "right"));
        }
    }
}
