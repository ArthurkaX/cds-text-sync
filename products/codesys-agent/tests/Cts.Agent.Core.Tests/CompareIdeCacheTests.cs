using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Core.Tests
{
    public sealed class CompareIdeCacheTests : IDisposable
    {
        readonly string root = Path.Combine(Path.GetTempPath(), "cts-compare-cache-" + Guid.NewGuid().ToString("N"));
        readonly string repo;
        readonly string project;
        readonly string snapshot = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml");
        int exports;
        int objectExports;
        int partialExports;
        List<string> fetchedGuids = new List<string>();

        public CompareIdeCacheTests()
        {
            repo = Path.Combine(root, "repo");
            project = Path.Combine(root, "project.project");
            Directory.CreateDirectory(repo);
            Directory.CreateDirectory(Path.Combine(repo, "project-view"));
            Git("init -q -b main");
            Git("config user.name Test");
            Git("config user.email test@example.com");
            File.WriteAllText(Path.Combine(repo, "README"), "test\n");
            File.WriteAllText(Path.Combine(repo, "project-view", ".keep"), "test\n");
            Git("add README");
            Git("commit -q -m base");
            SyncBase.Record(repo, "project-view", new List<string>());
        }

        [Fact]
        public void SecondCompareUsesCachedViewAndReturnsSameRecords()
        {
            var first = Compare(project, ExportReply);
            var second = Compare(project, ExportReply);
            Assert.Equal(1, exports);
            Assert.Equal(0, objectExports);
            Assert.Equal("miss", ((IDictionary<string, object>)first["timings"])["ide_cache"]);
            Assert.Equal("hit", ((IDictionary<string, object>)second["timings"])["ide_cache"]);
            Assert.Equal(Cts.Agent.Json.Serialize(first["objects"]), Cts.Agent.Json.Serialize(second["objects"]));
        }

        [Fact]
        public void CompareReportsIdeChangesWithoutChangingTheSyncFolder()
        {
            var beforeFiles = Directory.GetFiles(Path.Combine(repo, "project-view"), "*", SearchOption.AllDirectories)
                .ToDictionary(path => path.Substring(Path.Combine(repo, "project-view").Length + 1), File.ReadAllBytes);
            var baseCommit = GitRepository.Run(repo, "rev-parse refs/cts/base").Trim();
            var head = GitRepository.Run(repo, "rev-parse HEAD").Trim();
            var status = GitRepository.Run(repo, "status --porcelain");

            var result = Compare(project, ChangedMethodReply);

            var summary = (IDictionary<string, object>)result["summary"];
            Assert.True(Convert.ToInt32(summary["ide_changed"]) > 0);
            var objects = (IDictionary<string, object>)result["objects"];
            Assert.Contains(((IEnumerable<object>)objects["ide_changed"]).Cast<IDictionary<string, object>>(), item =>
                Convert.ToString(item["name"]) == "M_Toggle");
            Assert.Equal(beforeFiles.Count, Directory.GetFiles(Path.Combine(repo, "project-view"), "*", SearchOption.AllDirectories).Length);
            foreach (var file in beforeFiles)
                Assert.Equal(file.Value, File.ReadAllBytes(Path.Combine(repo, "project-view", file.Key)));
            Assert.Equal(baseCommit, GitRepository.Run(repo, "rev-parse refs/cts/base").Trim());
            Assert.Equal(head, GitRepository.Run(repo, "rev-parse HEAD").Trim());
            Assert.Equal(status, GitRepository.Run(repo, "status --porcelain"));
            Assert.False(File.Exists(Path.Combine(repo, ".git", "cts", "base-project")));
        }

        [Fact]
        public void An_object_deleted_in_the_IDE_is_listed_as_deleted_and_points_to_sync_not_to_its_text()
        {
            IDictionary<string, object> Row(string name, string reason) => new Dictionary<string, object>
                { { "name", name }, { "path", name + ".xml" }, { "category", "ide_changed" }, { "reason", reason } };
            Answer Build(params IDictionary<string, object>[] rows) => ComparePlanner.Build(new Dictionary<string, object>
            {
                { "base", true }, { "ide", "ide" },
                { "summary", new Dictionary<string, object> { { "unchanged", 1 }, { "modified", 0 }, { "added", 0 }, { "deleted", 0 }, { "not_importable", 0 }, { "ide_changed", rows.Length } } },
                { "objects", new Dictionary<string, object> { { "ide_changed", rows.ToList() } } },
            });
            var deleted = Row("Screen", "deleted in the IDE; cts sync removes the file");

            var onlyDeleted = Build(deleted);
            Assert.Equal(new[] { "ide_changed Screen Screen.xml: deleted in the IDE", "Next: cts sync removes the files of the objects deleted in the IDE (git keeps them); cts import --force creates them again from the files" }, onlyDeleted.Details);

            var both = Build(deleted, Row("Manager", "changed in the IDE; cts sync writes it to disk"));
            Assert.Equal("ide_changed Manager Manager.xml", both.Details[1]);
            Assert.StartsWith("Next: cts read-object NAME --body", both.Details[2]);
            Assert.EndsWith("cts sync also removes the files of the ones deleted in the IDE", both.Details[2]);
        }

        [Fact]
        public void An_object_changed_on_both_sides_is_marked_and_points_to_the_dry_run()
        {
            var answer = ComparePlanner.Build(new Dictionary<string, object>
            {
                { "base", true }, { "ide", "ide" },
                { "summary", new Dictionary<string, object> { { "unchanged", 1 }, { "modified", 2 }, { "added", 0 }, { "deleted", 0 }, { "not_importable", 0 }, { "both", 1 } } },
                { "objects", new Dictionary<string, object> { { "modified", new List<IDictionary<string, object>>
                {
                    new Dictionary<string, object> { { "name", "F_Scale" }, { "path", "F_Scale.st" }, { "ide_changed", true } },
                    new Dictionary<string, object> { { "name", "MAIN" }, { "path", "MAIN.st" } },
                } } } },
            });
            Assert.Equal("modified F_Scale F_Scale.st: changed in the IDE too", answer.Details[0]);
            Assert.Equal("modified MAIN MAIN.st", answer.Details[1]);
            Assert.StartsWith("Next: cts import --dry-run says whether", answer.Details[2]);
        }

        [Fact]
        public void Compare_says_which_folder_its_paths_are_under()
        {
            Answer Build(string view, bool rows) => ComparePlanner.Build(new Dictionary<string, object>
            {
                { "base", true }, { "ide", "ide" }, { "view", view },
                { "summary", new Dictionary<string, object> { { "unchanged", 1 }, { "modified", rows ? 1 : 0 }, { "added", 0 }, { "deleted", 0 }, { "not_importable", 0 } } },
                { "objects", new Dictionary<string, object> { { "modified", (rows ? new[] { new Dictionary<string, object> { { "name", "FB" }, { "path", "App/FB.st" } } } : new Dictionary<string, object>[0]).ToList<IDictionary<string, object>>() } } },
            });

            Assert.Equal(new[] { "modified FB App/FB.st", "the paths are of files under project-view/ in the sync folder" }, Build("project-view", true).Details);
            Assert.Equal(new[] { "modified FB App/FB.st" }, Build(".", true).Details);
            Assert.Empty(Build("project-view", false).Details);
        }

        [Fact]
        public void CompareReportsAnotherRecordedProjectWithoutWriting()
        {
            var other = Path.Combine(root, "previous.project");
            SyncBase.SaveProject(repo, other);
            var view = Path.Combine(repo, "project-view");
            var beforeFiles = Directory.GetFiles(view, "*", SearchOption.AllDirectories)
                .ToDictionary(path => path.Substring(view.Length + 1), File.ReadAllBytes);
            var baseCommit = GitRepository.Run(repo, "rev-parse refs/cts/base").Trim();
            var head = GitRepository.Run(repo, "rev-parse HEAD").Trim();
            var status = GitRepository.Run(repo, "status --porcelain");

            var result = Compare(project, ExportReply);

            Assert.Contains(((IEnumerable<object>)result["info"]).Cast<string>(), line =>
                line.StartsWith("The last sync of this folder was with " + other, StringComparison.Ordinal));
            Assert.Equal(false, result["base"]);
            Assert.Equal(other, result["base_project"]);
            Assert.Equal("base=other", ComparePlanner.Build(result).Pairs.Where(pair => pair.Key == "base").Select(pair => pair.Key + "=" + pair.Value).Single());
            Assert.Equal(baseCommit, GitRepository.Run(repo, "rev-parse refs/cts/base").Trim());
            Assert.Equal(head, GitRepository.Run(repo, "rev-parse HEAD").Trim());
            Assert.Equal(status, GitRepository.Run(repo, "status --porcelain"));
            Assert.Equal(other, SyncBase.OtherProject(repo, project));
            foreach (var file in beforeFiles)
                Assert.Equal(file.Value, File.ReadAllBytes(Path.Combine(view, file.Key)));
        }

        [Fact]
        public void OldAgentWithoutSkeletonFallsBackToFullExport()
        {
            Compare(project, ExportReply);
            var result = Compare(project, (method, args) =>
            {
                if (method == "project.skeleton") throw new AgentException("unknown_method", "unknown method");
                return ExportReply(method, args);
            });
            Assert.Equal(2, exports);
            Assert.Equal("miss", ((IDictionary<string, object>)result["timings"])["ide_cache"]);
        }

        [Fact]
        public void CacheNamingACommitGitLacksFallsBackToFullExport()
        {
            var first = Compare(project, ExportReply);
            var cachePath = Path.Combine(repo, ".git", "cts", "ide-cache.json");
            var cache = (IDictionary<string, object>)Cts.Agent.Json.Parse(File.ReadAllText(cachePath));
            cache["commit"] = new string('a', 40);
            File.WriteAllText(cachePath, Cts.Agent.Json.Serialize(cache));
            var second = Compare(project, ExportReply);
            Assert.Equal(2, exports);
            Assert.Equal("miss", ((IDictionary<string, object>)second["timings"])["ide_cache"]);
            Assert.Equal(Cts.Agent.Json.Serialize(first["objects"]), Cts.Agent.Json.Serialize(second["objects"]));
        }

        [Fact]
        public void CacheOfAnotherCtsBuildFallsBackToFullExport()
        {
            Compare(project, ExportReply);
            var cachePath = Path.Combine(repo, ".git", "cts", "ide-cache.json");
            var cache = (IDictionary<string, object>)Cts.Agent.Json.Parse(File.ReadAllText(cachePath));
            cache["build"] = "3.4.0 (commit 00000000)";
            File.WriteAllText(cachePath, Cts.Agent.Json.Serialize(cache));
            var second = Compare(project, ExportReply);
            Assert.Equal(2, exports);
            Assert.Equal("miss", ((IDictionary<string, object>)second["timings"])["ide_cache"]);
        }

        [Fact]
        public void CacheForAnotherProjectIsNotQueried()
        {
            Compare(project, ExportReply);
            var otherProject = Path.Combine(root, "other.project");
            var result = Compare(otherProject, (method, args) =>
            {
                if (method == "project.skeleton") return SkeletonReply();
                Assert.Equal("project.export", method);
                return ExportReply(method, args);
            });
            Assert.Equal(2, exports);
            Assert.Equal("miss", ((IDictionary<string, object>)result["timings"])["ide_cache"]);
        }

        [Fact]
        public void StoreReadsOnlyTheChangedFileFromAPatchedView()
        {
            var original = new MemoryViewFiles();
            original.Write("A.xml", System.Text.Encoding.UTF8.GetBytes("old A"));
            original.Write("B.xml", System.Text.Encoding.UTF8.GetBytes("old B"));
            var commit = CompareTool.Store(repo, "project-view", original, GitRepository.ReadFacts(repo), null);
            var baseline = new GitTreeViewFiles(repo, commit, "project-view");
            var written = new MemoryViewFiles();
            written.Write("A.xml", System.Text.Encoding.UTF8.GetBytes("new A"));
            var overlay = new OverlayViewFiles(baseline, written, Array.Empty<string>());
            var counted = new CountingViewFiles(overlay);
            CompareTool.Store(repo, "project-view", counted, GitRepository.ReadFacts(repo), null);
            Assert.Equal(new[] { "A.xml" }, counted.ReadPaths);
            counted.Dispose();
        }

        sealed class CountingViewFiles : IViewFiles, IDisposable
        {
            readonly IViewFiles inner;
            internal readonly List<string> ReadPaths = new List<string>();
            internal CountingViewFiles(IViewFiles inner) { this.inner = inner; }
            public IEnumerable<string> Paths => inner.Paths;
            public byte[] Read(string path) { ReadPaths.Add(path); return inner.Read(path); }
            public IDictionary<string, byte[]> ReadMany(IEnumerable<string> paths) => paths.ToDictionary(path => path, Read);
            public string BlobId(string path) => inner.BlobId(path);
            public void Dispose() => (inner as IDisposable)?.Dispose();
        }

        [Fact]
        public void ChangedMethodFetchesItsPouGroupAndMatchesFullCompare()
        {
            Compare(project, ExportReply);
            var partial = Compare(project, ChangedMethodReply);
            var full = Compare(project, ChangedMethodReply, "--full");
            Assert.Equal("partial", ((IDictionary<string, object>)partial["timings"])["ide_cache"]);
            Assert.Equal(1, partialExports);
            Assert.Equal(3, exports);
            Assert.Equal(Cts.Agent.Json.Serialize(partial["objects"]), Cts.Agent.Json.Serialize(full["objects"]));
            Assert.Contains("a04dd5ed-83d2-4ac4-b199-490b72709fb1", fetchedGuids);
            Assert.Contains("52d091fb-dc8a-40db-9a29-3cf23964be01", fetchedGuids);
            var unrelated = SnapshotReader.Read(snapshot).Nodes.Values.Single(node => node.Name == "FB_Motor").Guid;
            Assert.DoesNotContain(unrelated, fetchedGuids);
            Assert.True(fetchedGuids.Count > 2);
        }

        IDictionary<string, object> ExportReply(string method, IDictionary<string, object> args)
        {
            if (method == "project.skeleton") return SkeletonReply();
            if (method == "objects.export")
            {
                object rawKnown;
                args.TryGetValue("known", out rawKnown);
                var known = rawKnown as IDictionary<string, object> ?? new Dictionary<string, object>();
                var objects = ((IEnumerable<string>)args["guids"]).Select(guid => (object)new Dictionary<string, object>
                {
                    { "guid", Convert.ToString(guid) }, { "timestamp", Convert.ToInt64(known[Convert.ToString(guid)]) }, { "unchanged", true },
                }).ToList();
                objectExports++;
                return PipeReply(new Dictionary<string, object> { { "objects", objects } });
            }
            Assert.Equal("project.export", method);
            exports++;
            File.Copy(snapshot, Convert.ToString(args["path"]), true);
            return PipeReply(new Dictionary<string, object> { { "ide_stamp", "cache-stamp" }, { "ms", 10L } });
        }

        IDictionary<string, object> ChangedMethodReply(string method, IDictionary<string, object> args)
        {
            if (method == "project.skeleton") return SkeletonReply(true);
            if (method == "objects.export")
            {
                var guids = ((IEnumerable<string>)args["guids"]).ToList();
                fetchedGuids = guids;
                var known = (IDictionary<string, object>)args["known"];
                var objects = guids.Select(guid =>
                {
                    var timestamp = Convert.ToInt64(known[guid]);
                    var changed = guid == "a04dd5ed-83d2-4ac4-b199-490b72709fb1";
                    return (object)new Dictionary<string, object>
                    {
                        { "guid", guid }, { "timestamp", changed ? timestamp + 1 : timestamp },
                        { "unchanged", !changed },
                    };
                }).ToList();
                return PipeReply(new Dictionary<string, object> { { "objects", objects } });
            }
            if (method == "project.export")
            {
                exports++;
                if (args.ContainsKey("guids")) fetchedGuids = ((IEnumerable<string>)args["guids"]).ToList();
                var changedPath = Path.Combine(root, "method-edited.xml");
                WriteChangedSnapshot(changedPath, args.ContainsKey("guids") ? ((IEnumerable<string>)args["guids"]).ToHashSet(StringComparer.OrdinalIgnoreCase) : null);
                if (args.ContainsKey("guids")) partialExports++;
                File.Copy(changedPath, Convert.ToString(args["path"]), true);
                return PipeReply(new Dictionary<string, object> { { "ide_stamp", "cache-stamp" }, { "ms", 10L } });
            }
            return ExportReply(method, args);
        }

        void WriteChangedSnapshot(string path, HashSet<string> guids)
        {
            var document = XDocument.Load(snapshot, LoadOptions.PreserveWhitespace);
            var ns = document.Root.Name.Namespace;
            var methodEntry = document.Descendants(ns + "Single").Single(entry =>
                entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid")?.Value.Trim().Trim('{', '}') == "a04dd5ed-83d2-4ac4-b199-490b72709fb1");
            var body = methodEntry.Descendants().First(element => (string)element.Attribute("Name") == "TextBlobForSerialisation" && element.Value.Contains("xOpen := NOT xOpen;"));
            body.Value = body.Value.Replace("xOpen := NOT xOpen;", "xOpen := TRUE;");
            if (guids != null)
                foreach (var entry in document.Descendants(ns + "List2").Where(element => (string)element.Attribute("Name") == "EntryList").SelectMany(list => list.Elements(ns + "Single")).ToList())
                {
                    var guid = entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid")?.Value.Trim().Trim('{', '}');
                    if (!guids.Contains(guid)) entry.Remove();
                }
            document.Save(path, SaveOptions.DisableFormatting);
        }

        IDictionary<string, object> SkeletonReply(bool changed = false)
        {
            var model = SnapshotReader.Read(snapshot);
            var nodes = model.Nodes.Values.Select(node => (object)new Dictionary<string, object>
            {
                { "guid", node.Guid }, { "parent_guid", node.ParentGuid }, { "name", node.Name }, { "type_guid", node.Type },
                { "path", node.DisplayPath.Cast<object>().ToList() }, { "is_root", false }, { "view_guid", "21af5390-2942-461a-bf89-951aaf6999f1" },
                { "timestamp", Convert.ToInt64(node.Entry.Descendants().First(element => (string)element.Attribute("Name") == "Timestamp").Value) + (changed && node.Guid == "a04dd5ed-83d2-4ac4-b199-490b72709fb1" ? 1 : 0) },
            }).ToList();
            return PipeReply(new Dictionary<string, object> { { "nodes", nodes }, { "ide_stamp", "cache-stamp" } });
        }

        IDictionary<string, object> Compare(string projectPath, Func<string, IDictionary<string, object>, IDictionary<string, object>> handler, params string[] extra)
        {
            var command = CliCommands.Find(new[] { "compare" });
            var options = CliOptions.Parse(new[] { "compare", "--sync-folder", repo }.Concat(extra).ToArray(), null, command);
            var hello = new Hello(42, new Dictionary<string, object>
            {
                { "project", new Dictionary<string, object> { { "path", projectPath }, { "sync_folder", repo } } },
            });
            return ComparePlanner.Plan(new CliCall(command, options, hello, 30, handler));
        }

        static IDictionary<string, object> PipeReply(IDictionary<string, object> value)
        {
            return Cts.Agent.Json.Parse(Cts.Agent.Json.Serialize(value)) as IDictionary<string, object>;
        }

        void Git(string args) => GitRepository.Run(repo, args);

        public void Dispose()
        {
            try { Directory.Delete(root, true); } catch (IOException) { }
        }
    }
}
