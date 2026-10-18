using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class ComparePlannerTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-compare-planner-" + Guid.NewGuid().ToString("N"));
        readonly string _repo;

        public ComparePlannerTests()
        {
            _repo = Path.Combine(_root, "repo"); Directory.CreateDirectory(_repo);
            Git("init -q -b main"); Git("config user.name Test"); Git("config user.email test@example.com");
            Directory.CreateDirectory(Path.Combine(_repo, "project-view"));
        }

        [Fact]
        public void RecordKeepsManyBasePathsWithoutPuttingThemOnTheCommandLine()
        {
            var names = Enumerable.Range(0, 400).Select(number => "Folder With A Long Name " + number.ToString("D4", System.Globalization.CultureInfo.InvariantCulture) + "/Object With A Long Name.st").ToList();
            foreach (var name in names)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(Path.Combine(_repo, "project-view", name)));
                Write(name, "PROGRAM P\nEND_PROGRAM\n");
            }
            Commit(); SyncBase.Record(_repo, "project-view", new List<string>());
            foreach (var name in names) Write(name, "PROGRAM P\nvalue := 1;\nEND_PROGRAM\n");
            Write("New.st", "PROGRAM N\nEND_PROGRAM\n");
            var keep = names.Select(name => "project-view/" + name).Concat(new[] { "project-view/Gone.st" }).ToList();
            SyncBase.Record(_repo, "project-view", keep);
            var recorded = GitRepository.Run(_repo, "rev-parse refs/cts/base").Trim();
            using (var baseView = new GitTreeViewFiles(_repo, recorded, "project-view"))
            {
                Assert.Equal("PROGRAM P\nEND_PROGRAM\n", System.Text.Encoding.UTF8.GetString(baseView.Read(names[399])));
                Assert.Equal("PROGRAM N\nEND_PROGRAM\n", System.Text.Encoding.UTF8.GetString(baseView.Read("New.st")));
                Assert.DoesNotContain("Gone.st", baseView.Paths);
            }
        }

        [Fact]
        public void GitTreePreservesUtf8PathsAndBlobBytes()
        {
            Write("Färbung.xml", "grün\n");
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            using (var tree = new GitTreeViewFiles(_repo, commit, "project-view"))
            {
                Assert.Contains("Färbung.xml", tree.Paths);
                Assert.Equal("grün\n", System.Text.Encoding.UTF8.GetString(tree.Read("Färbung.xml")));
            }
        }

        [Fact]
        public async System.Threading.Tasks.Task GitTreeReadsThreeThousandBlobsWithoutBatchPipeDeadlock()
        {
            for (var index = 0; index < 3000; index++)
            {
                File.WriteAllText(Path.Combine(_repo, "project-view", "F" + index.ToString("D4") + ".xml"), new string('x', 190));
            }
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var read = System.Threading.Tasks.Task.Run(() =>
            {
                using (var tree = new GitTreeViewFiles(_repo, commit, "project-view"))
                    return tree.ReadMany(tree.Paths).Count(pair => pair.Value != null);
            });
            var completed = await System.Threading.Tasks.Task.WhenAny(read, System.Threading.Tasks.Task.Delay(TimeSpan.FromSeconds(20)));
            Assert.Same(read, completed);
            Assert.Equal(3000, await read);
        }

        [Fact]
        public void DiskAgainstBaseReadsOnlyChangedAndUntrackedFiles()
        {
            Write("Same.xml", "same\n");
            Write("Edited.xml", "base\n");
            Write("Deleted.xml", "gone\n");
            Write("Färbung.xml", "grün\n");
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            Write("Edited.xml", "edited\n");
            File.Delete(Path.Combine(_repo, "project-view", "Deleted.xml"));
            Write("New.csv", "new\n");
            var index = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "disk-index");
            var diskReads = 0;
            using (var baseline = new GitTreeViewFiles(_repo, commit, "project-view"))
            {
                var disk = new DiskAgainstBaseViewFiles(_repo, "project-view", baseline, index, path =>
                {
                    diskReads++;
                    return File.ReadAllBytes(Path.Combine(_repo, "project-view", path.Replace('/', Path.DirectorySeparatorChar)));
                });
                Assert.Equal("same\n", System.Text.Encoding.UTF8.GetString(disk.Read("Same.xml")));
                Assert.Equal("edited\n", System.Text.Encoding.UTF8.GetString(disk.Read("Edited.xml")));
                Assert.Equal("new\n", System.Text.Encoding.UTF8.GetString(disk.Read("New.csv")));
                Assert.Contains("Färbung.xml", disk.Paths);
                Assert.DoesNotContain("Deleted.xml", disk.Paths);
                Assert.NotNull(disk.BlobId("Same.xml"));
                Assert.Null(disk.BlobId("Edited.xml"));
                Assert.Equal(2, diskReads);
            }
        }

        [Fact]
        public void DiskAgainstBaseIgnoresFilesOnlyTouchedWithoutContentChanges()
        {
            Write("Touched.xml", "same\n");
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            File.SetLastWriteTimeUtc(Path.Combine(_repo, "project-view", "Touched.xml"), DateTime.UtcNow.AddMinutes(1));
            var index = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "disk-index");
            using (var baseline = new GitTreeViewFiles(_repo, commit, "project-view"))
            {
                var disk = new DiskAgainstBaseViewFiles(_repo, "project-view", baseline, index);
                Assert.Contains("Touched.xml", disk.Paths);
                Assert.NotNull(disk.BlobId("Touched.xml"));
            }
        }

        [Fact]
        public void DiskAgainstBaseOmitsDeletedFiles()
        {
            Write("Deleted.xml", "gone\n");
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            File.Delete(Path.Combine(_repo, "project-view", "Deleted.xml"));
            var index = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "disk-index");
            using (var baseline = new GitTreeViewFiles(_repo, commit, "project-view"))
            {
                var disk = new DiskAgainstBaseViewFiles(_repo, "project-view", baseline, index);
                Assert.DoesNotContain("Deleted.xml", disk.Paths);
                Assert.Null(disk.BlobId("Deleted.xml"));
            }
        }

        [Fact]
        public void DiskIndexRefreshesWhenTheBaseMoves()
        {
            Write("Move.xml", "old\n");
            Commit();
            var firstCommit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var index = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "disk-index");
            var diskReads = 0;
            using (var firstBaseline = new GitTreeViewFiles(_repo, firstCommit, "project-view"))
            {
                var first = new DiskAgainstBaseViewFiles(_repo, "project-view", firstBaseline, index, path =>
                {
                    diskReads++;
                    return File.ReadAllBytes(Path.Combine(_repo, "project-view", path.Replace('/', Path.DirectorySeparatorChar)));
                });
                Assert.Equal("old\n", System.Text.Encoding.UTF8.GetString(first.Read("Move.xml")));
            }
            Write("Other.xml", "new\n");
            Commit();
            var secondCommit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            using (var secondBaseline = new GitTreeViewFiles(_repo, secondCommit, "project-view"))
            {
                var second = new DiskAgainstBaseViewFiles(_repo, "project-view", secondBaseline, index, path =>
                {
                    diskReads++;
                    return File.ReadAllBytes(Path.Combine(_repo, "project-view", path.Replace('/', Path.DirectorySeparatorChar)));
                });
                Assert.NotNull(second.BlobId("Move.xml"));
                Assert.Equal("old\n", System.Text.Encoding.UTF8.GetString(second.Read("Move.xml")));
                Assert.Equal(0, diskReads);
            }
        }

        [Fact]
        public void DiskIndexLockMakesTheStatViewFailForDirectoryFallback()
        {
            Write("A.xml", "a\n");
            Commit();
            var commit = GitRepository.Run(_repo, "rev-parse HEAD").Trim();
            var index = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "disk-index");
            Directory.CreateDirectory(Path.GetDirectoryName(index));
            File.WriteAllText(index + ".lock", "held");
            using (var baseline = new GitTreeViewFiles(_repo, commit, "project-view"))
                Assert.Throws<InvalidOperationException>(() => new DiskAgainstBaseViewFiles(_repo, "project-view", baseline, index));
            Assert.Equal("a\n", File.ReadAllText(Path.Combine(_repo, "project-view", "A.xml")));
        }

        [Fact]
        public void CompareFallsBackToDirectoryWhenDiskIndexLockIsHeld()
        {
            Write("Changed.xml", "base\n");
            Write("Same.xml", "same\n");
            Commit();
            SyncBase.Record(_repo, "project-view", new List<string>());
            var baseCommit = GitRepository.Run(_repo, "rev-parse refs/cts/base").Trim();
            Write("Changed.xml", "disk\n");
            var stampPath = Path.Combine(GitRepository.Run(_repo, "rev-parse --absolute-git-dir").Trim(), "cts", "ide-stamp.json");
            SyncBase.SaveStamp(stampPath, Path.Combine(_root, "project.project"), "stamp", baseCommit);
            File.WriteAllText(Path.Combine(Path.GetDirectoryName(stampPath), "disk-index.lock"), "held");
            var command = CliCommands.Find(new[] { "compare" });
            var options = CliOptions.Parse(new[] { "compare", "--sync-folder", _repo }, null, command);
            var hello = new Hello(42, new Dictionary<string, object>
            {
                { "ide_stamp", "stamp" },
                { "project", new Dictionary<string, object> { { "path", Path.Combine(_root, "project.project") }, { "sync_folder", _repo } } },
            });
            var call = new CliCall(command, options, hello, 30, (method, args) => throw new InvalidOperationException("unexpected agent call " + method));
            var data = ComparePlanner.Plan(call);
            var summary = (IDictionary<string, object>)data["summary"];
            Assert.Equal(1, summary["modified"]);
            Assert.Equal(1, summary["unchanged"]);
            var objects = (IDictionary<string, object>)data["objects"];
            var modified = ((System.Collections.IEnumerable)objects["modified"]).Cast<IDictionary<string, object>>().Single();
            Assert.Equal("Changed.xml", modified["path"]);
            Assert.Equal("Changed", modified["name"]);
            var timings = (IDictionary<string, object>)data["timings"];
            Assert.All(new[] { "base_s", "ide_s", "disk_s", "compare_s" }, key => Assert.Contains(key, timings.Keys));
            Assert.Equal("unchanged", data["ide"]);
        }

        void Write(string path, string text) => File.WriteAllText(Path.Combine(_repo, "project-view", path), text);
        void Commit() { Git("add -A"); Git("commit -q -m snapshot"); }
        void Git(string args) => GitRepository.Run(_repo, args);
        public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } }
    }
}
