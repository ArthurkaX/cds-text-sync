using System;
using System.IO;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CompareToolTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-compare-tool-" + Guid.NewGuid().ToString("N"));
        readonly string _repo;

        public CompareToolTests()
        {
            _repo = Path.Combine(_root, "repo"); Directory.CreateDirectory(_repo);
            Run("init -q -b main"); Run("config user.name Test"); Run("config user.email test@example.com"); Run("config diff.tool fake"); Run("config difftool.fake.cmd \"echo compare\"");
            Directory.CreateDirectory(Path.Combine(_repo, "project-view"));
            File.WriteAllText(Path.Combine(_repo, "project-view", "A.st"), "PROGRAM A\nEND_PROGRAM\n");
            Run("add -A"); Run("commit -q -m initial");
            File.WriteAllText(Path.Combine(_repo, "staged.txt"), "staged\n"); Run("add staged.txt");
        }

        [Fact]
        public void MergeToolUsesGitMergeToolWhenItNamesASupportedProgram()
        {
            Run("config merge.tool vscode");
            Assert.Equal("vscode", CompareTool.MergeUses(_repo));
        }

        [Fact]
        public void BaseTreeUsesTheViewAsItsPathRoot()
        {
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            using (var nested = new GitTreeViewFiles(_repo, commit, "project-view"))
                Assert.Equal("PROGRAM A\nEND_PROGRAM\n", System.Text.Encoding.UTF8.GetString(nested.Read("A.st")));
            using (var rootView = new GitTreeViewFiles(_repo, commit, "."))
                Assert.Equal("PROGRAM A\nEND_PROGRAM\n", System.Text.Encoding.UTF8.GetString(rootView.Read("project-view/A.st")));
        }

        [Fact]
        public void IdeSnapshotUsesItsOwnRefAndIndex()
        {
            var head = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var snapshot = Path.Combine(_root, "ide"); Directory.CreateDirectory(snapshot);
            File.WriteAllText(Path.Combine(snapshot, "A.st"), "PROGRAM A\nEND_PROGRAM\n");
            var result = CompareTool.Open(_repo, "project-view", new DirectoryViewFiles(snapshot), null, GitRepository.ReadFacts(_repo));
            Assert.Equal(0, result["files"]);
            Assert.Equal(head, GitRepository.Run(_repo, "rev-parse HEAD").Trim());
            GitRepository.Run(_repo, "rev-parse --verify refs/cts/ide^{commit}");
            Assert.Contains("staged.txt", GitRepository.Run(_repo, "diff --cached --name-only"));
            Assert.Equal("PROGRAM A\nEND_PROGRAM\n", File.ReadAllText(Path.Combine(_repo, "project-view", "A.st")));
        }

        [Fact]
        public void AToolGitCannotStartNamesGitsReason()
        {
            Run("config diff.tool kdiff3");
            Run("config difftool.kdiff3.path " + Path.Combine(_root, "missing", "kdiff3"));
            File.WriteAllText(Path.Combine(_repo, "project-view", "A.st"), "PROGRAM A\n// disk\nEND_PROGRAM\n");
            var snapshot = Path.Combine(_root, "ide-for-missing-tool"); Directory.CreateDirectory(snapshot);
            File.WriteAllText(Path.Combine(snapshot, "A.st"), "PROGRAM A\n// ide\nEND_PROGRAM\n");
            var failure = Assert.Throws<InvalidOperationException>(() => CompareTool.Open(_repo, "project-view", new DirectoryViewFiles(snapshot), null, GitRepository.ReadFacts(_repo)));
            Assert.Contains("git difftool exited", failure.Message);
            Assert.Contains("kdiff3", failure.Message.Substring("git difftool exited".Length));
        }

        [Fact]
        public void AToolPathTheUsersGitNamesIsLeftToGit()
        {
            Run("config difftool.kdiff3.path /opt/kdiff3/kdiff3");
            Assert.Null(CompareTool.ToolPath(_repo, "kdiff3"));
            Assert.Null(CompareTool.ToolPath(_repo, "nosuchtool"));
        }

        [Fact]
        public void ToolUsesDiskViewAndLeavesTheUsersIndexAlone()
        {
            var head = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            File.WriteAllText(Path.Combine(_repo, "project-view", "A.st"), "PROGRAM A\n// disk\nEND_PROGRAM\n");
            var snapshot = Path.Combine(_root, "ide-changed"); Directory.CreateDirectory(snapshot);
            File.WriteAllText(Path.Combine(snapshot, "A.st"), "PROGRAM A\n// ide\nEND_PROGRAM\n");
            var result = CompareTool.Open(_repo, "project-view", new DirectoryViewFiles(snapshot), null, GitRepository.ReadFacts(_repo));
            Assert.Equal(1, result["files"]);
            Assert.Equal(head, GitRepository.Run(_repo, "rev-parse HEAD").Trim());
            Assert.Contains("staged.txt", GitRepository.Run(_repo, "diff --cached --name-only"));
        }

        [Fact]
        public void DesktopCopyKeepsTheAttributesWhenGitHasNoTemplates()
        {
            File.WriteAllText(Path.Combine(_repo, ".gitattributes"), "*.xml -merge\n");
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var templates = Path.Combine(_root, "no-templates"); Directory.CreateDirectory(templates);
            Environment.SetEnvironmentVariable("GIT_TEMPLATE_DIR", templates);
            try
            {
                var copy = CompareTool.DesktopCopy(_repo, "project-view", commit, null, null);
                Assert.Equal("*.xml -merge\n", File.ReadAllText(Path.Combine(copy, ".git", "info", "attributes")));
                Assert.Equal("ide", GitRepository.Run(copy, "symbolic-ref --short HEAD").Trim());
                Assert.Equal("main", GitRepository.Run(_repo, "symbolic-ref --short HEAD").Trim());
                Assert.NotEqual(0, GitRun.In(_repo, "rev-parse -q --verify refs/heads/ide").ExitCode);
            }
            finally { Environment.SetEnvironmentVariable("GIT_TEMPLATE_DIR", null); }
        }

        [Fact]
        public void DesktopCopyAgainstACommitWithoutTheViewHasNoViewFiles()
        {
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var bare = GitRepository.Run(_repo, "commit-tree 4b825dc642cb6eb9a060e54bf8d69288fbee4904 -m bare").Trim();
            var copy = CompareTool.DesktopCopy(_repo, "project-view", commit, bare, "bare");
            Assert.False(Directory.Exists(Path.Combine(copy, "project-view")));
            Assert.Equal("ide", GitRepository.Run(copy, "symbolic-ref --short HEAD").Trim());
        }

        void Run(string args) => GitRepository.Run(_repo, args);

        public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } }
    }
}
