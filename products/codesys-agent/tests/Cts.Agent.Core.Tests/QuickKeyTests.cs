using Xunit;

namespace Cts.Agent.Tests
{
    public class QuickKeyTests
    {
        [Theory]
        [InlineData("Alt+Q", "Alt+Q", 0x51, false, true, false)]
        [InlineData("shift + ctrl + q", "Ctrl+Shift+Q", 0x51, true, false, true)]
        [InlineData("Control+Alt+7", "Ctrl+Alt+7", 0x37, true, true, false)]
        [InlineData("F9", "F9", 0x78, false, false, false)]
        [InlineData("Ctrl+f12", "Ctrl+F12", 0x7B, true, false, false)]
        public void AChordIsReadInAnySpellingAndNamedInCtsOwn(string text, string named, int vk, bool ctrl, bool alt, bool shift)
        {
            var key = QuickKey.Parse(text);
            Assert.Equal(named, key.Text);
            Assert.True(key.Matches(vk, ctrl, alt, shift));
        }

        [Theory]
        [InlineData("Q")]
        [InlineData("7")]
        [InlineData("Alt+")]
        [InlineData("Alt+Alt+Q")]
        [InlineData("Win+Q")]
        [InlineData("Alt+F13")]
        [InlineData("Alt+F01")]
        [InlineData("Alt+Space")]
        [InlineData("")]
        [InlineData(null)]
        public void ALetterWithoutAModifierOrAnUnknownKeyIsNoChord(string text)
        {
            Assert.Null(QuickKey.Parse(text));
        }

        [Fact]
        public void TheChordMatchesExactlySoAltGrIsNotAlt()
        {
            Assert.True(QuickKey.Default.Matches(0x51, false, true, false));
            Assert.False(QuickKey.Default.Matches(0x51, true, true, false));
            Assert.False(QuickKey.Default.Matches(0x51, false, true, true));
            Assert.False(QuickKey.Default.Matches(0x57, false, true, false));
        }

        [Theory]
        [InlineData("{\"version\": 1, \"quick_key\": \"Ctrl+Shift+Q\"}", "Ctrl+Shift+Q")]
        [InlineData("{\"version\": 1}", "Alt+Q")]
        [InlineData("{\"quick_key\": \"Q\"}", "Alt+Q")]
        [InlineData("{\"quick_key\": 5}", "Alt+Q")]
        [InlineData("[1]", "Alt+Q")]
        [InlineData("{broken", "Alt+Q")]
        public void TheUserDefaultsNameTheChordOrAltQStands(string json, string named)
        {
            Assert.Equal(named, QuickKey.FromDefaults(json).Text);
        }
    }
}
