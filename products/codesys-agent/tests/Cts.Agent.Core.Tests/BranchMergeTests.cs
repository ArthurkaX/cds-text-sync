using System;
using System.IO;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class BranchMergeTests : IDisposable
    {
        readonly string _repo = Path.Combine(Path.GetTempPath(), "cts-merge-" + Guid.NewGuid().ToString("N"));

        public BranchMergeTests()
        {
            Directory.CreateDirectory(Path.Combine(_repo, "v", "F"));
            Run("init -q -b main");
            Run("config user.name Test");
            Run("config user.email test@example.com");
            Write(".gitattributes", "*.xml -merge\n");
            foreach (var name in new[] { "a", "b", "c", "d", "f" }) Write("v/F/" + name + ".st", "l1\nl2\nl3\nl4\nl5\nl6\n");
            Write("v/F/e.xml", "<x>1</x>\n");
            Run("add -A");
            Run("commit -q -m base");
            Run("switch -q -c theirs");
            Write("v/F/b.st", "l1\nT2\nl3\nl4\nl5\nl6\n");
            Write("v/F/c.st", "l1\nT2\nl3\nl4\nl5\nl6\n");
            Write("v/F/d.st", "l1\nl2\nT3\nl4\nl5\nl6\n");
            Write("v/F/e.xml", "<x>T</x>\n");
            Write("v/F/g.st", "new\n");
            Write("v/F/h.st", "T1\n");
            File.Delete(Path.Combine(_repo, "v", "F", "f.st"));
            Run("add -A");
            Run("commit -q -m theirs");
            Run("switch -q main");
            Write("v/F/a.st", "O1\nl2\nl3\nl4\nl5\nl6\n");
            Write("v/F/c.st", "l1\nl2\nl3\nl4\nl5\nO6\n");
            Write("v/F/d.st", "l1\nl2\nO3\nl4\nl5\nl6\n");
            Write("v/F/e.xml", "<x>O</x>\n");
            Write("v/F/f.st", "O1\nl2\nl3\nl4\nl5\nl6\n");
            Write("v/F/h.st", "O1\n");
            Run("add -A");
            Run("commit -q -m ours");
        }

        [Fact]
        public void ThePreviewSaysWhatTheMergeDoesToEachFileAndChangesNothing()
        {
            var head = Run("rev-parse HEAD");
            var plan = BranchMerge.Plan(_repo, "theirs");
            var rows = plan.Rows.ToDictionary(row => row.Path.Substring("v/F/".Length), row => row.Result + " " + row.Resolve);
            Assert.Equal("main", plan.Into);
            Assert.Equal("ours ", rows["a.st"]);
            Assert.Equal("theirs ", rows["b.st"]);
            Assert.Equal("merged ", rows["c.st"]);
            Assert.Equal("conflict text", rows["d.st"]);
            Assert.Equal("conflict side", rows["e.xml"]);
            Assert.Equal("conflict side", rows["f.st"]);
            Assert.Equal("theirs ", rows["g.st"]);
            Assert.Equal("conflict text", rows["h.st"]);
            Assert.Equal(head, Run("rev-parse HEAD"));
            Assert.Equal("", Run("status --porcelain"));
        }

        [Fact]
        public void AConflictWithoutASideRefusesAndLeavesTheBranchAsItWas()
        {
            var head = Run("rev-parse HEAD");
            var refusal = Assert.Throws<InvalidOperationException>(() => BranchMerge.Merge(_repo, "theirs", new[] { "v/F/d.st=theirs" }));
            Assert.Contains("3 conflict(s) need a side", refusal.Message);
            Assert.Contains("v/F/e.xml", refusal.Message);
            Assert.Equal(head, Run("rev-parse HEAD"));
            Assert.Equal("", Run("status --porcelain"));
        }

        [Fact]
        public void TheMergeTakesTheChosenSidesAndCommits()
        {
            var plan = BranchMerge.Merge(_repo, "theirs", new[] { "v/F/e.xml=ours", "v/F/f.st=theirs", "theirs" });
            Assert.Equal(Run("rev-parse HEAD"), plan.Commit);
            Assert.Equal(3, Run("rev-list --parents -n 1 HEAD").Split(' ').Length);
            Assert.Equal("Merge theirs into " + Run("branch --show-current"), Run("log -1 --format=%s"));
            Assert.Equal("l1\nl2\nT3\nl4\nl5\nl6\n", Read("v/F/d.st"));
            Assert.Equal("<x>O</x>\n", Read("v/F/e.xml"));
            Assert.False(File.Exists(Path.Combine(_repo, "v", "F", "f.st")));
            Assert.Equal("l1\nT2\nl3\nl4\nl5\nO6\n", Read("v/F/c.st"));
            Assert.Equal("new\n", Read("v/F/g.st"));
            Assert.Equal("", Run("status --porcelain"));
            Assert.True(BranchMerge.Plan(_repo, "theirs").UpToDate);
        }

        [Fact]
        public void AFolderTakesASideForEveryConflictInIt()
        {
            BranchMerge.Merge(_repo, "theirs", new[] { "v/F=ours" });
            Assert.Equal("l1\nl2\nO3\nl4\nl5\nl6\n", Read("v/F/d.st"));
            Assert.Equal("O1\nl2\nl3\nl4\nl5\nl6\n", Read("v/F/f.st"));
        }

        [Fact]
        public void UncommittedChangesRefuseTheMerge()
        {
            Write("v/F/a.st", "edited\n");
            var refusal = Assert.Throws<InvalidOperationException>(() => BranchMerge.Merge(_repo, "theirs", new[] { "ours" }));
            Assert.Contains("uncommitted changes", refusal.Message);
        }

        void Write(string path, string text) => File.WriteAllText(Path.Combine(_repo, path.Replace('/', Path.DirectorySeparatorChar)), text);

        string Read(string path) => File.ReadAllText(Path.Combine(_repo, path.Replace('/', Path.DirectorySeparatorChar)));

        string Run(string args)
        {
            var result = GitRun.In(_repo, args);
            Assert.True(result.ExitCode == 0, result.Message);
            return result.Output.Trim();
        }

        public void Dispose()
        {
            try { Directory.Delete(_repo, true); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }
}
