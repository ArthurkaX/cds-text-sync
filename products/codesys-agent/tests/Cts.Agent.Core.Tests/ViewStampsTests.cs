using System;
using System.IO;
using System.Text;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ViewStampsTests : IDisposable
    {
        readonly string _view = Path.Combine(Path.GetTempPath(), "cts-stamps-" + Guid.NewGuid().ToString("N"));

        public ViewStampsTests()
        {
            Directory.CreateDirectory(Path.Combine(_view, "POUs"));
            File.WriteAllText(Path.Combine(_view, "POUs", "A.st"), "a");
            File.WriteAllText(Path.Combine(_view, "POUs", "B.st"), "b");
        }

        public void Dispose() => Directory.Delete(_view, true);

        [Fact]
        public void A_file_changed_by_someone_else_is_not_overwritten_and_is_named()
        {
            var stamps = ViewStamps.Take(_view);
            File.WriteAllText(Path.Combine(_view, "POUs", "A.st"), "a, edited meanwhile");
            Assert.False(stamps.Write("POUs/A.st", Encoding.UTF8.GetBytes("from the IDE")));
            Assert.Equal("a, edited meanwhile", File.ReadAllText(Path.Combine(_view, "POUs", "A.st")));
            Assert.True(stamps.Write(Path.Combine(_view, "POUs", "B.st"), Encoding.UTF8.GetBytes("from the IDE")));
            Assert.False(stamps.Moved("POUs/B.st"));
            Assert.Equal(new[] { "POUs/A.st" }, stamps.Changed);
        }

        [Fact]
        public void A_file_made_or_removed_by_someone_else_has_moved_and_one_cts_makes_has_not()
        {
            var stamps = ViewStamps.Take(_view);
            File.Delete(Path.Combine(_view, "POUs", "B.st"));
            File.WriteAllText(Path.Combine(_view, "POUs", "C.st"), "c");
            Assert.True(stamps.Moved("POUs/B.st"));
            Assert.True(stamps.Moved("POUs/C.st"));
            Assert.True(stamps.Write("POUs/New/D.st", Encoding.UTF8.GetBytes("d")));
            Assert.True(stamps.Delete("POUs/A.st"));
            Assert.False(stamps.Moved("POUs/A.st"));
            Assert.False(stamps.Moved("POUs/New/D.st"));
        }
    }
}
