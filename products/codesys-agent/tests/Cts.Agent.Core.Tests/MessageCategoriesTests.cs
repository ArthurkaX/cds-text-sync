using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class MessageCategoriesTests
    {
        const string Build = "97f48d64-a2a3-4856-b640-75c046e37ea9";
        const string Export = "0c5d0a8e-3e4b-4c3e-9b1a-2f1e5d6c7b8a";

        static List<Dictionary<string, object>> Available()
        {
            return new List<Dictionary<string, object>>
            {
                new Dictionary<string, object> { { "guid", "" }, { "description", "Offline Help" } },
                new Dictionary<string, object> { { "guid", Export }, { "description", "Export/Import" } },
                new Dictionary<string, object> { { "guid", Build }, { "description", "Build" } },
            };
        }

        [Fact]
        public void NoneNamedIsBuild()
        {
            var available = Available();
            Assert.Same(available[2], MessageCategories.Pick("", available));
            Assert.Same(available[2], MessageCategories.Pick(null, available));
        }

        [Fact]
        public void AGuidMatchesWhateverItsBracesAndCase()
        {
            var available = Available();
            Assert.Same(available[1], MessageCategories.Pick("{" + Export.ToUpperInvariant() + "}", available));
            Assert.Same(available[2], MessageCategories.Pick(" " + Build + " ", available));
        }

        [Fact]
        public void ADescriptionMatchesWhateverItsCase()
        {
            var available = Available();
            Assert.Same(available[1], MessageCategories.Pick("export/import", available));
            Assert.Same(available[0], MessageCategories.Pick("Offline Help", available));
        }

        [Fact]
        public void AnUnknownCategoryListsTheAvailableOnes()
        {
            var error = Assert.Throws<ProtocolException>(() => MessageCategories.Pick("does-not-exist", Available()));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            Assert.Contains("Unknown message category 'does-not-exist'", error.Message);
            Assert.Contains("Export/Import (" + Export + ")", error.Message);
            Assert.Contains("Build (" + Build + ")", error.Message);
        }

        [Fact]
        public void AnEmptyListStillNamesTheCategoryAsked()
        {
            var error = Assert.Throws<ProtocolException>(() => MessageCategories.Pick(Export, new List<Dictionary<string, object>>()));
            Assert.Contains("'" + Export + "'", error.Message);
            Assert.Contains("(the IDE listed none)", error.Message);
        }

        [Fact]
        public void BuildBeforeTheFirstCompileIsACategoryOfItsOwn()
        {
            // A fresh IDE registers the compiler's category with its first compile.
            var available = Available();
            available.RemoveAt(2);
            foreach (var asked in new[] { "", null, "build", "{" + Build + "}" })
            {
                var picked = MessageCategories.Pick(asked, available);
                Assert.DoesNotContain(picked, available);
                Assert.Equal(Build, picked["guid"]);
                Assert.Equal("Build", picked["description"]);
            }
        }

        [Fact]
        public void LastKeepsTheNewestOldestFirst()
        {
            var messages = new List<string> { "a", "b", "c" };
            Assert.Equal(new[] { "b", "c" }, MessageCategories.Last(messages, 2));
            Assert.Equal(new[] { "a", "b", "c" }, MessageCategories.Last(messages, 0));
            Assert.Equal(new[] { "a", "b", "c" }, MessageCategories.Last(messages, 9));
            Assert.Throws<ProtocolException>(() => MessageCategories.Last(messages, -1));
        }
    }
}
