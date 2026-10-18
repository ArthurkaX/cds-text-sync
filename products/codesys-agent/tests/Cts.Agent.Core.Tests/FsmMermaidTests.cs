using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class FsmMermaidTests
    {
        [Fact]
        public void MatchesPythonMachineGoldens()
        {
            var path = Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "Golden", "fsm-mermaid.json");
            var entries = (List<object>)Json.Parse(File.ReadAllText(path));
            var sourcePath = Path.Combine(System.AppDomain.CurrentDomain.BaseDirectory, "Golden", "fsm-machines.json");
            var sources = (List<object>)Json.Parse(File.ReadAllText(sourcePath));
            for (var i = 0; i < entries.Count; i++)
            {
                var entry = (Dictionary<string, object>)entries[i];
                var source = (Dictionary<string, object>)sources[i];
                var expected = (List<object>)entry["mermaid"];
                var actual = FsmDetector.Machines((string)source["text"]);
                Assert.Equal(expected.Cast<string>(), actual.Select(FsmMermaid.Render));
            }
        }

        [Fact]
        public void SanitizesAndTruncatesLongGuards()
        {
            var machine = Machine("B", "abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefghijk");
            Assert.Contains("s0 --> s1 : abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyzabcdefgh...", FsmMermaid.Render(machine));
        }

        [Fact]
        public void SanitizesGuardSyntaxCharactersAndNewlines()
        {
            var machine = Machine("B", "x; y: z# \"q\"\nr");
            Assert.Equal("    s0 --> s1 : x  y  z   q  r", FsmMermaid.Render(machine).Split('\n').Last());
        }

        [Fact]
        public void RendersAnySourceAndDeferredComment()
        {
            var machine = Machine("B", "", null);
            machine["deferred"] = true;
            var rendered = FsmMermaid.Render(machine);
            Assert.Contains("    %% transitions write the next-state variable; they take effect on the following scan", rendered);
            Assert.Contains("    ANY : (any state)", rendered);
            Assert.Contains("    ANY --> s1", rendered);
        }

        static Dictionary<string, object> Machine(string target, string guard, string overrideSource = "A")
        {
            return new Dictionary<string, object>
            {
                ["deferred"] = false,
                ["states"] = new List<Dictionary<string, object>>
                {
                    new Dictionary<string, object> { ["label"] = "A" },
                    new Dictionary<string, object> { ["label"] = "B" }
                },
                ["transitions"] = new List<Dictionary<string, object>>
                {
                    new Dictionary<string, object> { ["source"] = overrideSource, ["target"] = target, ["guard"] = guard }
                }
            };
        }
    }
}
