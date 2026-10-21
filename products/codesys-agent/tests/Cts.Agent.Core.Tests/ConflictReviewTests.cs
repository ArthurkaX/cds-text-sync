using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ConflictReviewTests
    {
        const string DryRun = @"{""base"": true, ""conflicts"": [
            {""name"": ""MAIN"", ""path"": ""Application/MAIN.st"", ""key"": ""Application/MAIN"",
             ""disk"": ""PROGRAM MAIN\r\n// cts:implementation\r\nx := 1;"", ""ide"": ""PROGRAM MAIN\n// cts:implementation\nx := 2;""},
            {""name"": ""Close"", ""path"": ""Application/FB_Valve.st"", ""key"": ""Application/FB_Valve/Close"", ""disk"": ""a"", ""ide"": ""b""}],
            ""conflict_next"": ""Keep the disk text""}";

        [Fact]
        public void A_dry_runs_conflicts_read_as_objects_with_both_texts_none_chosen()
        {
            var items = ConflictReview.Parse(DryRun);
            Assert.Equal(new[] { "Application/MAIN", "Application/FB_Valve/Close" }, items.Select(item => item.Key));
            Assert.Equal("PROGRAM MAIN\n// cts:implementation\nx := 1;", items[0].Disk);
            Assert.Equal("PROGRAM MAIN\n// cts:implementation\nx := 2;", items[0].Ide);
            Assert.All(items, item => Assert.Equal(ConflictSide.Open, item.Side));
            Assert.Empty(ConflictReview.Parse(@"{""base"": true, ""summary"": {}}"));
        }

        [Fact]
        public void Apply_waits_for_every_side_then_takes_each_and_hands_the_rest_to_the_merge_program()
        {
            var items = ConflictReview.Parse(DryRun);
            items[0].Side = ConflictSide.Ide;
            Assert.Null(ConflictReview.Args("import", items));
            items[1].Side = ConflictSide.Disk;
            Assert.Equal(new[] { "import", "--take", "Application/MAIN=ide", "--take", "Application/FB_Valve/Close=disk" }, ConflictReview.Args("import", items));
            items[1].Side = ConflictSide.Hand;
            Assert.Equal(new[] { "export", "--take", "Application/MAIN=ide", "--tool" }, ConflictReview.Args("export", items));
        }

        [Fact]
        public void The_next_open_row_comes_after_the_one_settled_then_from_the_top()
        {
            var items = ConflictReview.Parse(DryRun);
            Assert.Equal(1, ConflictReview.NextOpen(items, 0));
            items[1].Side = ConflictSide.Disk;
            Assert.Equal(0, ConflictReview.NextOpen(items, 1));
            items[0].Side = ConflictSide.Hand;
            Assert.Equal(-1, ConflictReview.NextOpen(items, 0));
        }

        [Fact]
        public void Only_the_plain_run_of_1_or_2_asks_first_and_only_while_both_sides_may_have_changed()
        {
            var items = WidgetMenu.Items(false, "C:\\work", 7, "plant", true);
            var import = items.Single(item => item.Key == '1');
            Assert.True(ConflictReview.AsksFirst(import, import.Args, 2));
            Assert.True(ConflictReview.AsksFirst(import, import.Args, -1));
            Assert.False(ConflictReview.AsksFirst(import, import.Args, 0));
            Assert.False(ConflictReview.AsksFirst(import, import.Forced, 2));
            var compare = items.Single(item => item.Key == '5');
            Assert.False(ConflictReview.AsksFirst(compare, compare.Args, 2));
            Assert.Equal(2, WidgetMenu.Both("ok compare modified=3 ide_changed=2 both=2"));
            Assert.Equal(0, WidgetMenu.Both("ok compare modified=3"));
            Assert.Equal(-1, WidgetMenu.Both("error compare cause=refused"));
        }
    }
}
