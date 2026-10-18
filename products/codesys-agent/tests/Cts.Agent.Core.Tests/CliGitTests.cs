using System;
using System.IO;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CliGitTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-git-" + Guid.NewGuid().ToString("N"));
        readonly string _repo;
        public CliGitTests()
        {
            Directory.CreateDirectory(_root);
            _repo = Path.Combine(_root, "work"); Directory.CreateDirectory(_repo);
            Run(_repo, "init -q -b main"); Run(_repo, "config user.name Test"); Run(_repo, "config user.email test@example.com");
            File.WriteAllText(Path.Combine(_repo, "a.txt"), "one\n"); Run(_repo, "add -A"); Run(_repo, "commit -q -m first");
        }
        [Fact]
        public void Branch_and_history_use_the_sync_repository()
        {
            GitRepository.Create(_repo, "feature");
            Assert.Equal("feature", GitRepository.Position(_repo)["branch"]);
            Assert.Contains("main", GitRepository.Branches(_repo));
            Assert.Single(GitRepository.History(_repo, 20, false));
        }
        [Fact]
        public void A_branch_name_with_spaces_gets_dashes()
        {
            Assert.Equal("some-changes", GitRepository.Create(_repo, " some  changes "));
            Assert.Equal("some-changes", GitRepository.Position(_repo)["branch"]);
            Assert.Throws<InvalidOperationException>(() => GitRepository.Create(_repo, "a..b"));
        }
        [Fact]
        public void Push_creates_upstream_on_the_only_remote()
        {
            var bare = Path.Combine(_root, "remote.git"); Run(_root, "init --bare -q " + Quote(bare));
            Run(_repo, "remote add origin " + Quote(bare));
            var result = GitRepository.Push(_repo);
            Assert.Equal("origin/main", result["upstream"]);
            GitRepository.Run(bare, "show-ref --verify --quiet refs/heads/main");
        }
        static void Run(string folder, string args) => GitRepository.Run(folder, args);
        static string Quote(string value) => "\"" + value.Replace("\"", "\\\"") + "\"";
        public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } }
    }
}
