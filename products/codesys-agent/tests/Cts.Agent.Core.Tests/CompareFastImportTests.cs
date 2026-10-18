using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CompareFastImportTests : IDisposable
    {
        readonly string root = Path.Combine(Path.GetTempPath(), "cts-fast-import-" + Guid.NewGuid().ToString("N"));
        string repo;

        [Fact]
        public void StoresTreeHandlesQuotedPathsReusesIdenticalCommitAndBlobs()
        {
            Initialize(false);
            var firstFiles = Files(new KeyValuePair<string, byte[]>("space name.st", new byte[] { 1, 2 }), new KeyValuePair<string, byte[]>("quo\"te.st", new byte[] { 3, 4 }));
            var first = CompareTool.Store(repo, ".", firstFiles, GitRepository.ReadFacts(repo), null);
            var tree = GitRepository.Run(repo, "ls-tree -r -z " + first);
            var reference = Path.Combine(root, "reference");
            Directory.CreateDirectory(reference);
            GitRun.In(reference, "init -q -b main");
            foreach (var path in firstFiles.Paths)
            {
                File.WriteAllBytes(Path.Combine(reference, path), firstFiles.Read(path));
            }
            GitRun.In(reference, "add -A");
            var expectedTree = GitRepository.Run(reference, "ls-files --stage -z").Split('\0').Where(value => value.Length > 0)
                .Select(value => NormalizeIndexEntry(value)).OrderBy(value => value, StringComparer.Ordinal);
            var actualTree = tree.Split('\0').Where(value => value.Length > 0)
                .Select(value => { var tab = value.IndexOf('\t'); var parts = value.Substring(0, tab).Split(' '); return parts[0] + " " + parts[2] + "\t" + value.Substring(tab + 1); }).OrderBy(value => value, StringComparer.Ordinal);
            Assert.Equal(expectedTree, actualTree);
            Assert.Contains("quo\"te.st", tree);
            Assert.Contains("space name.st", tree);
            Assert.Equal(CompareTool.Store(repo, ".", firstFiles, GitRepository.ReadFacts(repo), null), first);
            Assert.Equal(first, GitRepository.Run(repo, "rev-parse refs/cts/ide").Trim());
            var second = CompareTool.Store(repo, ".", Files(new KeyValuePair<string, byte[]>("space name.st", new byte[] { 1, 2 }), new KeyValuePair<string, byte[]>("quo\"te.st", new byte[] { 8, 9 })), GitRepository.ReadFacts(repo), null);
            Assert.Equal(second, GitRepository.Run(repo, "rev-parse refs/cts/ide").Trim());
            var oldId = GitRun.In(repo, "rev-parse " + first + ":\"space name.st\"").Output.Trim();
            var newId = GitRun.In(repo, "rev-parse " + second + ":\"space name.st\"").Output.Trim();
            Assert.Equal(oldId, newId);
            Assert.NotEqual(first, second);
        }

        [Fact]
        public void StoresSha256RepositoryWhenSupported()
        {
            Directory.CreateDirectory(root);
            repo = Path.Combine(root, "repo256");
            Directory.CreateDirectory(repo);
            var init = GitRun.In(repo, "init -q --object-format=sha256");
            if (init == null || init.ExitCode != 0) return;
            Git("config user.name Test");
            Git("config user.email test@example.com");
            var commit = CompareTool.Store(repo, ".", Files(new KeyValuePair<string, byte[]>("a.st", new byte[] { 5 })), GitRepository.ReadFacts(repo), null);
            Assert.Equal(64, commit.Length);
        }

        void Initialize(bool sha256)
        {
            Directory.CreateDirectory(root);
            repo = Path.Combine(root, "repo");
            Directory.CreateDirectory(repo);
            Git(sha256 ? "init -q --object-format=sha256" : "init -q -b main");
            Git("config user.name Test");
            Git("config user.email test@example.com");
        }

        MemoryViewFiles Files(params KeyValuePair<string, byte[]>[] files)
        {
            var result = new MemoryViewFiles();
            foreach (var file in files) result.Write(file.Key, file.Value);
            return result;
        }

        static string NormalizeIndexEntry(string value)
        {
            var tab = value.IndexOf('\t');
            var fields = value.Substring(0, tab).Split(' ');
            return fields[0] + " " + fields[1] + "\t" + value.Substring(tab + 1);
        }

        void Git(string args) => GitRepository.Run(repo, args);

        public void Dispose() { try { Directory.Delete(root, true); } catch (IOException) { } }
    }
}
