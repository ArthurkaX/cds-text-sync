using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.RegularExpressions;
using System.Xml.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ImportCommandTests : IDisposable
    {
        static readonly string Fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-import-" + Guid.NewGuid().ToString("N"));
        readonly string _peer = Path.Combine(Path.GetTempPath(), "cts-update-peer-" + Guid.NewGuid().ToString("N"));
        readonly string _project = @"C:\projects\demo.project";
        readonly string _stamp = "session:0";

        public ImportCommandTests()
        {
            Directory.CreateDirectory(_root);
            File.Copy(Path.Combine(Fixture, "cds-text-sync.json"), Path.Combine(_root, "cds-text-sync.json"));
            Git("init -q -b main"); Git("config user.name Test"); Git("config user.email test@example.com");
            Export((method, args) =>
            {
                Assert.Equal("project.export", method);
                File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]));
                return new Dictionary<string, object>();
            });
        }

        [Fact]
        public void Carries_an_existing_text_edit_and_moves_only_its_base_file()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories)
                .First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            var text = File.ReadAllText(file);
            File.WriteAllText(file, text.Replace("END_PROGRAM", "// disk edit\nEND_PROGRAM"));
            var originalBase = GitRepository.Run(_root, "rev-parse refs/cts/base").Trim();
            IDictionary<string, object> set = null;
            string guid = null;
            IDictionary<string, object> current;
            var parsed = StViewReader.Read(view).Objects.First(item => Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar)) == file);
            current = new Dictionary<string, object>
            {
                { "declaration", Strip(parsed.Declaration) }, { "implementation", parsed.Implementation },
            };
            var call = ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(parsed.Path);
                if (method == "objects.settext")
                {
                    set = new Dictionary<string, object>(args); guid = Convert.ToString(args["guid"]);
                    foreach (var part in new[] { "declaration", "implementation" }) if (args.ContainsKey(part)) current[part] = args[part];
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", new[] { new Dictionary<string, object>(current) { { "guid", guid } } } },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            });
            var result = ImportCommand.Execute(call);
            Assert.True(set != null, Json.Pretty(result));
            Assert.NotNull(set["guid"]);
            Assert.Single((IList<string>)result["updated_text_objects"]);
            Assert.NotEqual(originalBase, GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
            Assert.False(File.Exists(StampPath()));
        }

        [Fact]
        public void ProjectUpdatePullsImportsAndSavesAnOwnersProject()
        {
            var oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
            var projectId = ProjectInfo.ProjectIdOf(_root);
            ProjectInfo.Record(projectId, _root, "demo", true);
            var view = ViewFolder.Of(_root);
            var viewFolder = Path.GetRelativePath(_root, view).Replace('\\', '/');
            Git("add -f -- " + ProcessArgs.Quote(viewFolder));
            Git("add -A");
            Git("commit -q -m baseline");
            var remote = Path.Combine(_root, "remote.git");
            Git("init --bare -q " + ProcessArgs.Quote(remote));
            Git("remote add origin " + ProcessArgs.Quote(remote));
            Git("push -u origin main");
            var cloned = GitRun.In(_root, "clone -q -b main " + ProcessArgs.Quote(remote) + " " + ProcessArgs.Quote(_peer));
            Assert.NotNull(cloned);
            Assert.Equal(0, cloned.ExitCode);
            Peer("config user.name Test");
            Peer("config user.email test@example.com");
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var remoteFile = Path.Combine(_peer, viewFolder.Replace('/', Path.DirectorySeparatorChar), item.File.Replace('/', Path.DirectorySeparatorChar));
            Assert.True(File.Exists(remoteFile), GitRepository.Run(_root, "ls-files") + "\n" + GitRepository.Run(_peer, "ls-files"));
            File.WriteAllText(remoteFile, File.ReadAllText(remoteFile).Replace("END_PROGRAM", "// team change\nEND_PROGRAM"));
            Peer("commit -q -am team");
            Peer("push origin main");
            var current = new Dictionary<string, object>
            {
                { "declaration", Strip(item.Declaration) }, { "implementation", item.Implementation },
            };
            var writes = 0;
            var saves = 0;
            try
            {
                var command = CliCommands.All.Single(candidate => candidate.Name == "project" && candidate.Sub == "update");
                var options = CliOptions.Parse(new[] { "project", "update" }, null, command);
                var project = new Dictionary<string, object> { { "path", _project }, { "sync_folder", _root } };
                var hello = new Hello(42, new Dictionary<string, object> { { "project", project }, { "ide_stamp", _stamp } });
                var call = new CliCall(command, options, hello, 30, (method, args) => (IDictionary<string, object>)Json.Parse(Json.Serialize(
                    method == "project.status" ? new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", false } } } }
                    : method == "project.permissions" ? new Dictionary<string, object> { { "deny", new List<object>() } }
                    : method == "project.source" ? Marked(Convert.ToString(args["source"]))
                    : method == "project.export" ? ExportSnapshot(args)
                    : method == "project.tree" ? Tree(item.Path)
                    : method == "objects.settext" ? SetText(args, current, ref writes)
                    : method == "objects.texts" ? Texts(current, args)
                    : method == "project.save" ? Save(ref saves)
                    : throw new InvalidOperationException("unexpected update agent call " + method))));
                var result = command.Execute(call);
                Assert.True(writes > 0);
                Assert.True(saves == 1, Json.Pretty(result));
                Assert.Equal(true, result["saved"]);
                Assert.NotEqual(((IDictionary<string, object>)result["pulled"])["from"], ((IDictionary<string, object>)result["pulled"])["to"]);
                Assert.Equal("main", ((IDictionary<string, object>)result["to"])["branch"]);
            }
            finally { Environment.SetEnvironmentVariable("XDG_DATA_HOME", oldXdg); }
        }

        // Every command that imports merges from the IDE's and the base's
        // texts: project update once got neither and refused an object the
        // IDE had changed ("cannot identify merge text").
        [Fact]
        public void AComparePlanCarriesTheTextsToMergeWhicheverCommandImports()
        {
            var command = CliCommands.All.Single(candidate => candidate.Name == "project" && candidate.Sub == "update");
            var options = CliOptions.Parse(new[] { "project", "update" }, null, command);
            var project = new Dictionary<string, object> { { "path", _project }, { "sync_folder", _root } };
            var hello = new Hello(42, new Dictionary<string, object> { { "project", project }, { "ide_stamp", _stamp } });
            var call = new CliCall(command, options, hello, 30, (method, args) => (IDictionary<string, object>)Json.Parse(Json.Serialize(
                method == "project.export" ? ExportSnapshot(args)
                : method == "project.permissions" ? new Dictionary<string, object> { { "deny", new List<object>() } }
                : throw new InvalidOperationException("unexpected agent call " + method))));
            var plan = ComparePlanner.TypedPlan(call);
            Assert.NotNull(plan.IdeObjects);
            Assert.NotNull(plan.BaseObjects);
            Assert.All(plan.Records, record => Assert.IsType<CompareRecord>(record));
        }

        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public void ProjectUpdateRestoresPublishedProjectAndReopensAColleaguesProject(bool opensTheTrackedFile)
        {
            var oldXdg = Environment.GetEnvironmentVariable("XDG_DATA_HOME");
            Environment.SetEnvironmentVariable("XDG_DATA_HOME", Path.Combine(_root, "xdg"));
            var projectId = ProjectInfo.ProjectIdOf(_root);
            ProjectInfo.Record(projectId, _root, "demo", false);
            var publishedPath = Path.Combine(_root, "Demo.project");
            var openProject = opensTheTrackedFile ? publishedPath : Path.Combine(Path.GetTempPath(), "cts-colleague-open-" + Guid.NewGuid().ToString("N") + ".project");
            File.WriteAllText(publishedPath, "published project");
            Git("lfs install --local");
            Git("lfs track '*.project'");
            Git("add -A");
            Git("commit -q -m publish");
            File.WriteAllText(openProject, "local project save");
            var publishedCommit = GitRepository.Run(_root, "log -1 --format=%H HEAD -- Demo.project").Trim();
            var remote = Path.Combine(_root, "remote.git");
            Git("init --bare -q " + ProcessArgs.Quote(remote));
            Git("remote add origin " + ProcessArgs.Quote(remote));
            Git("push -u origin main");
            var cloned = GitRun.In(_root, "clone -q -b main " + ProcessArgs.Quote(remote) + " " + ProcessArgs.Quote(_peer));
            Assert.NotNull(cloned);
            Assert.Equal(0, cloned.ExitCode);
            Peer("config user.name Test");
            Peer("config user.email test@example.com");
            var view = ViewFolder.Of(_root);
            var viewFolder = Path.GetRelativePath(_root, view).Replace('\\', '/');
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var remoteFile = Path.Combine(_peer, viewFolder.Replace('/', Path.DirectorySeparatorChar), item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(remoteFile, File.ReadAllText(remoteFile).Replace("END_PROGRAM", "// published branch change\nEND_PROGRAM"));
            Peer("commit -q -am team");
            Peer("push origin main");
            var current = new Dictionary<string, object>
            {
                { "declaration", Strip(item.Declaration) }, { "implementation", item.Implementation },
            };
            var closed = false;
            var opened = false;
            var baseWasPublishViewWhenOpened = false;
            var writes = 0;
            var saves = 0;
            try
            {
                var command = CliCommands.All.Single(candidate => candidate.Name == "project" && candidate.Sub == "update");
                var options = CliOptions.Parse(new[] { "project", "update" }, null, command);
                var project = new Dictionary<string, object> { { "path", openProject }, { "sync_folder", _root } };
                var hello = new Hello(42, new Dictionary<string, object> { { "project", project }, { "ide_stamp", _stamp } });
                var call = new CliCall(command, options, hello, 30, (method, args) => (IDictionary<string, object>)Json.Parse(Json.Serialize(
                    method == "project.status" ? new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", false } } } }
                    : method == "project.source" ? Marked(Convert.ToString(args["source"]))
                    : method == "project.close" ? Close(args, ref closed)
                    : method == "project.open" ? OpenAfterCheckingBase(args, openProject, viewFolder, item.File, publishedCommit, ref opened, ref baseWasPublishViewWhenOpened)
                    : method == "project.permissions" ? new Dictionary<string, object> { { "deny", new List<object>() } }
                    : method == "project.export" ? ExportSnapshot(args)
                    : method == "project.tree" ? Tree(item.Path)
                    : method == "objects.settext" ? SetText(args, current, ref writes)
                    : method == "objects.texts" ? Texts(current, args)
                    : method == "project.save" ? Save(ref saves)
                    : throw new InvalidOperationException("unexpected update agent call " + method))));
                var result = command.Execute(call);
                Assert.True(closed);
                Assert.True(opened);
                Assert.True(baseWasPublishViewWhenOpened);
                Assert.Equal("published project", File.ReadAllText(openProject));
                Assert.True(writes > 0);
                Assert.True(saves == 1, Json.Pretty(result));
                SyncBase.CheckBase(_root);
                var baseFile = viewFolder + "/" + item.File;
                Assert.Equal(GitRepository.Run(_root, "show " + ProcessArgs.Quote("HEAD:" + baseFile)),
                    GitRepository.Run(_root, "show " + ProcessArgs.Quote("refs/cts/base:" + baseFile)));
                Assert.Equal("Demo.project", result["project_file"]);
                Assert.Equal(publishedCommit, result["published"]);
                Assert.False(result.ContainsKey("pull_error"));
            }
            finally
            {
                Environment.SetEnvironmentVariable("XDG_DATA_HOME", oldXdg);
                if (!opensTheTrackedFile && File.Exists(openProject)) File.Delete(openProject);
            }
        }

        IDictionary<string, object> ExportSnapshot(IDictionary<string, object> args)
        {
            File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true);
            return new Dictionary<string, object>();
        }

        static IDictionary<string, object> SetText(IDictionary<string, object> args, IDictionary<string, object> current, ref int writes)
        {
            writes++;
            foreach (var key in new[] { "declaration", "implementation" }) if (args.ContainsKey(key)) current[key] = args[key];
            return new Dictionary<string, object>();
        }

        static IDictionary<string, object> Save(ref int saves)
        {
            saves++;
            return new Dictionary<string, object>();
        }

        static IDictionary<string, object> Texts(IDictionary<string, object> current, IDictionary<string, object> args)
        {
            var item = new Dictionary<string, object>(current);
            item["guid"] = args.ContainsKey("guid") ? args["guid"]
                : args.ContainsKey("guids") ? ((IEnumerable<object>)args["guids"]).First()
                : "11111111-1111-1111-1111-111111111111";
            return new Dictionary<string, object> { { "objects", new List<object> { item } } };
        }

        static IDictionary<string, object> Close(IDictionary<string, object> args, ref bool closed)
        {
            Assert.Equal(true, args["discard"]);
            closed = true;
            return new Dictionary<string, object>();
        }

        static IDictionary<string, object> Open(IDictionary<string, object> args, string path, ref bool opened)
        {
            Assert.Equal(path, args["path"]);
            Assert.Equal("published project", File.ReadAllText(path));
            opened = true;
            return new Dictionary<string, object>();
        }

        IDictionary<string, object> OpenAfterCheckingBase(IDictionary<string, object> args, string path, string viewFolder,
            string relative, string publishedCommit, ref bool opened, ref bool baseWasPublishView)
        {
            var basePath = viewFolder + "/" + relative;
            baseWasPublishView = GitRepository.Run(_root, "show " + ProcessArgs.Quote("refs/cts/base:" + basePath))
                == GitRepository.Run(_root, "show " + ProcessArgs.Quote(publishedCommit + ":" + basePath));
            return Open(args, path, ref opened);
        }

        [Fact]
        public void Dry_run_returns_the_compare_plan_without_writes()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories)
                .First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            var text = File.ReadAllText(file);
            File.WriteAllText(file, text.Replace("END_PROGRAM", "// disk edit\nEND_PROGRAM"));
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return ViewTree(view);
                throw new InvalidOperationException("dry run must use the matching IDE stamp");
            }));
            Assert.True(result.ContainsKey("summary"));
            Assert.False(result.ContainsKey("refused"));
            // It reads the IDE tree, as the import would, and writes nothing.
            Assert.Equal(new[] { "project.tree" }, calls);
        }

        [Fact]
        public void Dry_run_meets_the_refusal_the_import_would()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// disk edit\nEND_PROGRAM"));
            // The IDE tree lacks the edited program, so the import has nothing to write it into.
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
                method == "project.tree" ? Tree(new string[0]) : throw new InvalidOperationException("dry run must not write: " + method)));
            Assert.Equal("cannot identify IDE object for MAIN", result["refused"]);
        }

        [Fact]
        public void A_file_that_does_not_parse_is_named_in_the_refusal()
        {
            var view = ViewFolder.Of(_root);
            File.WriteAllText(Path.Combine(view, "FB_Broken.st"), "FUNCTION_BLOCK FB_Broken\nVAR\nEND_VAR\n");
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
                method == "project.tree" ? ViewTree(view) : throw new InvalidOperationException("dry run must not write: " + method)));
            Assert.StartsWith("FB_Broken.st: cannot read or parse", Convert.ToString(result["refused"]));
        }

        [Fact]
        public void Dry_run_returns_public_object_dictionaries_without_private_keys()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories)
                .First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// typed plan edit\nEND_PROGRAM"));
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
                method == "project.tree" ? ViewTree(view) : throw new InvalidOperationException("dry run must use the matching IDE stamp")));
            var objects = (IDictionary<string, object>)result["objects"];
            var modified = ((System.Collections.IEnumerable)objects["modified"]).Cast<IDictionary<string, object>>().ToList();
            var record = Assert.Single(modified);
            Assert.DoesNotContain(record.Keys, key => key.StartsWith("_", StringComparison.Ordinal));
            Assert.Equal(".st", Path.GetExtension(Convert.ToString(record["path"])).ToLowerInvariant());
        }

        [Fact]
        public void A_folder_is_on_disk_while_its_directory_is_without_its_container_file()
        {
            var view = ViewFolder.Of(_root);
            var container = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => Directory.GetFiles(Path.GetDirectoryName(path), "*.st").Any());
            File.Delete(container);
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
                method == "project.tree" ? ViewTree(view) : throw new InvalidOperationException("dry run must use the matching IDE stamp")));
            var summary = (IDictionary<string, object>)result["summary"];
            Assert.Equal(0, Convert.ToInt32(summary["deleted"]));
        }

        // A new device's or application's container file is still the IDE's to
        // write when the objects below it reached disk without it.
        [Fact]
        public void An_application_container_only_the_IDE_has_is_reported_though_its_objects_are_on_disk()
        {
            var view = ViewFolder.Of(_root);
            var container = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => path.Replace('\\', '/').EndsWith("/Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
            var viewRelative = ExportCommand.Relative(_root, view);
            var basePath = (viewRelative == "." ? "" : viewRelative.TrimEnd('/') + "/") + ExportCommand.Relative(view, container);
            File.Delete(container);
            var tracked = GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/base").Split('\n')
                .Select(path => path.Trim()).Where(path => path.Length > 0 && path != basePath).ToList();
            SyncBase.Record(_root, viewRelative, tracked);
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return ViewTree(view);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, "session:changed"));
            var ideChanged = ((System.Collections.IEnumerable)((IDictionary<string, object>)result["objects"])["ide_changed"]).Cast<IDictionary<string, object>>();
            Assert.Contains(ideChanged, record => Convert.ToString(record["path"]).EndsWith("Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
        }

        [Fact]
        public void SyncRefusedOnlineNamesSyncToRepeat()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// edit\nEND_PROGRAM"));
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(SyncCall(null, (method, args) => throw new InvalidOperationException("no project edit while online"), true)));
            Assert.EndsWith("Run `cts disconnect`, then repeat `cts sync`.", failure.Message);
        }

        [Fact]
        public void ImportRefusesOnlineBeforeAnyProjectEdit()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// edit\nEND_PROGRAM"));
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(ImportCall(null, (method, args) => throw new InvalidOperationException("no project edit while online"), true)));
            Assert.Equal("The IDE is online with the PLC; editing the project while online is not supported. Run `cts disconnect`, then repeat `cts import`.", failure.Message);
            Assert.Equal(1, failure.ExitCode);
        }

        [Fact]
        public void ImportRefusesDeniedWriteBeforeCallingMutationMethods()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// edit\nEND_PROGRAM"));
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(ImportCall(null, (method, args) => throw new InvalidOperationException("mutation must be refused"), deny: new[] { "sync_import_text" })));
            Assert.Equal("Forbidden by the deny list (deny list includes 'sync_import_text')  See `cts permissions`.", failure.Message);
            Assert.Equal(1, failure.ExitCode);
        }

        [Fact]
        public void DeniedDeleteNamesTheObjectsItWouldDelete()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.Delete(file);
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(ImportCall(null, (method, args) => throw new InvalidOperationException("mutation must be refused"), deny: new[] { "delete_pou" })));
            Assert.Equal("Forbidden by the deny list (deny list includes 'delete_pou'): it would delete " + Path.GetFileNameWithoutExtension(file) + " from the project  See `cts permissions`.", failure.Message);
        }

        [Fact]
        public void SyncRefusesABaseRecordedWithAnotherProjectFile()
        {
            var other = Path.Combine(Path.GetDirectoryName(_project), "older copy.project");
            SyncBase.SaveProject(_root, other);
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            })));
            Assert.StartsWith("the last sync of this folder was with " + other + ", so a merge has no common base", failure.Message, StringComparison.Ordinal);
        }

        [Fact]
        public void ImportRefusesWholePlanBeforeWritingAValidTextEdit()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories)
                .First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// edit\nEND_PROGRAM"));
            File.WriteAllText(Path.Combine(view, "unsupported.csv"), "new data");
            var writes = new List<string>();
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                writes.Add(method);
                if (method == "project.tree") return Tree(new[] { "Application" });
                throw new InvalidOperationException("unexpected agent mutation " + method);
            })));
            Assert.Equal("added unsupported.csv: not a changed text list", failure.Message);
            Assert.Equal(new[] { "project.tree" }, writes);
        }

        [Fact]
        public void Replaces_a_changed_native_xml_object_and_reads_it_back()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var content = File.ReadAllText(file).Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>",
                "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>");
            File.WriteAllText(file, content);
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            IDictionary<string, object> replace = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") { replace = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.NotNull(replace);
            Assert.Equal(content, replace["xml"]);
            Assert.Empty((IList<string>)result["to_disk"]);
            Assert.True(!((System.Collections.IEnumerable)result["unapplied_objects"]).Cast<object>().Any(), Json.Pretty(result));
        }

        // A device's own settings live in its container file, which names the device's path.
        [Fact]
        public void Replaces_a_device_whose_container_file_changed()
        {
            var view = ViewFolder.Of(_root);
            var file = Path.Combine(view, "PLC_Stabur", ".cds-object.xml");
            var before = Path.Combine(_root, "before.xml");
            File.Copy(file, before);
            var content = File.ReadAllText(file).Replace("<Single Name=\"Disable\" Type=\"bool\">False</Single>",
                "<Single Name=\"Disable\" Type=\"bool\">True</Single>");
            File.WriteAllText(file, content);
            IDictionary<string, object> replace = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(new[] { "PLC_Stabur" });
                if (method == "objects.replace") { replace = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.export") return NativeReply(replace == null ? before : file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.NotNull(replace);
            Assert.Equal("11111111-1111-1111-1111-111111111111", replace["guid"]);
            Assert.Equal(content, replace["xml"]);
            Assert.False(result.ContainsKey("refused"), Json.Pretty(result));
        }

        [Fact]
        public void A_library_the_replaced_Library_Manager_could_not_load_is_named()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>",
                "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>"));
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") return new Dictionary<string, object>
                {
                    { "libraries", new List<object> { new Dictionary<string, object> { { "name", "ModbusFB, * (CODESYS)" }, { "error", "not installed" } } } },
                };
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var library = Assert.Single((System.Collections.IEnumerable)result["libraries_not_loaded"]);
            Assert.Equal("ModbusFB, * (CODESYS)", ((IDictionary<string, object>)library)["name"]);
        }

        [Fact]
        public void A_device_of_another_version_on_disk_is_refused_with_change_device()
        {
            var view = ViewFolder.Of(_root);
            var file = Path.Combine(view, "PLC_Stabur", ".cds-object.xml");
            var before = Path.Combine(_root, "before.xml");
            File.Copy(file, before);
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"Version\" Type=\"string\">3.5.16.40</Single>",
                "<Single Name=\"Version\" Type=\"string\">3.5.17.0</Single>"));
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(new[] { "PLC_Stabur" });
                if (method == "objects.export") return NativeReply(before, Convert.ToString(((IList<object>)args["guids"])[0]));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.StartsWith("PLC_Stabur/.cds-object.xml: the device is another type or version on disk; "
                + "cts project change-device --device \"PLC_Stabur\" --type 4096 --id \"10c0 0101\" --version 3.5.17.0 makes",
                Convert.ToString(result["refused"]));
            Assert.Equal(new[] { "project.tree", "objects.export" }, calls);
        }

        [Theory]
        [InlineData(true)]
        [InlineData(false)]
        public void A_replaced_screen_CODESYS_stores_its_own_way_landed_unless_the_IDE_kept_it(bool taken)
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Visualization.xml", SearchOption.AllDirectories).Single();
            var before = Path.Combine(_root, "before.xml");
            File.Copy(file, before);
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"Value\" Type=\"string\">Start</Single>",
                "<Single Name=\"Value\" Type=\"string\">Run</Single>"));
            // What CODESYS makes of the file: the new label, and a default it adds.
            var stored = Path.Combine(_root, "stored.xml");
            File.WriteAllText(stored, File.ReadAllText(file).Replace("<Single Name=\"Value\" Type=\"string\">VCENTER</Single>",
                "<Single Name=\"Value\" Type=\"string\">TOP</Single>"));
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Visualization";
            var exports = 0;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") return new Dictionary<string, object>();
                if (method == "objects.export") return NativeReply(++exports == 1 || !taken ? before : stored, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var unapplied = ((System.Collections.IEnumerable)result["unapplied_objects"]).Cast<object>().ToList();
            Assert.Equal(taken ? 0 : 1, unapplied.Count);
        }

        [Fact]
        public void A_saving_import_saves_when_it_replaced_only_a_native_object()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>",
                "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>"));
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var saves = 0;
            var call = ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") return new Dictionary<string, object>();
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                if (method == "project.save") { saves++; return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            });
            call.Options.Params["save"] = true;
            var result = ImportCommand.Execute(call);
            Assert.Equal(1, saves);
            Assert.Equal(true, result["saved"]);
        }

        // An import that changes Task.xml, its agent's replies past the tree from *reply*.
        CliCall NativeTaskImport(Func<string, IDictionary<string, object>, IDictionary<string, object>> reply)
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>",
                "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>"));
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var call = ImportCall(null, (method, args) =>
                method == "project.tree" ? Tree(key.Split('/'))
                : method == "objects.export" ? NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]))
                : method == "project.export" ? SnapshotReply(args, File.ReadAllText(file))
                : reply(method, args) ?? throw new InvalidOperationException("unexpected agent call " + method));
            call.Options.Params["save"] = true;
            return call;
        }

        [Fact]
        public void An_object_the_agent_refuses_is_named_unapplied_and_the_import_answers()
        {
            var call = NativeTaskImport((method, args) =>
                method == "objects.replace" ? throw new AgentException("ide_error", "the IDE refused the XML") : null);
            var result = ImportCommand.Execute(call);
            var miss = ((IEnumerable<object>)result["unapplied_objects"]).Cast<IDictionary<string, object>>().Single();
            Assert.Equal("the IDE refused the XML", miss["error"]);
        }

        [Fact]
        public void A_save_the_agent_refuses_is_named_and_the_import_answers()
        {
            var call = NativeTaskImport((method, args) =>
                method == "objects.replace" ? new Dictionary<string, object>()
                : method == "project.save" ? throw new AgentException("ide_error", "the project file is read-only") : null);
            var result = ImportCommand.Execute(call);
            Assert.Equal("the project file is read-only", result["save_error"]);
            Assert.False(result.ContainsKey("saved") && Equals(result["saved"], true));
        }

        [Fact]
        public void An_export_reply_that_stops_at_its_budget_is_asked_again_for_the_rest()
        {
            var asked = new List<string>();
            var call = ImportCall(null, (method, args) =>
            {
                Assert.Equal("objects.export", method);
                var guids = ((IList<object>)args["guids"]).Select(Convert.ToString).ToList();
                asked.Add(string.Join(",", guids));
                var reply = new Dictionary<string, object> { { "objects", new List<object> { new Dictionary<string, object> { { "guid", guids[0] }, { "meta", "m" }, { "object", "o" } } } } };
                if (guids.Count > 1) reply["rest"] = guids.Skip(1).Cast<object>().ToList();
                return reply;
            });
            var exported = ImportCommand.ExportedObjects(call, new[] { "a", "b", "c" });
            Assert.Equal(new[] { "a", "b", "c" }, exported.Select(item => Convert.ToString(item["guid"])));
            Assert.Equal(new[] { "a,b,c", "b,c", "c" }, asked);
        }

        [Fact]
        public void An_export_reply_that_exports_nothing_and_names_it_all_rest_is_refused()
        {
            var call = ImportCall(null, (method, args) => new Dictionary<string, object> { { "objects", new List<object>() }, { "rest", args["guids"] } });
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.ExportedObjects(call, new[] { "a", "b" }));
            Assert.Equal("bad_reply", failure.Cause);
        }

        [Theory]
        [InlineData("timeout")]
        [InlineData("transport")]
        public void A_call_whose_outcome_is_unknown_ends_the_import(string code)
        {
            var call = NativeTaskImport((method, args) =>
                method == "objects.replace" ? throw new AgentException(code, "no reply") : null);
            var failure = Assert.Throws<CliFailure>(() => ImportCommand.Execute(call));
            Assert.False(failure.Declined);
            Assert.Contains("outcome unknown", failure.Cause);
        }

        [Fact]
        public void Carries_changed_native_meta_properties_from_the_ide_export()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Visualization.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, File.ReadAllText(file).Replace("<Single Name=\"SizeX\" Type=\"int\">1024</Single>",
                "<Single Name=\"SizeX\" Type=\"int\">1280</Single>"));
            Assert.Contains("<Single Name=\"SizeX\" Type=\"int\">1280</Single>", File.ReadAllText(file));
            var baseline = Path.Combine(Fixture, "expected", "PLC_Stabur", "Plc Logic", "Application", "Visualization.xml");
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Visualization";
            IDictionary<string, object> replaced = null;
            var calls = new List<string>();
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.export") return NativeReply(calls.Count == 2 ? baseline : file,
                    Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "objects.replace") { replaced = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.NotNull(replaced);
            Assert.Equal(new[] { "project.tree", "objects.export", "objects.replace", "objects.export", "project.export" }, calls);
            Assert.Contains("477d844b-9b2a-407e-90a4-d36fd6dde2fc", (IList<string>)replaced["properties"]);
        }

        [Fact]
        public void Carries_an_edit_of_a_member_file_beside_a_graphical_pou()
        {
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"), LoadOptions.PreserveWhitespace);
            var valve = document.Descendants(document.Root.Name.Namespace + "Single").Single(entry => entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")
                ?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid")?.Value.Trim().Trim('{', '}') == "52d091fb-dc8a-40db-9a29-3cf23964be01");
            valve.Elements().First(element => (string)element.Attribute("Name") == "Object").Elements().First(element => (string)element.Attribute("Name") == "Implementation")
                .ReplaceNodes(new XElement(document.Root.Name.Namespace + "List", new XAttribute("Name", "NetworkList")));
            var graphical = Path.Combine(_root, "graphical.xml");
            document.Save(graphical, SaveOptions.DisableFormatting);
            File.Delete(StampPath());
            Export((method, args) => { File.Copy(graphical, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); });
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "FB_Valve.A_Reset.xml", SearchOption.AllDirectories).Single();
            var baseline = Path.Combine(_root, "a-reset-base.xml");
            File.Copy(file, baseline);
            File.WriteAllText(file, File.ReadAllText(file).Replace("Name=\"TextBlobForSerialisation\" Type=\"string\">", "Name=\"TextBlobForSerialisation\" Type=\"string\">// disk edit\n"));
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/FB_Valve/A_Reset";
            IDictionary<string, object> replaced = null;
            var calls = new List<string>();
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.export") return NativeReply(calls.Count == 2 ? baseline : file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "objects.replace") { replaced = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.NotNull(replaced);
            Assert.Contains("// disk edit", Convert.ToString(replaced["xml"]));
        }

        [Fact]
        public void A_native_both_sides_changed_in_different_elements_is_merged()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var original = File.ReadAllText(file);
            var priority = Regex.Match(original, "<Single Name=\"Priority\" Type=\"string\">[^<]*</Single>").Value;
            File.WriteAllText(file, original.Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>", "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>"));
            var ideSnapshot = Path.Combine(_root, "ide-edit.xml");
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var taskMeta = document.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "Task"));
            taskMeta.Parent.Descendants().First(element => (string)element.Attribute("Name") == "Priority").Value = "7";
            document.Save(ideSnapshot);
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            IDictionary<string, object> replace = null;
            var exports = 0;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.export" && exports++ == 0) { File.Copy(ideSnapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") { replace = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            var merged = original.Replace("<Single Name=\"AllowEmpty\" Type=\"bool\">False</Single>", "<Single Name=\"AllowEmpty\" Type=\"bool\">True</Single>")
                .Replace(priority, "<Single Name=\"Priority\" Type=\"string\">7</Single>");
            Assert.NotNull(replace);
            Assert.Equal(merged, replace["xml"]);
            Assert.Equal(merged, File.ReadAllText(file));
            Assert.Contains("Task", ((IEnumerable<string>)result["merged"]));
        }

        [Fact]
        public void Force_puts_the_disk_native_back_over_an_IDE_only_change()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var ideSnapshot = Path.Combine(_root, "ide-only.xml");
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var taskMeta = document.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "Task"));
            taskMeta.Parent.Descendants().First(element => (string)element.Attribute("Name") == "Priority").Value = "2";
            document.Save(ideSnapshot);
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            IDictionary<string, object> replace = null;
            var result = ImportCommand.Execute(ImportCall(new[] { "--force" }, (method, args) =>
            {
                if (method == "project.export") { File.Copy(ideSnapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.replace") { replace = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.NotNull(replace);
            Assert.Equal(File.ReadAllText(file), replace["xml"]);
            Assert.Contains("overwrote-ide " + ExportCommand.Relative(view, file), ImportCommand.Build(result).Details);
        }

        [Fact]
        public void Imports_a_copied_native_xml_file_and_places_its_new_guids()
        {
            var view = ViewFolder.Of(_root);
            var source = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var sourceText = File.ReadAllText(source);
            var file = Path.Combine(Path.GetDirectoryName(source), "TaskCopy.xml");
            File.WriteAllText(file, sourceText.Replace("<Single Name=\"Name\" Type=\"string\">Task</Single>",
                "<Single Name=\"Name\" Type=\"string\">TaskCopy</Single>"));
            var parent = ExportCommand.Relative(view, Path.GetDirectoryName(file));
            IDictionary<string, object> imported = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(parent.Split('/'));
                if (method == "objects.import")
                {
                    imported = new Dictionary<string, object>(args);
                    return new Dictionary<string, object> { { "guid", "22222222-2222-2222-2222-222222222222" }, { "parent_guid", args["parent_guid"] } };
                }
                if (method == "objects.export") return NativeReply(file, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(file));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.NotNull(imported);
            Assert.Equal("TaskCopy", NativeValue(File.ReadAllText(file), "Name"));
            Assert.Equal("22222222-2222-2222-2222-222222222222", NativeValue(File.ReadAllText(file), "Guid"));
            Assert.Equal("11111111-1111-1111-1111-111111111111", NativeValue(File.ReadAllText(file), "ParentGuid"));
            Assert.Empty(((System.Collections.IEnumerable)result["unapplied_objects"]).Cast<object>());
        }

        [Fact]
        public void A_new_native_object_lands_with_the_defaults_CODESYS_adds_and_its_file_takes_them()
        {
            var view = ViewFolder.Of(_root);
            var source = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var file = Path.Combine(Path.GetDirectoryName(source), "TaskCopy.xml");
            const string name = "<Single Name=\"Name\" Type=\"string\">TaskCopy</Single>";
            File.WriteAllText(file, File.ReadAllText(source).Replace("<Single Name=\"Name\" Type=\"string\">Task</Single>", name));
            var parent = ExportCommand.Relative(view, Path.GetDirectoryName(file));
            var ideFile = Path.Combine(_root, "ide-form.xml");
            string IdeForm()
            {
                File.WriteAllText(ideFile, File.ReadAllText(file).Replace(name, name + "<Single Name=\"Added\" Type=\"int\">0</Single>"));
                return ideFile;
            }
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(parent.Split('/'));
                if (method == "objects.import") return new Dictionary<string, object> { { "guid", "22222222-2222-2222-2222-222222222222" }, { "parent_guid", args["parent_guid"] } };
                if (method == "objects.export") return NativeReply(IdeForm(), Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(IdeForm()));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Empty(((System.Collections.IEnumerable)result["unapplied_objects"]).Cast<object>());
            Assert.Equal("0", NativeValue(File.ReadAllText(file), "Added"));
        }

        [Fact]
        public void Creates_missing_folders_before_importing_a_native_xml_file()
        {
            var view = ViewFolder.Of(_root);
            var source = Directory.GetFiles(view, "Visualization.xml", SearchOption.AllDirectories).Single();
            var directory = Path.Combine(Path.GetDirectoryName(source), "Visus_Live");
            Directory.CreateDirectory(directory);
            var content = File.ReadAllText(source).Replace("<Single Name=\"Name\" Type=\"string\">Visualization</Single>",
                "<Single Name=\"Name\" Type=\"string\">Visu_Live</Single>");
            var file = Path.Combine(directory, "Visu_Live.xml");
            File.WriteAllText(file, content);
            var parentKey = ExportCommand.Relative(view, Path.GetDirectoryName(source));
            string ide = null;
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(parentKey.Split('/'));
                if (method == "objects.create") return new Dictionary<string, object> { { "guid", "folder-guid" } };
                if (method == "objects.import") return new Dictionary<string, object> { { "guid", "native-guid" }, { "parent_guid", "folder-guid" } };
                if (method == "objects.export") return NativeReply(file, "native-guid");
                if (method == "project.export")
                {
                    var placed = File.ReadAllText(file);
                    ide = Regex.Replace(placed, @"<Single Name=""ParentSVNodeGuid"" Type=""System.Guid"">[^<]*</Single>",
                        "<Single Name=\"ParentSVNodeGuid\" Type=\"System.Guid\">folder-guid</Single>")
                        .Replace("<Single Type=\"string\">Application</Single>\n", "<Single Type=\"string\">Application</Single>\n        <Single Type=\"string\">Visus_Live</Single>\n");
                    Assert.NotEqual(placed, ide);
                    return SnapshotReply(args, ide);
                }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(new[] { "project.tree", "objects.create", "objects.import", "objects.export", "project.export" }, calls);
            // The IDE places the new object in its folder: the file takes the IDE's place for it.
            Assert.Equal(ide, File.ReadAllText(file));
            Assert.Equal(new[] { ExportCommand.Relative(view, file) }, (IList<string>)result["to_disk"]);
        }

        [Fact]
        public void Deletes_a_removed_native_xml_object()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            File.Delete(file);
            string deletedGuid = null;
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(key.Split('/'));
                if (method == "objects.delete") { deletedGuid = Convert.ToString(args["guid"]); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal("11111111-1111-1111-1111-111111111111", deletedGuid);
        }

        [Fact]
        public void Deletes_a_text_list_whose_xml_and_csv_are_gone()
        {
            var view = ViewFolder.Of(_root);
            File.Delete(Path.Combine(view, "POUs", "GlobalTextList.xml"));
            File.Delete(Path.Combine(view, "POUs", "GlobalTextList.csv"));
            string deletedGuid = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "objects.delete") { deletedGuid = Convert.ToString(args["guid"]); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal("11111111-1111-1111-1111-111111111111", deletedGuid);
            Assert.False(result.ContainsKey("refused"), Json.Serialize(result));
        }

        [Fact]
        public void Deletes_a_task_with_task_call_children()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            File.Delete(file);
            string deletedGuid = null;
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree")
                {
                    var tree = Tree(key.Split('/'));
                    var task = tree;
                    foreach (var part in key.Split('/')) task = ((IList<IDictionary<string, object>>)task["children"]).Single();
                    ((IList<IDictionary<string, object>>)task["children"]).Add(new Dictionary<string, object>
                    {
                        { "name", "MAIN" }, { "guid", "call-guid" }, { "type", "413e2a7d-adb1-4d2c-be29-6ae6e4fab820" },
                        { "children", new List<IDictionary<string, object>>() },
                    });
                    return tree;
                }
                if (method == "objects.delete") { deletedGuid = Convert.ToString(args["guid"]); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal("11111111-1111-1111-1111-111111111111", deletedGuid);
        }

        [Fact]
        public void Writes_a_changed_text_default_with_setfield()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n212,Begin\n705,This is stabur Runtime under \n978,This is stabur Runtime under arm VM\n");
            var state = TextListFields();
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return TextListTree();
                if (method == "project.export") return SnapshotReply(args, TextListEntry(Convert.ToString(((IList<object>)args["guids"])[0]), state));
                if (method == "objects.fields") return TextListReply(state);
                if (method == "objects.setfield")
                {
                    var match = Regex.Match(Convert.ToString(args["path"]), @"TextList\[(\d+)\]\.TextDefault");
                    ((IDictionary<string, object>)((IList<object>)state["TextList"])[int.Parse(match.Groups[1].Value)])["TextDefault"] = args["value"];
                    return new Dictionary<string, object>();
                }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Contains("objects.setfield", calls);
            Assert.Equal(new[] { "GlobalTextList" }, (IList<string>)result["updated_field_objects"]);
            Assert.Contains("212,Begin", File.ReadAllText(file));
            // The rows live in the .csv: the .xml the IDE's export rewrites has none.
            Assert.DoesNotContain("TextDefault", File.ReadAllText(Path.ChangeExtension(file, ".xml")));
        }

        [Fact]
        public void Adds_a_text_list_row_with_listadd()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n212,Start\n705,This is stabur Runtime under \n978,This is stabur Runtime under arm VM\n1000,New row\n");
            var state = TextListFields();
            var insertedAt = -1;
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "project.export") return SnapshotReply(args, TextListEntry(Convert.ToString(((IList<object>)args["guids"])[0]), state));
                if (method == "objects.fields") return TextListReply(state);
                if (method == "objects.listadd")
                {
                    insertedAt = Convert.ToInt32(args["at"]);
                    ((IList<object>)state["TextList"]).Insert(insertedAt, new Dictionary<string, object>((IDictionary<string, object>)args["fields"]));
                    return new Dictionary<string, object>();
                }
                if (method == "objects.setfield") return new Dictionary<string, object>();
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(3, insertedAt);
        }

        [Fact]
        public void A_text_list_row_new_in_the_middle_of_the_file_goes_to_the_end_of_the_IDEs_list()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n212,Start\n300,New row\n705,This is stabur Runtime under \n978,This is stabur Runtime under arm VM\n");
            var state = TextListFields();
            var insertedAt = -1;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "project.export") return SnapshotReply(args, TextListEntry(Convert.ToString(((IList<object>)args["guids"])[0]), state));
                if (method == "objects.fields") return TextListReply(state);
                if (method == "objects.listadd")
                {
                    insertedAt = Convert.ToInt32(args["at"]);
                    ((IList<object>)state["TextList"]).Insert(insertedAt, new Dictionary<string, object>((IDictionary<string, object>)args["fields"]));
                    return new Dictionary<string, object>();
                }
                if (method == "objects.setfield") return new Dictionary<string, object>();
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(3, insertedAt);
            Assert.Equal(new[] { "GlobalTextList" }, (IList<string>)result["updated_field_objects"]);
        }

        [Fact]
        public void Adds_no_text_list_row_the_IDE_already_got_from_the_same_import()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n212,Start\n705,This is stabur Runtime under \n978,This is stabur Runtime under arm VM\n1000,New row\n");
            var state = TextListFields();
            var reads = 0;
            var added = 0;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "project.export") return SnapshotReply(args, TextListEntry(Convert.ToString(((IList<object>)args["guids"])[0]), state));
                if (method == "objects.fields")
                {
                    // After the plan the row arrives the way the object's .xml would bring it.
                    if (++reads == 2) ((IList<object>)state["TextList"]).Insert(3, new Dictionary<string, object> { { "TextID", "1000" }, { "TextDefault", "New row" } });
                    return TextListReply(state);
                }
                if (method == "objects.listadd") added++;
                if (method == "objects.listadd" || method == "objects.setfield") return new Dictionary<string, object>();
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(0, added);
            Assert.Equal(new[] { "GlobalTextList" }, (IList<string>)result["updated_field_objects"]);
            Assert.Equal(1, ((IList<object>)state["TextList"]).Count(row => Equals(((IDictionary<string, object>)row)["TextID"], "1000")));
        }

        [Fact]
        public void Removes_a_text_list_row_with_listremove()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n212,Start\n978,This is stabur Runtime under arm VM\n");
            var state = TextListFields();
            var removed = -1;
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "project.export") return SnapshotReply(args, TextListEntry(Convert.ToString(((IList<object>)args["guids"])[0]), state));
                if (method == "objects.fields") return TextListReply(state);
                if (method == "objects.listremove")
                {
                    removed = Convert.ToInt32(args["index"]);
                    ((IList<object>)state["TextList"]).RemoveAt(removed);
                    return new Dictionary<string, object>();
                }
                if (method == "objects.setfield") return new Dictionary<string, object>();
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(1, removed);
        }

        [Fact]
        public void Reordered_text_list_rows_change_nothing_in_the_IDE()
        {
            var file = TextListFile();
            File.WriteAllText(file, "TextID,TextDefault\n705,This is stabur Runtime under \n212,Start\n978,This is stabur Runtime under arm VM\n");
            var writes = new List<string>();
            try
            {
                ImportCommand.Execute(ImportCall(null, (method, args) =>
                {
                    writes.Add(method);
                    if (method == "project.tree") return TextListTree();
                    if (method == "objects.fields") return TextListReply(TextListFields());
                    throw new InvalidOperationException("unexpected call " + method);
                }));
            }
            catch (CliFailure failure) { Assert.DoesNotContain("order", failure.Message); }
            Assert.DoesNotContain(writes, method => method.StartsWith("objects.list", StringComparison.Ordinal) || method == "objects.setfield");
        }

        [Fact]
        public void Reports_a_native_conflict_with_exit_code_two_without_force()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, Regex.Replace(File.ReadAllText(file), "<Single Name=\"Priority\" Type=\"string\">[^<]*</Single>",
                "<Single Name=\"Priority\" Type=\"string\">5</Single>"));
            var ideSnapshot = Path.Combine(_root, "ide-conflict.xml");
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var taskMeta = document.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "Task"));
            taskMeta.Parent.Descendants().First(element => (string)element.Attribute("Name") == "Priority").Value = "2";
            document.Save(ideSnapshot);
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.export") { File.Copy(ideSnapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(key.Split('/'));
                throw new InvalidOperationException("unexpected mutation " + method);
            }, ideStamp: "session:changed"));
            var answer = ImportCommand.Build(result);
            Assert.Equal(2, answer.ExitCode);
            Assert.Contains("conflict Task " + ExportCommand.Relative(view, file), answer.Details);
            Assert.DoesNotContain("objects.replace", calls);
        }

        [Theory]
        [InlineData("disk")]
        [InlineData("ide")]
        public void Sync_take_settles_a_native_conflict_on_the_chosen_side(string side)
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(file, Regex.Replace(File.ReadAllText(file), "<Single Name=\"Priority\" Type=\"string\">[^<]*</Single>",
                "<Single Name=\"Priority\" Type=\"string\">5</Single>"));
            var ideSnapshot = Path.Combine(_root, "ide-conflict.xml");
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var taskMeta = document.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "Task"));
            taskMeta.Parent.Descendants().First(element => (string)element.Attribute("Name") == "Priority").Value = "2";
            document.Save(ideSnapshot);
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var calls = new List<string>();
            var exported = new List<string>();
            var result = ImportCommand.Execute(SyncCall(new[] { "--take", side }, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.export" && args.TryGetValue("guids", out var guids)) exported.AddRange(((IList<object>)guids).Select(Convert.ToString));
                if (method == "project.export") { File.Copy(ideSnapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(key.Split('/'));
                return new Dictionary<string, object>();
            }, ideStamp: "session:changed"));
            Assert.False(result.ContainsKey("conflicts"));
            Assert.Equal(side == "disk", calls.Contains("objects.replace"));
            // The IDE side is the object's own export, written to its file.
            Assert.Equal(side == "ide", exported.Contains("11111111-1111-1111-1111-111111111111"));
        }

        [Fact]
        public void Gives_the_ide_a_text_list_xml_with_the_rows_of_its_csv()
        {
            var view = ViewFolder.Of(_root);
            var file = Path.Combine(view, "POUs", "GlobalTextList.xml");
            File.WriteAllText(file, File.ReadAllText(file).Replace("<List Name=\"Languages\" Type=\"System.Collections.ArrayList\" />",
                "<List Name=\"Languages\" Type=\"System.Collections.ArrayList\"><Single Type=\"string\">en</Single></List>"));
            var baseline = Path.Combine(Fixture, "expected", "POUs", "GlobalTextList.xml");
            var sent = Path.Combine(_root, "sent.xml");
            IDictionary<string, object> replaced = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "objects.export") return NativeReply(replaced == null ? baseline : sent, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "objects.replace")
                {
                    replaced = new Dictionary<string, object>(args);
                    File.WriteAllText(sent, Convert.ToString(args["xml"]));
                    return new Dictionary<string, object>();
                }
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(sent));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var rows = XDocument.Parse(Convert.ToString(replaced["xml"])).Descendants().Where(element => (string)element.Attribute("Type") == "{53da1be7-ad25-47c3-b0e8-e26286dad2e0}").ToList();
            Assert.Equal(new[] { "212", "705", "978" }, rows.Select(row => row.Elements().First(element => (string)element.Attribute("Name") == "TextID").Value));
            Assert.All(rows, row => Assert.Single(row.Elements().Single(element => (string)element.Attribute("Name") == "LanguageTexts").Elements()));
            Assert.False(result.ContainsKey("partial"), Json.Serialize(result));
            // The file keeps its rows in the .csv, the .xml only the rest.
            Assert.DoesNotContain("TextDefault", File.ReadAllText(file));
            Assert.Contains("<Single Type=\"string\">en</Single>", File.ReadAllText(file));
        }

        [Fact]
        public void A_language_added_to_a_text_lists_xml_and_csv_at_once_goes_with_the_xml()
        {
            var csv = TextListFile();
            File.WriteAllText(csv, "TextID,TextDefault,en\n212,Start,Begin\n705,This is stabur Runtime under ,Runtime\n978,This is stabur Runtime under arm VM,Arm\n");
            var file = Path.ChangeExtension(csv, ".xml");
            File.WriteAllText(file, File.ReadAllText(file).Replace("<List Name=\"Languages\" Type=\"System.Collections.ArrayList\" />",
                "<List Name=\"Languages\" Type=\"System.Collections.ArrayList\"><Single Type=\"string\">en</Single></List>"));
            var baseline = Path.Combine(Fixture, "expected", "POUs", "GlobalTextList.xml");
            var sent = Path.Combine(_root, "sent.xml");
            IDictionary<string, object> replaced = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TextListTree();
                if (method == "objects.export") return NativeReply(replaced == null ? baseline : sent, Convert.ToString(((IList<object>)args["guids"])[0]));
                if (method == "objects.replace")
                {
                    replaced = new Dictionary<string, object>(args);
                    File.WriteAllText(sent, Convert.ToString(args["xml"]));
                    return new Dictionary<string, object>();
                }
                if (method == "project.export") return SnapshotReply(args, File.ReadAllText(sent));
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.False(result.ContainsKey("refused"), Json.Pretty(result));
            var texts = XDocument.Parse(Convert.ToString(replaced["xml"])).Descendants()
                .Where(element => (string)element.Attribute("Name") == "LanguageTexts").Select(element => element.Elements().Single().Value);
            Assert.Equal(new[] { "Begin", "Runtime", "Arm" }, texts);
        }

        string TextListFile()
        {
            var view = ViewFolder.Of(_root);
            var file = Path.Combine(view, "POUs", "GlobalTextList.csv");
            Directory.CreateDirectory(Path.GetDirectoryName(file));
            File.Copy(Path.Combine(Fixture, "expected", "POUs", "GlobalTextList.csv"), file, true);
            return file;
        }

        static string TextListEntry(string guid, IDictionary<string, object> state)
        {
            var document = XDocument.Load(Path.Combine(Fixture, "expected", "POUs", "GlobalTextList.xml"), LoadOptions.PreserveWhitespace);
            document.Descendants().First(element => (string)element.Attribute("Name") == "Guid").Value = guid;
            var list = document.Descendants().First(element => (string)element.Attribute("Name") == "TextList");
            list.RemoveNodes();
            foreach (var row in (IList<object>)state["TextList"])
            {
                var fields = (IDictionary<string, object>)row;
                list.Add(new XElement("Single", new XAttribute("Type", "{53da1be7-ad25-47c3-b0e8-e26286dad2e0}"), new XAttribute("Method", "IArchivable"),
                    new XElement("Single", new XAttribute("Name", "TextID"), new XAttribute("Type", "string"), Convert.ToString(fields["TextID"])),
                    new XElement("Single", new XAttribute("Name", "TextDefault"), new XAttribute("Type", "string"), Convert.ToString(fields["TextDefault"])),
                    new XElement("List", new XAttribute("Name", "LanguageTexts"), new XAttribute("Type", "System.Collections.ArrayList"))));
            }
            return document.Root.ToString(SaveOptions.DisableFormatting);
        }

        // `project.export {path, guids}`: a snapshot holding these entries, the
        // IDE's objects as the export reads them.
        static IDictionary<string, object> SnapshotReply(IDictionary<string, object> args, params string[] entries)
        {
            var body = string.Concat(entries.Select(entry => XDocument.Parse(entry.TrimStart('\uFEFF'), LoadOptions.PreserveWhitespace).Root.ToString(SaveOptions.DisableFormatting)));
            File.WriteAllText(Convert.ToString(args["path"]), "<ExportFile><StructuredView Guid=\"{00000000-0000-0000-0000-000000000001}\"><Single xml:space=\"preserve\"><List2 Name=\"EntryList\">"
                + body + "</List2></Single></StructuredView></ExportFile>");
            return new Dictionary<string, object>();
        }

        static IDictionary<string, object> TextListTree()
        {
            var tree = Tree(new[] { "GlobalTextList" });
            var node = ((IList<IDictionary<string, object>>)tree["children"])[0];
            node["type"] = "63784cbb-9ba0-45e6-9d69-babf3f040511";
            return tree;
        }

        static IDictionary<string, object> TextListFields()
        {
            return new Dictionary<string, object>
            {
                { "Languages", new List<object>() },
                { "TextList", new List<object>
                    {
                        new Dictionary<string, object> { { "TextID", "212" }, { "TextDefault", "Start" } },
                        new Dictionary<string, object> { { "TextID", "705" }, { "TextDefault", "This is stabur Runtime under " } },
                        new Dictionary<string, object> { { "TextID", "978" }, { "TextDefault", "This is stabur Runtime under arm VM" } },
                        new Dictionary<string, object> { { "TextID", "" }, { "TextDefault", "" } },
                    } },
            };
        }

        static IDictionary<string, object> TextListReply(IDictionary<string, object> fields)
        {
            return new Dictionary<string, object> { { "name", "GlobalTextList" }, { "fields", fields } };
        }

        static string NativeValue(string content, string name)
        {
            return XDocument.Parse(content).Descendants().First(element => (string)element.Attribute("Name") == name).Value;
        }

        static IDictionary<string, object> NativeReply(string file, string guid)
        {
            var entry = XDocument.Load(file, LoadOptions.PreserveWhitespace);
            var objects = new List<object>
            {
                new Dictionary<string, object>
                {
                    { "guid", guid }, { "meta", AgentExportMember.Of(entry, "MetaObject") }, { "object", AgentExportMember.Of(entry, "Object") },
                },
            };
            return new Dictionary<string, object> { { "objects", objects } };
        }

        [Fact]
        public void ImportAppliesPragmaBuildFlagsAfterWritingText()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            File.WriteAllText(file, "(* cds-text-sync: ExcludeFromBuild *)\n" + File.ReadAllText(file).Replace("END_PROGRAM", "// flag and text edit\nEND_PROGRAM"));
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Kind == "PROGRAM");
            IDictionary<string, object> current = new Dictionary<string, object>();
            var calls = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.setfield") return new Dictionary<string, object>();
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", new[] { new Dictionary<string, object>(current) } },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.True(calls.IndexOf("objects.settext") < calls.IndexOf("objects.setfield"));
            Assert.Equal(new[] { "ExcludeFromBuild" }, ((IEnumerable<object>)result["settings"]).Cast<string>());
        }

        [Fact]
        public void ForceMakesAnObjectTheIdeDeletedAgainFromItsFile()
        {
            var view = ViewFolder.Of(_root);
            var diskItem = StViewReader.Read(view).Objects.First(item => item.Path.Last() == "F_Scale");
            var document = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            document.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "F_Scale")).Parent.Remove();
            var ideSnapshot = Path.Combine(_root, "ide-deleted.xml");
            document.Save(ideSnapshot);
            SyncBase.SaveStamp(StampPath(), _project, "session:changed", GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
            var creates = new List<string>();
            var current = new Dictionary<string, object>();
            var result = ImportCommand.Execute(ImportCall(new[] { "--force" }, (method, args) =>
            {
                if (method == "project.export") { File.Copy(ideSnapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(diskItem.Path.Take(diskItem.Path.Length - 1).ToArray());
                if (method == "objects.create") { creates.Add(Convert.ToString(args["name"])); return new Dictionary<string, object> { { "guid", "44444444-4444-4444-4444-444444444444" } }; }
                if (method == "objects.settext") { current.Clear(); foreach (var pair in args) current[pair.Key] = pair.Value; return new Dictionary<string, object>(); }
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new[] { new Dictionary<string, object>(current) } } };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.True(creates.SequenceEqual(new[] { "F_Scale" }), Json.Pretty(result));
        }

        [Fact]
        public void ForceKeepsTheIDEFileOnOverwrittenRefBeforeWritingDiskText()
        {
            var view = ViewFolder.Of(_root);
            var diskItem = StViewReader.Read(view).Objects.First(item => item.Path.Last() == "MAIN");
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = Regex.Replace(snapshot, @"PROGRAM MAIN\r?\n\(\* t76 timing probe \*\)", "PROGRAM MAIN\n(* IDE side edit *)");
            Assert.NotEqual(snapshot, changedSnapshot);
            SyncBase.SaveStamp(StampPath(), _project, "session:changed", GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
            IDictionary<string, object> written = null;
            var current = new Dictionary<string, object>();
            var result = ImportCommand.Execute(ImportCall(new[] { "--force" }, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(diskItem.Path);
                if (method == "objects.settext")
                {
                    GitRepository.Run(_root, "show-ref --verify --quiet refs/cts/overwritten");
                    written = new Dictionary<string, object>(args);
                    current.Clear(); foreach (var pair in args) current[pair.Key] = pair.Value;
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", new[] { new Dictionary<string, object>(current) } },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.True(written != null, Json.Pretty(result));
            var viewRelative = ExportCommand.Relative(_root, view);
            var kept = GitRun.In(_root, "show " + ProcessArgs.Quote("refs/cts/overwritten:" + viewRelative + "/" + diskItem.File));
            Assert.True(kept.ExitCode == 0, kept.Error + "\n" + GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/overwritten"));
            Assert.Contains("IDE side edit", kept.Output);
            Assert.DoesNotContain("IDE side edit", Convert.ToString(written["declaration"]));
            Assert.Equal(new[] { diskItem.Key }, ((IEnumerable<object>)result["overwritten_ide_changes"]).Cast<string>());
        }

        [Fact]
        public void MergesNonOverlappingTextEditsIntoTheIDEAndTheObjectFile()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            var original = File.ReadAllText(file);
            File.WriteAllText(file, original.Replace("END_PROGRAM", "// disk edit\nEND_PROGRAM"));
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := GVL_Bench.eMode; // IDE edit");
            Assert.Contains("eObservedMode := GVL_Bench.eMode;", original);
            IDictionary<string, object> current = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new[] { current } } };
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.NotNull(current);
            Assert.False(result.ContainsKey("partial"), Json.Pretty(result));
            Assert.Contains("IDE edit", Convert.ToString(current["implementation"]));
            Assert.Contains("disk edit", Convert.ToString(current["implementation"]));
            Assert.Equal(new[] { "MAIN" }, ((IEnumerable<object>)result["merged"]).Cast<string>());
            var both = original.Replace("END_PROGRAM", "// disk edit\nEND_PROGRAM").Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := GVL_Bench.eMode; // IDE edit");
            Assert.Equal(both, File.ReadAllText(file));
        }

        [Fact]
        public void LeavesAnOverlappingTextConflictUnwrittenAndPartial()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var diskText = File.ReadAllText(file);
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;");
            var writes = 0;
            IDictionary<string, object> current = null;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { writes++; current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new[] { current } } };
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Equal(0, writes);
            Assert.Equal(diskText, File.ReadAllText(file));
            Assert.True(Equals(result["partial"], true));
            Assert.Contains("MAIN", Convert.ToString(result["partial_reason"]));
            Assert.Single((System.Collections.IEnumerable)result["conflicts"]);
        }

        [Fact]
        public void ADryRunNamesTheConflictTheImportWouldLeave()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var changedSnapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml")).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;");
            var result = ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            var answer = ImportCommand.Build(result);
            Assert.Contains(answer.Pairs, pair => pair.Key == "conflicts" && Equals(pair.Value, 1));
            Assert.Contains(answer.Details, line => line.StartsWith("conflict MAIN ") && line.EndsWith("the same lines"));
            Assert.Contains("Keep the disk text: cts sync --take disk. Keep the IDE text: cts sync --take ide.", answer.Details);
        }

        [Fact]
        public void SyncWritesAnIdeBodyIntoAFileWrittenWithoutOne()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            var exported = File.ReadAllText(file);
            var marker = exported.IndexOf("// --- implementation ---", StringComparison.Ordinal);
            File.WriteAllText(file, exported.Substring(0, marker) + exported.Substring(exported.IndexOf("END_PROGRAM", marker, StringComparison.Ordinal)));
            SyncBase.Record(_root, ExportCommand.Relative(_root, view), new List<string>());
            SyncBase.SaveStamp(StampPath(), _project, _stamp, GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), snapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Equal(exported, File.ReadAllText(file));
            Assert.Contains(item.File, ((IEnumerable<object>)result["to_disk"]).Cast<string>());
        }

        [Fact]
        public void SyncWritesAnIdeOnlyTextEditToTheFileAndCarriesItsBase()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            var originalBase = GitRepository.Run(_root, "rev-parse refs/cts/base").Trim();
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := GVL_Bench.eMode; // IDE edit");
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Contains("IDE edit", File.ReadAllText(file));
            Assert.Contains(item.File, ((IEnumerable<object>)result["to_disk"]).Cast<string>());
            Assert.NotEqual(originalBase, GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
        }

        [Fact]
        public void CommitTakesTheDiskAsItIsAndWarnsOfTheIdeEdit()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := GVL_Bench.eMode; // IDE edit");
            var call = Call("commit", new[] { "-m", "first state", "--tag", "v1" }, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, "session:changed");
            var marks = _sources.Count;
            var result = call.Command.Execute(call);
            Assert.Equal(true, result["committed"]);
            Assert.Equal("main", result["branch"]);
            Assert.Equal("first state", GitRepository.Run(_root, "log -1 --format=%s").Trim());
            Assert.DoesNotContain("IDE edit", GitRepository.Run(_root, "show HEAD:" + ProcessArgs.Quote(Path.GetRelativePath(_root, view).Replace('\\', '/') + "/" + item.File)));
            Assert.Equal(GitRepository.Run(_root, "rev-parse HEAD").Trim(), GitRepository.Run(_root, "rev-parse v1^{commit}").Trim());
            Assert.Equal("", GitRepository.Run(_root, "status --porcelain"));
            Assert.Equal(marks, _sources.Count);
            var line = Verdict.Line(call.Command.Build(result).Status, "commit", call.Command.Build(result).Pairs);
            Assert.StartsWith("ok commit branch=main commit=", line);
            Assert.Contains(" ide_differs=1", line);
        }

        [Fact]
        public void CommitLeavesAProjectFileOutAndTagsHeadWhenNothingChanged()
        {
            Git("add -A");
            Git("commit -q -m start");
            File.WriteAllText(Path.Combine(_root, "copy.project"), "binary");
            var call = Call("commit", new[] { "-m", "again", "--tag", "v2" }, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(new[] { "Application" });
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, null);
            var result = call.Command.Execute(call);
            Assert.Equal(false, result["committed"]);
            Assert.Equal("start", GitRepository.Run(_root, "log -1 --format=%s").Trim());
            Assert.Equal(GitRepository.Run(_root, "rev-parse HEAD").Trim(), GitRepository.Run(_root, "rev-parse v2^{commit}").Trim());
            Assert.Equal("?? copy.project", GitRepository.Run(_root, "status --porcelain").Trim());
        }

        [Fact]
        public void CommitOffABranchIsRefused()
        {
            Git("add -A");
            Git("commit -q -m start");
            Git("switch -q --detach");
            var call = Call("commit", new[] { "-m", "x" }, (method, args) => throw new InvalidOperationException("unexpected agent call " + method), false, null, null);
            var failure = Assert.Throws<CliFailure>(() => call.Command.Execute(call));
            Assert.StartsWith("not on a branch", failure.Message, StringComparison.Ordinal);
        }

        [Fact]
        public void CheckoutCarriesChangedFileIntoTheIdeAndSaves()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            Git("add -A");
            Git("commit -q -m baseline");
            Git("switch -q -c feature");
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// branch edit\nEND_PROGRAM"));
            Git("add -A");
            Git("commit -q -m feature");
            Git("switch -q main");
            var current = new Dictionary<string, object> { { "declaration", Strip(item.Declaration) }, { "implementation", item.Implementation } };
            var writes = 0;
            var saves = 0;
            var call = Call("checkout", new[] { "feature" }, (method, args) =>
            {
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext")
                {
                    writes++;
                    foreach (var part in new[] { "declaration", "implementation" })
                    {
                        if (args.ContainsKey(part)) current[part] = args[part];
                    }
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts")
                {
                    var answer = new Dictionary<string, object> { { "guid", "11111111-1111-1111-1111-111111111111" } };
                    foreach (var pair in current) answer[pair.Key] = pair.Value;
                    return new Dictionary<string, object> { { "objects", new[] { answer } } };
                }
                if (method == "project.save")
                {
                    saves++;
                    return new Dictionary<string, object>();
                }
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, _stamp);
            var imported = call.Command.Execute(call);
            Assert.Equal("feature", GitRepository.Position(_root)["branch"]);
            Assert.True(writes > 0);
            Assert.Equal(1, saves);
            Assert.Equal(true, imported["saved"]);
        }

        [Fact]
        public void CheckoutImportRefusalRestoresStartingBranch()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            Git("add -A");
            Git("commit -q -m baseline");
            Git("switch -q -c feature");
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// denied branch edit\nEND_PROGRAM"));
            Git("add -A");
            Git("commit -q -m feature");
            Git("switch -q main");
            var call = Call("checkout", new[] { "feature" }, (method, args) =>
            {
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, new[] { "sync_import_text" }, _stamp);
            var failure = Assert.Throws<CliFailure>(() => call.Command.Execute(call));
            Assert.Contains("cannot carry feature into the IDE", failure.Message);
            Assert.Contains("back on main", failure.Message);
            Assert.Equal("main", GitRepository.Position(_root)["branch"]);
        }

        [Fact]
        public void CheckoutRefusesWhenTheIdeAndFolderDiffer()
        {
            Git("add -A");
            Git("commit -q -m baseline");
            Git("switch -q -c feature");
            Git("switch -q main");
            var call = Call("checkout", new[] { "feature" }, (method, args) =>
            {
                if (method == "project.export")
                {
                    var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
                    File.WriteAllText(Convert.ToString(args["path"]), snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := GVL_Bench.eMode; // IDE edit"));
                    return new Dictionary<string, object>();
                }
                if (method == "project.tree") return Tree(new[] { "Application" });
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, "session:ide-edit");
            var failure = Assert.Throws<CliFailure>(() => call.Command.Execute(call));
            Assert.Contains("differ", failure.Message);
            Assert.Equal("main", GitRepository.Position(_root)["branch"]);
        }

        [Fact]
        public void SyncWritesAnIdeOnlyNativeChangeAsTheExportWriterDoes()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var snapshotPath = Path.Combine(_root, "ide-native.xml");
            var snapshot = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var meta = snapshot.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "Task"));
            meta.Parent.Descendants().First(element => (string)element.Attribute("Name") == "Priority").Value = "2";
            snapshot.Save(snapshotPath);
            var expected = ViewExport.NativeBytes(meta.Parent, false);
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(snapshotPath, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(key.Split('/'));
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Equal(expected, File.ReadAllBytes(file));
            Assert.Contains(ExportCommand.Relative(view, file), ((IEnumerable<object>)result["to_disk"]).Cast<string>());
        }

        // A whole folder the IDE added (a new device's) is created on disk.
        [Theory]
        [InlineData("sync", true, false)]
        [InlineData("sync", true, true)]
        [InlineData("import", false, false)]
        public void ANativeObjectTheIdeAddedIsWrittenBySyncAndLeftByImport(string command, bool written, bool newFolder)
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "Task.xml", SearchOption.AllDirectories).Single();
            var key = ExportCommand.Relative(view, Path.GetDirectoryName(file)) + "/Task";
            var viewRelative = ExportCommand.Relative(_root, view);
            var basePath = (viewRelative == "." ? "" : viewRelative.TrimEnd('/') + "/") + ExportCommand.Relative(view, file);
            var expected = File.ReadAllBytes(file);
            if (newFolder) Directory.Delete(Path.GetDirectoryName(file), true);
            else File.Delete(file);
            var gone = newFolder ? basePath.Substring(0, basePath.LastIndexOf('/') + 1) : basePath;
            var tracked = GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/base").Split('\n')
                .Select(path => path.Trim()).Where(path => path.Length > 0 && !(newFolder ? path.StartsWith(gone, StringComparison.Ordinal) : path == basePath)).ToList();
            SyncBase.Record(_root, viewRelative, tracked);
            var result = ImportCommand.Execute(Call(command, null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(key.Split('/'));
                throw new InvalidOperationException("unexpected agent call " + method);
            }, false, null, "session:changed"));
            Assert.False(result.ContainsKey("refused"), Json.Pretty(result));
            Assert.Equal(written, File.Exists(file));
            if (written) Assert.Equal(expected, File.ReadAllBytes(file));
            if (newFolder) Assert.True(File.Exists(Path.Combine(Path.GetDirectoryName(file), ".cds-object.xml")), "the container's own file");
        }

        [Theory]
        [InlineData("GVL_Fixture", "PLC_Stabur/Plc Logic/Application/GVL_Fixture.st")]
        [InlineData("Visualization", "PLC_Stabur/Plc Logic/Application/Visualization.xml")]
        [InlineData("GlobalTextList", "POUs/GlobalTextList.xml", "POUs/GlobalTextList.csv")]
        public void SyncRemovesTheFilesOfAnObjectTheIdeDeleted(string name, params string[] files)
        {
            var view = ViewFolder.Of(_root);
            Assert.All(files, file => Assert.True(File.Exists(Path.Combine(view, file)), file));
            var result = ImportCommand.Execute(SyncCall(null, IdeWithout(name), ideStamp: "session:changed"));
            Assert.All(files, file => Assert.False(File.Exists(Path.Combine(view, file)), file));
            Assert.Contains(name, ((IEnumerable<object>)result["ide_removed"]).Cast<string>());
            var baseFiles = GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/base");
            Assert.All(files, file => Assert.DoesNotContain(file, baseFiles));
        }

        [Fact]
        public void SyncRemovesAFolderTheIdeDeletedWithItsFiles()
        {
            var view = ViewFolder.Of(_root);
            var appContainer = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => path.Replace('\\', '/').EndsWith("/Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
            var folder = Path.Combine(Path.GetDirectoryName(appContainer), "Gone");
            Directory.CreateDirectory(folder);
            File.WriteAllText(Path.Combine(folder, ".cds-object.xml"), File.ReadAllText(appContainer)
                .Replace("32d92914-bcb4-4227-b529-32fd90910eca", "33333333-3333-3333-3333-333333333333")
                .Replace("<Single Name=\"Name\" Type=\"string\">Application</Single>", "<Single Name=\"Name\" Type=\"string\">Gone</Single>")
                .Replace("639b491f-5557-464c-af91-1471bac9f549", ObjectKinds.FolderType));
            File.WriteAllText(Path.Combine(folder, "GVL_Gone.st"), "VAR_GLOBAL\nEND_VAR\n");
            SyncBase.Record(_root, ExportCommand.Relative(_root, view), new List<string>());
            SyncBase.SaveStamp(StampPath(), _project, _stamp, GitRepository.Run(_root, "rev-parse refs/cts/base").Trim());
            var snapshot = Path.Combine(Fixture, "snapshot.xml");
            ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(snapshot, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(new[] { "MAIN" });
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.False(Directory.Exists(folder));
            Assert.DoesNotContain("/Gone/", GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/base"));
        }

        [Fact]
        public void SyncRemovesTheXmlBesideATextObjectOnceTheIdeNeedsItNoMore()
        {
            var view = ViewFolder.Of(_root);
            var withSettings = SnapshotWithAttributeCount("2");
            File.Delete(StampPath());
            Export((method, args) => { File.Copy(withSettings, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); });
            var beside = Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application", "GVL_Fixture.xml");
            Assert.True(File.Exists(beside));
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(new[] { "MAIN" });
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.False(File.Exists(beside));
            Assert.True(File.Exists(Path.ChangeExtension(beside, ".st")));
            Assert.False(result.ContainsKey("ide_removed"));
        }

        [Fact]
        public void SyncWritesTheXmlBesideATextObjectAsExportDoes()
        {
            var view = ViewFolder.Of(_root);
            var before = SnapshotWithAttributeCount("2");
            var after = SnapshotWithAttributeCount("3");
            File.Delete(StampPath());
            Export((method, args) => { File.Copy(before, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); });
            var beside = Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application", "GVL_Fixture.xml");
            var exported = File.ReadAllText(beside);
            ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(after, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(new[] { "MAIN" });
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Equal(exported.Replace(">2</Single>", ">3</Single>"), File.ReadAllText(beside));
        }

        // The fixture's snapshot with GVL_Fixture's dymmattributecount at *count*, a setting only an .xml beside its .st holds.
        string SnapshotWithAttributeCount(string count)
        {
            var snapshot = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            snapshot.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "GVL_Fixture")).Parent
                .Elements().First(element => (string)element.Attribute("Name") == "Object").Add(new XElement(snapshot.Root.Name.Namespace + "Single",
                    new XAttribute("Name", "dymmattributecount"), new XAttribute("Type", "int"), count));
            var path = Path.Combine(_root, "attribute-count-" + count + ".xml");
            snapshot.Save(path);
            return path;
        }

        [Fact]
        public void SyncTakesAMethodTheIdeDeletedOutOfItsPouFile()
        {
            var file = Path.Combine(ViewFolder.Of(_root), "PLC_Stabur", "Plc Logic", "Application", "FB_Logger.st");
            Assert.Contains("METHOD LogADDLong", File.ReadAllText(file));
            var result = ImportCommand.Execute(SyncCall(null, IdeWithout("LogADDLong"), ideStamp: "session:changed"));
            Assert.DoesNotContain("METHOD LogADDLong", File.ReadAllText(file));
            Assert.Contains("FUNCTION_BLOCK FB_Logger", File.ReadAllText(file));
            Assert.Contains("LogADDLong", ((IEnumerable<object>)result["ide_removed"]).Cast<string>());
        }

        // An IDE that has the fixture's objects but *name*.
        Func<string, IDictionary<string, object>, IDictionary<string, object>> IdeWithout(string name)
        {
            var snapshot = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            snapshot.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == name)).Parent.Remove();
            var snapshotPath = Path.Combine(_root, "ide-without.xml");
            snapshot.Save(snapshotPath);
            return (method, args) =>
            {
                if (method == "project.export") { File.Copy(snapshotPath, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(new[] { "MAIN" });
                throw new InvalidOperationException("unexpected agent call " + method);
            };
        }

        [Fact]
        public void SyncWritesAnIdeNewGlobalVariableListToItsExportPath()
        {
            var view = ViewFolder.Of(_root);
            var original = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var sourceMeta = original.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "GVL_Bench"));
            var clone = new XElement(sourceMeta.Parent);
            clone.Descendants().First(element => (string)element.Attribute("Name") == "Guid").Value = "22222222-2222-2222-2222-222222222222";
            clone.Descendants().First(element => (string)element.Attribute("Name") == "Name").Value = "GVL_OnlyIde";
            sourceMeta.Parent.Parent.Add(clone);
            var snapshotPath = Path.Combine(_root, "ide-new-gvl.xml");
            original.Save(snapshotPath);
            var relative = "PLC_Stabur/Plc Logic/Application/GVL_OnlyIde.st";
            var tree = Tree(relative.Substring(0, relative.Length - 3).Split('/'));
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(snapshotPath, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return tree;
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.True(File.Exists(Path.Combine(view, relative.Replace('/', Path.DirectorySeparatorChar))));
            Assert.Contains("PLC_Stabur/Plc Logic/Application/GVL_OnlyIde", ((IEnumerable<object>)result["to_disk"]).Cast<string>());
        }

        [Fact]
        public void SyncWritesAnIdeNewMethodIntoItsPouFile()
        {
            var view = ViewFolder.Of(_root);
            var existing = Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application", "FB_Logger.st");
            var originalBytes = File.ReadAllBytes(existing);
            var snapshot = XDocument.Load(Path.Combine(Fixture, "snapshot.xml"));
            var sourceMeta = snapshot.Descendants().First(element => (string)element.Attribute("Name") == "MetaObject"
                && element.Elements().Any(child => (string)child.Attribute("Name") == "Name" && child.Value == "LogADDLong"));
            var clone = new XElement(sourceMeta.Parent);
            clone.Descendants().First(element => (string)element.Attribute("Name") == "Guid").Value = "33333333-3333-3333-3333-333333333333";
            clone.Descendants().First(element => (string)element.Attribute("Name") == "Name").Value = "LogIDEOnly";
            foreach (var text in clone.Descendants().Where(element => (string)element.Attribute("Name") == "TextBlobForSerialisation"))
                text.Value = text.Value.Replace("LogADDLong", "LogIDEOnly");
            sourceMeta.Parent.Parent.Add(clone);
            var snapshotPath = Path.Combine(_root, "ide-new-method.xml");
            snapshot.Save(snapshotPath);
            var relative = "PLC_Stabur/Plc Logic/Application/FB_Logger.st";
            var methodPath = "PLC_Stabur/Plc Logic/Application/FB_Logger/LogIDEOnly";
            var result = ImportCommand.Execute(SyncCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(snapshotPath, Convert.ToString(args["path"]), true); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(methodPath.Split('/'));
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            var file = Path.Combine(view, relative.Replace('/', Path.DirectorySeparatorChar));
            Assert.Contains("METHOD LogIDEOnly", File.ReadAllText(file));
            Assert.Equal(originalBytes, File.ReadAllBytes(file).Take(originalBytes.Length));
            // Laid out as the export joins blocks: one blank line before it, a newline after it.
            var added = File.ReadAllText(file).Substring(System.Text.Encoding.UTF8.GetString(originalBytes).Length);
            Assert.StartsWith("\nMETHOD LogIDEOnly", added);
            Assert.EndsWith("END_METHOD\n", added);
            Assert.Contains(methodPath, ((IEnumerable<object>)result["to_disk"]).Cast<string>());
        }

        [Fact]
        public void SyncTakeIdeWritesTheIdeSideOfAnOverlapToDisk()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;");
            var result = ImportCommand.Execute(SyncCall(new[] { "--take", "ide" }, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("sync --take ide must not write to the IDE");
            }, ideStamp: "session:changed"));
            Assert.Contains("eObservedMode := IDE;", File.ReadAllText(file));
            Assert.Contains(item.File, ((IEnumerable<object>)result["to_disk"]).Cast<string>());
            Assert.False(result.ContainsKey("partial"));
        }

        [Fact]
        public void SyncTakeDiskKeepsDiskTextAndPreservesTheIdeSide()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var diskText = File.ReadAllText(file);
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;")
                .Replace("F_Scale := x * k;", "F_Scale := x * k; // IDE only");
            var scale = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "F_Scale");
            IDictionary<string, object> current = null;
            var result = ImportCommand.Execute(SyncCall(new[] { "--take", "disk" }, (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new[] { current } } };
                throw new InvalidOperationException("unexpected agent call " + method);
            }, ideStamp: "session:changed"));
            Assert.Equal(diskText, File.ReadAllText(file));
            Assert.DoesNotContain("eObservedMode := IDE;", Convert.ToString(current["implementation"]));
            var relative = ExportCommand.Relative(_root, view);
            var preserved = GitRun.In(_root, "show " + ProcessArgs.Quote("refs/cts/overwritten:" + relative + "/" + item.File));
            Assert.Equal(0, preserved.ExitCode);
            Assert.Contains("eObservedMode := IDE;", preserved.Output);
            Assert.False(Equals(result.ContainsKey("partial") ? result["partial"] : false, true));
            // --take decides only the conflict: an edit only the IDE made still reaches its file.
            Assert.Contains("F_Scale := x * k; // IDE only", File.ReadAllText(Path.Combine(view, scale.File.Replace('/', Path.DirectorySeparatorChar))));
            Assert.Equal(new[] { scale.File }, ((IEnumerable<object>)result["to_disk"]).Cast<string>());
            Assert.Single((System.Collections.IEnumerable)result["overwritten_ide_changes"]);
        }

        // What is saved on the right of the side-by-side view: an edited
        // text, the carried side as it opened (saved as it was), or nothing.
        [Theory]
        [InlineData("import", "edited", "eObservedMode := Resolved;")]
        [InlineData("import", "as-is", "eObservedMode := Disk;")]
        [InlineData("import", "unsaved", null)]
        [InlineData("export", "edited", "eObservedMode := Resolved;")]
        [InlineData("export", "as-is", "eObservedMode := IDE;")]
        [InlineData("export", "unsaved", null)]
        public void ToolTakesWhatIsSavedOnTheRight(string command, string save, string expected)
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var snapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml"));
            var changedSnapshot = snapshot.Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;");
            Git("config merge.tool winmerge");
            Git("config mergetool.winmerge.path fake-winmerge");
            IDictionary<string, object> current = null;
            IList<string> shown = null;
            var originalRunner = ConflictTool.StartAndWait;
            try
            {
                ConflictTool.StartAndWait = arguments =>
                {
                    shown = arguments;
                    var right = arguments.Last();
                    if (save == "edited") File.WriteAllText(right, File.ReadAllText(right).Replace("eObservedMode := " + (command == "import" ? "Disk" : "IDE") + ";", "eObservedMode := Resolved;"));
                    if (save == "as-is") File.WriteAllText(right, File.ReadAllText(right));
                };
                var call = Call(command, new[] { "--tool" }, (method, args) =>
                {
                    if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object> { { "objects", 1 } }; }
                    if (method == "project.tree") return Tree(item.Path);
                    if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                    if (method == "objects.texts") return new Dictionary<string, object> { { "objects", new[] { current } } };
                    throw new InvalidOperationException("unexpected agent call " + method);
                }, false, null, "session:changed");
                var result = command == "import" ? ImportCommand.Execute(call) : ExportCommand.Execute(call);
                Assert.True(shown != null, Json.Serialize(result));
                Assert.Equal(command == "import" ? "IDE (its edit)" : "Disk (its edit)", shown[shown.IndexOf("/dl") + 1]);
                if (expected == null)
                {
                    Assert.Null(current);
                    Assert.Contains("eObservedMode := Disk;", File.ReadAllText(file));
                    if (command == "import") Assert.True(result.ContainsKey("partial"));
                    else Assert.Contains(item.File, (IEnumerable<string>)result["pending_import"]);
                    return;
                }
                Assert.Contains(expected, File.ReadAllText(file));
                Assert.Contains(expected, Convert.ToString(current["implementation"]));
                Assert.Equal(new[] { "MAIN" }, ((IEnumerable<object>)result["merged"]).Cast<string>());
                if (command == "export") Assert.Empty((IEnumerable<string>)result["pending_import"]);
                else Assert.False(result.ContainsKey("partial"));
            }
            finally { ConflictTool.StartAndWait = originalRunner; }
        }

        // An export that kept a file the IDE changed too leaves the conflict
        // to the next import: it does not record the IDE as the base.
        [Fact]
        public void AnImportAfterAnExportThatKeptAFileStillSeesTheIdeEdit()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == "MAIN");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            File.WriteAllText(file, File.ReadAllText(file).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := Disk;"));
            var changedSnapshot = File.ReadAllText(Path.Combine(Fixture, "snapshot.xml")).Replace("eObservedMode := GVL_Bench.eMode;", "eObservedMode := IDE;");
            Func<string, IDictionary<string, object>, IDictionary<string, object>> fake = (method, args) =>
            {
                if (method == "project.export") { File.WriteAllText(Convert.ToString(args["path"]), changedSnapshot); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            };
            ExportCommand.Execute(Call("export", null, fake, false, null, "session:changed"));
            var plan = ImportCommand.Execute(Call("import", new[] { "--dry-run" }, fake, false, null, "session:changed"));
            var conflicts = ((System.Collections.IEnumerable)plan["conflicts"]).Cast<IDictionary<string, object>>();
            Assert.Equal("MAIN", Assert.Single(conflicts)["name"]);
        }

        [Fact]
        public void RenameOfAnObjectInItsOwnFilePrecedesItsTextWrite()
        {
            var view = ViewFolder.Of(_root);
            var before = StViewReader.Read(view);
            var itemBefore = before.Objects.First(candidate => candidate.Kind == "PROGRAM");
            var file = Path.Combine(view, itemBefore.File.Replace('/', Path.DirectorySeparatorChar));
            var oldName = itemBefore.Path.Last();
            var newName = oldName + "_Renamed";
            var text = File.ReadAllText(file);
            var pattern = @"(?im)^PROGRAM\s+" + Regex.Escape(oldName) + @"\b";
            Assert.True(Regex.IsMatch(text, pattern), file);
            File.WriteAllText(file, Regex.Replace(text, pattern, "PROGRAM " + newName));
            var renamedFile = Path.Combine(Path.GetDirectoryName(file), Path.GetFileNameWithoutExtension(file).Replace(oldName, newName) + Path.GetExtension(file));
            File.Move(file, renamedFile);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == newName);
            var calls = new List<string>();
            IDictionary<string, object> current = new Dictionary<string, object>
            {
                { "declaration", Strip(item.Declaration) }, { "implementation", item.Implementation },
            };
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(item.Path.Take(item.Path.Length - 1).Concat(new[] { oldName }).ToArray());
                if (method == "objects.rename") return new Dictionary<string, object>();
                if (method == "objects.settext")
                {
                    foreach (var part in new[] { "declaration", "implementation" }) if (args.ContainsKey(part)) current[part] = args[part];
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", new[] { new Dictionary<string, object>(current) { { "guid", "11111111-1111-1111-1111-111111111111" } } } },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Contains("objects.rename", calls);
            Assert.True(calls.IndexOf("objects.rename") < calls.IndexOf("objects.settext"));
            Assert.Equal(new[] { item.Key }, ((IEnumerable<object>)result["renamed_objects"]).Cast<string>());
        }

        [Fact]
        public void A_file_moved_into_a_new_folder_moves_its_object_there_without_a_delete()
        {
            var view = ViewFolder.Of(_root);
            var item = StViewReader.Read(view).Objects.First(candidate => candidate.Kind == "PROGRAM");
            var file = Path.Combine(view, item.File.Replace('/', Path.DirectorySeparatorChar));
            var folder = Path.Combine(Path.GetDirectoryName(file), "Moved");
            Directory.CreateDirectory(folder);
            File.Move(file, Path.Combine(folder, Path.GetFileName(file)));
            var moved = StViewReader.Read(view).Objects.First(candidate => candidate.Path.Last() == item.Path.Last());
            var calls = new List<string>();
            IDictionary<string, object> current = new Dictionary<string, object>
            {
                { "declaration", Strip(item.Declaration) }, { "implementation", item.Implementation },
            };
            IDictionary<string, object> Fake(string method, IDictionary<string, object> args)
            {
                calls.Add(method);
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.create")
                {
                    Assert.Equal("folder", args["kind"]);
                    return new Dictionary<string, object> { { "guid", "22222222-2222-2222-2222-222222222222" } };
                }
                if (method == "objects.move")
                {
                    Assert.Equal("11111111-1111-1111-1111-111111111111", args["guid"]);
                    Assert.Equal("22222222-2222-2222-2222-222222222222", args["parent_guid"]);
                    return new Dictionary<string, object>();
                }
                if (method == "objects.settext")
                {
                    foreach (var part in new[] { "declaration", "implementation" }) if (args.ContainsKey(part)) current[part] = args[part];
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", new[] { new Dictionary<string, object>(current) { { "guid", "11111111-1111-1111-1111-111111111111" } } } },
                };
                if (method == "project.export") return SnapshotReply(args);
                throw new InvalidOperationException("unexpected agent call " + method);
            }
            var plan = ImportCommand.Build(ImportCommand.Execute(ImportCall(new[] { "--dry-run" }, Fake, deny: new[] { "delete_pou" })));
            Assert.Equal(new[] { "renamed " + item.File + " -> " + moved.File + ": the object keeps its GUID" }, plan.Details);
            Assert.Contains(new KeyValuePair<string, object>("added", 0), plan.Pairs);
            Assert.Contains(new KeyValuePair<string, object>("renamed", 1), plan.Pairs);
            Assert.DoesNotContain("objects.move", calls);
            var result = ImportCommand.Execute(ImportCall(null, Fake, deny: new[] { "delete_pou" }));
            Assert.Contains("renamed " + moved.Key, ImportCommand.Build(result).Details);
            Assert.DoesNotContain("objects.delete", calls);
            Assert.DoesNotContain("objects.rename", calls);
            Assert.True(calls.IndexOf("objects.create") < calls.IndexOf("objects.move"), string.Join(",", calls));
            Assert.Equal(new[] { moved.Key }, ((IEnumerable<object>)result["renamed_objects"]).Cast<string>());
        }

        // A renamed folder brings its old file along: the old folder's guid
        // and name, rewritten as the folder the import made.
        [Theory]
        [InlineData(false)]
        [InlineData(true)]
        public void CreatesAnUnmarkedNewFolderBeforeItsOneMemberPerFileGVL(bool renamedFolderFile)
        {
            var view = ViewFolder.Of(_root);
            var appContainer = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => path.Replace('\\', '/').EndsWith("/Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
            var parent = Path.GetDirectoryName(appContainer);
            var newFolder = Path.Combine(parent, "NewFolder");
            Directory.CreateDirectory(newFolder);
            if (renamedFolderFile) File.WriteAllText(Path.Combine(newFolder, ".cds-object.xml"), File.ReadAllText(appContainer)
                .Replace("<Single Name=\"Name\" Type=\"string\">Application</Single>", "<Single Name=\"Name\" Type=\"string\">OldFolder</Single>")
                .Replace("639b491f-5557-464c-af91-1471bac9f549", ObjectKinds.FolderType));
            File.WriteAllText(Path.Combine(newFolder, "GVL_New.st"), "VAR_GLOBAL\n    xNew : BOOL;\nEND_VAR\n");
            var parentKey = Path.GetRelativePath(view, parent).Replace('\\', '/');
            var folderEntry = File.ReadAllText(appContainer)
                .Replace("32d92914-bcb4-4227-b529-32fd90910eca", "33333333-3333-3333-3333-333333333333")
                .Replace("<Single Name=\"Name\" Type=\"string\">Application</Single>", "<Single Name=\"Name\" Type=\"string\">NewFolder</Single>")
                .Replace("639b491f-5557-464c-af91-1471bac9f549", ObjectKinds.FolderType);
            var calls = new List<string>();
            var currentGuid = 0;
            var current = new Dictionary<string, IDictionary<string, object>>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                calls.Add(method + ":" + (args.ContainsKey("kind") ? args["kind"] : ""));
                if (method == "project.tree") return Tree(parentKey.Split('/'));
                if (method == "objects.create")
                {
                    if (Equals(args["kind"], "folder")) return new Dictionary<string, object> { { "guid", "33333333-3333-3333-3333-333333333333" } };
                    currentGuid++;
                    return new Dictionary<string, object> { { "guid", currentGuid.ToString() } };
                }
                if (method == "objects.settext")
                {
                    current[Convert.ToString(args["guid"])] = new Dictionary<string, object>(args);
                    return new Dictionary<string, object>();
                }
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", current.Select(pair => { var item = new Dictionary<string, object>(pair.Value); item["guid"] = pair.Key; return (IDictionary<string, object>)item; }).ToList() },
                };
                if (method == "project.export")
                {
                    Assert.Equal(new[] { "33333333-3333-3333-3333-333333333333" }, ((IEnumerable<string>)args["guids"]).ToArray());
                    return SnapshotReply(args, folderEntry);
                }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var createFolder = calls.IndexOf("objects.create:folder");
            var createGvl = calls.IndexOf("objects.create:gvl");
            Assert.True(createFolder >= 0 && createGvl > createFolder, string.Join(",", calls));
            Assert.Equal(new[] { "NewFolder" }, (IList<string>)result["created_native_objects"]);
            // The new folder's file is on disk as export writes it: the next export adds nothing.
            var folderFile = Path.Combine(newFolder, ".cds-object.xml");
            Assert.Equal(Encoding.UTF8.GetString(ViewExport.NativeBytes(XElement.Parse(folderEntry, LoadOptions.PreserveWhitespace), false)), File.ReadAllText(folderFile));
            Assert.Contains(parentKey + "/NewFolder/.cds-object.xml", (IList<string>)result["to_disk"]);
        }

        [Fact]
        public void CreatesAFileAtTheViewTopAtTheProjectRoot()
        {
            var view = ViewFolder.Of(_root);
            File.WriteAllText(Path.Combine(view, "F_Shared.st"), "FUNCTION F_Shared : INT\nVAR_INPUT\n\tx : INT;\nEND_VAR\n// --- implementation ---\nF_Shared := x;\nEND_FUNCTION\n");
            var anyPath = StViewReader.Read(view).Objects.First(item => item.Path.Last() == "FB_Valve").Path;
            var creates = new List<IDictionary<string, object>>();
            var current = new Dictionary<string, IDictionary<string, object>>();
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(anyPath);
                if (method == "objects.create")
                {
                    creates.Add(new Dictionary<string, object>(args));
                    current["root-guid"] = new Dictionary<string, object>(args);
                    return new Dictionary<string, object> { { "guid", "root-guid" } };
                }
                if (method == "objects.settext") return new Dictionary<string, object>();
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", current.Select(pair => { var item = new Dictionary<string, object>(pair.Value); item["guid"] = pair.Key; return (IDictionary<string, object>)item; }).ToList() },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var create = creates.Single();
            Assert.Equal("F_Shared", create["name"]);
            Assert.Equal(true, create["root"]);
            Assert.False(create.ContainsKey("parent_guid"));
        }

        [Fact]
        public void CreatesANewInterfaceAndItsMethodWithoutAFolderOfTheSameName()
        {
            var view = ViewFolder.Of(_root);
            var neighbour = Directory.GetFiles(view, "FB_Valve.st", SearchOption.AllDirectories).Single();
            var folder = Path.GetDirectoryName(neighbour);
            File.WriteAllText(Path.Combine(folder, "I_New.st"), "INTERFACE I_New\nEND_INTERFACE\n");
            File.WriteAllText(Path.Combine(folder, "I_New.M_New.st"), "METHOD M_New : BOOL\nVAR_INPUT\n\tx : BOOL;\nEND_VAR\n");
            var parentPath = StViewReader.Read(view).Objects.First(item => item.Path.Last() == "FB_Valve").Path;
            var creates = new List<string>();
            var current = new Dictionary<string, IDictionary<string, object>>();
            ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(parentPath);
                if (method == "objects.create")
                {
                    creates.Add(args["kind"] + ":" + args["name"]);
                    var guid = "created-" + creates.Count;
                    current[guid] = new Dictionary<string, object>(args);
                    return new Dictionary<string, object> { { "guid", guid } };
                }
                if (method == "objects.settext") return new Dictionary<string, object>();
                if (method == "objects.texts") return new Dictionary<string, object>
                {
                    { "objects", current.Select(pair => { var item = new Dictionary<string, object>(pair.Value); item["guid"] = pair.Key; return (IDictionary<string, object>)item; }).ToList() },
                };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(new[] { "interface:I_New", "method:M_New" }, creates);
        }

        [Fact]
        public void CreatesPropertyAccessorsInsideThePropertyCreate()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "FB_Valve.st", SearchOption.AllDirectories).Single();
            File.AppendAllText(file, "\nACTION A_LiveTmp:\nxOpen := FALSE;\nEND_ACTION\n\nPROPERTY P_LiveTmp : BOOL\nGET\n// --- implementation ---\nP_LiveTmp := xOpen;\nEND_GET\nSET\n// --- implementation ---\nxOpen := P_LiveTmp;\nEND_SET\nEND_PROPERTY\n");
            var current = new Dictionary<string, IDictionary<string, object>>();
            var creates = new List<IDictionary<string, object>>();
            var next = 0;
            var parent = StViewReader.Read(view).Objects.First(item => item.Path.Last() == "FB_Valve");
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return Tree(parent.Path);
                if (method == "objects.create")
                {
                    creates.Add(new Dictionary<string, object>(args));
                    var guid = "created-" + (++next);
                    if (Equals(args["kind"], "property")) return new Dictionary<string, object>
                    {
                        { "guid", guid }, { "accessors", new List<object>
                            { new Dictionary<string, object> { { "name", "Get" }, { "guid", "get-guid" } }, new Dictionary<string, object> { { "name", "Set" }, { "guid", "set-guid" } } } },
                    };
                    return new Dictionary<string, object> { { "guid", guid } };
                }
                if (method == "objects.settext") { current[Convert.ToString(args["guid"])] = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") return new Dictionary<string, object> { { "objects", current.Select(pair => { var row = new Dictionary<string, object>(pair.Value); row["guid"] = pair.Key; return (IDictionary<string, object>)row; }).ToList() } };
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(new[] { "action", "property" }, creates.Select(args => Convert.ToString(args["kind"])));
            var propertyCreate = creates.Single(args => Equals(args["kind"], "property"));
            Assert.Equal(new Dictionary<string, string> { { "Get", "P_LiveTmp := xOpen;" }, { "Set", "xOpen := P_LiveTmp;" } },
                (IDictionary<string, string>)propertyCreate["accessors"]);
            var createdNames = ((IEnumerable<object>)result["created_text_objects"]).Cast<string>().ToList();
            Assert.Contains("Get", createdNames);
            Assert.Contains("Set", createdNames);
            Assert.Equal(4, current.Count);
        }

        [Fact]
        public void ImportWithoutBaseWritesDiskEditsAndDoesNotDeleteMissingFiles()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            var item = StViewReader.Read(view).Objects.First(candidate => Path.Combine(view, candidate.File.Replace('/', Path.DirectorySeparatorChar)) == file);
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// no base edit\nEND_PROGRAM"));
            var missing = Directory.GetFiles(view, "GVL_Bench.st", SearchOption.AllDirectories).Single();
            File.Delete(missing);
            GitRepository.Run(_root, "update-ref -d refs/cts/base");
            var current = new Dictionary<string, object>();
            var deleted = false;
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"])); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") { var read = new Dictionary<string, object>(current); return new Dictionary<string, object> { { "objects", new[] { read } } }; }
                if (method == "objects.delete") { deleted = true; return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.False(deleted);
            Assert.Single((IList<string>)result["updated_text_objects"]);
            Assert.Contains("// no base edit", Convert.ToString(current["implementation"]));
            Assert.NotNull(result["base"]);
            var answer = ImportCommand.Build(result);
            Assert.Contains(answer.Pairs, pair => pair.Key == "native" && Equals(pair.Value, 0));
            Assert.DoesNotContain(answer.Details, detail => detail.StartsWith("deleted ", StringComparison.Ordinal));
            var plan = ComparePlanner.Plan(ImportCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"])); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            var objects = (IDictionary<string, object>)plan["objects"];
            var ideChanged = ((System.Collections.IEnumerable)objects["ide_changed"]).Cast<IDictionary<string, object>>();
            Assert.Contains(ideChanged, record => Equals(record["path"], Path.GetRelativePath(view, missing).Replace('\\', '/'))
                && Equals(record["reason"], "not in the view; cts sync writes it to disk"));
        }

        [Fact]
        public void ImportFromAnotherProjectFilesSyncWritesTheDiskTextAndTakesTheFolderOver()
        {
            var view = ViewFolder.Of(_root);
            var file = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).First(path => File.ReadAllText(path).Contains("END_PROGRAM"));
            var item = StViewReader.Read(view).Objects.First(candidate => Path.Combine(view, candidate.File.Replace('/', Path.DirectorySeparatorChar)) == file);
            File.WriteAllText(file, File.ReadAllText(file).Replace("END_PROGRAM", "// the branch's edit\nEND_PROGRAM"));
            SyncBase.SaveProject(_root, Path.Combine(Path.GetDirectoryName(_project), "older copy.project"));
            var current = new Dictionary<string, object>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.export") { File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"])); return new Dictionary<string, object>(); }
                if (method == "project.tree") return Tree(item.Path);
                if (method == "objects.settext") { current = new Dictionary<string, object>(args); return new Dictionary<string, object>(); }
                if (method == "objects.texts") { var read = new Dictionary<string, object>(current); return new Dictionary<string, object> { { "objects", new[] { read } } }; }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Single((IList<string>)result["updated_text_objects"]);
            Assert.Contains("// the branch's edit", Convert.ToString(current["implementation"]));
            Assert.Null(SyncBase.OtherProject(_root, _project));
            Git("add -A");
            Assert.Equal("", GitRepository.Run(_root, "diff --cached --name-only refs/cts/base -- project-view").Trim());
        }

        [Theory]
        [InlineData(true)]
        [InlineData(false)]
        public void ExportOfAnotherProjectFileWritesWhatABranchSwitchChangedAndKeepsUncommittedEdits(bool anotherProject)
        {
            var view = ViewFolder.Of(_root);
            var files = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).OrderBy(path => path, StringComparer.Ordinal).ToList();
            var switched = files[0];
            var edited = files[1];
            var exported = File.ReadAllText(switched);
            Git("add -A");
            Git("commit -qm export");
            File.WriteAllText(switched, exported + "// on the other branch\n");
            Git("commit -qam switch");
            File.WriteAllText(edited, File.ReadAllText(edited) + "// not committed\n");
            if (anotherProject) SyncBase.SaveProject(_root, Path.Combine(Path.GetDirectoryName(_project), "older copy.project"));
            Export((method, args) =>
            {
                File.Copy(Path.Combine(Fixture, "snapshot.xml"), Convert.ToString(args["path"]));
                return new Dictionary<string, object>();
            });
            Assert.Equal(anotherProject ? exported : exported + "// on the other branch\n", File.ReadAllText(switched));
            Assert.EndsWith("// not committed\n", File.ReadAllText(edited), StringComparison.Ordinal);
        }

        static string Strip(string text)
        {
            var lines = (text ?? "").Replace("\r\n", "\n").Split('\n').ToList();
            if (lines.Count > 0 && lines[0].TrimStart().StartsWith("(* cds-text-sync:", StringComparison.OrdinalIgnoreCase)) lines.RemoveAt(0);
            return string.Join("\n", lines).Trim();
        }

        [Fact]
        public void DeletesTheFolderEmptiedByItsLastObjectDeletion()
        {
            var view = ViewFolder.Of(_root);
            var appContainer = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => path.Replace('\\', '/').EndsWith("/Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
            var parent = Path.GetDirectoryName(appContainer);
            var newFolder = Path.Combine(parent, "EmptyAfterImport");
            Directory.CreateDirectory(newFolder);
            File.Copy(appContainer, Path.Combine(newFolder, ".cds-object.xml"));
            File.WriteAllText(Path.Combine(newFolder, "GVL_One.st"), "VAR_GLOBAL\nEND_VAR\n");
            SyncBase.Record(_root, ExportCommand.Relative(_root, view), new List<string>());
            var baseCommit = GitRepository.Run(_root, "rev-parse refs/cts/base").Trim();
            SyncBase.SaveStamp(StampPath(), _project, _stamp, baseCommit);
            File.Delete(Path.Combine(newFolder, "GVL_One.st"));
            var treePath = Path.GetRelativePath(view, parent).Replace('\\', '/').Split('/').Concat(new[] { "EmptyAfterImport", "GVL_One" }).ToArray();
            var deleted = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TreeWithGuids(treePath);
                if (method == "objects.delete") { deleted.Add(Convert.ToString(args["guid"])); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(new[] { "guid-" + treePath.Length, "guid-" + (treePath.Length - 1) }, deleted);
            Assert.Contains("EmptyAfterImport", ((IEnumerable<object>)result["deleted_objects"]).Cast<string>());
            Assert.False(Directory.Exists(newFolder));
        }

        [Fact]
        public void DeletesTheFolderEmptiedByItsLastXmlObjectDeletion()
        {
            var view = ViewFolder.Of(_root);
            var appContainer = Directory.GetFiles(view, ".cds-object.xml", SearchOption.AllDirectories)
                .First(path => path.Replace('\\', '/').EndsWith("/Application/.cds-object.xml", StringComparison.OrdinalIgnoreCase));
            var parent = Path.GetDirectoryName(appContainer);
            var newFolder = Path.Combine(parent, "Visus");
            Directory.CreateDirectory(newFolder);
            File.Copy(appContainer, Path.Combine(newFolder, ".cds-object.xml"));
            var screen = Directory.GetFiles(view, "Visualization.xml", SearchOption.AllDirectories).Single();
            File.WriteAllText(Path.Combine(newFolder, "Visu_One.xml"), File.ReadAllText(screen)
                .Replace("<Single Name=\"Name\" Type=\"string\">Visualization</Single>", "<Single Name=\"Name\" Type=\"string\">Visu_One</Single>"));
            SyncBase.Record(_root, ExportCommand.Relative(_root, view), new List<string>());
            var baseCommit = GitRepository.Run(_root, "rev-parse refs/cts/base").Trim();
            SyncBase.SaveStamp(StampPath(), _project, _stamp, baseCommit);
            File.Delete(Path.Combine(newFolder, "Visu_One.xml"));
            var treePath = Path.GetRelativePath(view, parent).Replace('\\', '/').Split('/').Concat(new[] { "Visus", "Visu_One" }).ToArray();
            var deleted = new List<string>();
            var result = ImportCommand.Execute(ImportCall(null, (method, args) =>
            {
                if (method == "project.tree") return TreeWithGuids(treePath);
                if (method == "objects.delete") { deleted.Add(Convert.ToString(args["guid"])); return new Dictionary<string, object>(); }
                throw new InvalidOperationException("unexpected agent call " + method);
            }));
            Assert.Equal(new[] { "guid-" + treePath.Length, "guid-" + (treePath.Length - 1) }, deleted);
            Assert.Contains("Visus", ((IEnumerable<object>)result["deleted_objects"]).Cast<string>());
            Assert.False(Directory.Exists(newFolder));
            Assert.Equal("", GitRepository.Run(_root, "ls-tree -r --name-only refs/cts/base").Split('\n').Where(path => path.Contains("/Visus/")).FirstOrDefault() ?? "");
        }

        [Fact]
        public void ComparePlanVerdictListsRefusalBeforeChangedObjectsAndNextStep()
        {
            var objects = new Dictionary<string, object>
            {
                { "modified", new List<IDictionary<string, object>> { new Dictionary<string, object> { { "name", "MAIN" }, { "path", "MAIN.st" } } } },
                { "ide_changed", new List<IDictionary<string, object>> { new Dictionary<string, object> { { "name", "FB" }, { "path", "FB.st" } } } },
            };
            var answer = ImportCommand.Build(new Dictionary<string, object>
            {
                { "summary", new Dictionary<string, object> { { "modified", 1 }, { "added", 0 }, { "deleted", 0 }, { "not_importable", 0 }, { "ide_changed", 1 } } },
                { "objects", objects }, { "refused", "changed in the IDE" },
            });
            Assert.Equal(new[] { "modified", "added", "deleted", "not_importable", "ide_changed" }, answer.Pairs.Select(pair => pair.Key));
            Assert.Equal("would be refused: changed in the IDE", answer.Details[0]);
            Assert.Equal(Verdict.Error, answer.Status);
            Assert.Equal(1, answer.ExitCode);
            Assert.Equal("modified MAIN MAIN.st", answer.Details[1]);
            Assert.Equal("ide_changed FB FB.st", answer.Details[2]);
            Assert.Contains("cts import --force", answer.Details[3]);
        }

        [Fact]
        public void ImportVerdictCountsPayloadAndReportsSaveAndPartialState()
        {
            var answer = ImportCommand.Build(new Dictionary<string, object>
            {
                { "created_text_objects", new[] { "A" } }, { "updated_text_objects", new[] { "B" } },
                { "created_native_objects", new[] { "Folder" } }, { "created_objects", new[] { "Folder" } },
                { "deleted_objects", new[] { "Old" } }, { "overwritten_ide_changes", new[] { "B" } },
                { "timings", new Dictionary<string, object> { { "total_s", 0.25 } } }, { "saved", false },
                { "partial", true }, { "partial_reason", "read-back incomplete" },
            });
            Assert.Equal(new[] { "text=2", "native=1", "created=1", "deleted=1", "overwritten=1", "s=0.25", "saved=False" },
                answer.Pairs.Select(pair => pair.Key + "=" + Convert.ToString(pair.Value)));
            Assert.Equal(Verdict.Partial, answer.Status);
            Assert.Equal(2, answer.ExitCode);
            Assert.Contains("the IDE holds the change unsaved; saving the project is the user's call (cts save)", answer.Details);
        }

        [Fact]
        public void SyncAnswerNamesTheDirectionEachChangeTook()
        {
            var answer = ImportCommand.Build(new Dictionary<string, object>
            {
                { "syncing", true }, { "updated_text_objects", new[] { "DiskText" } },
                { "to_disk", new[] { "IdeText.st" } }, { "merged", new[] { "Both" } },
            });
            Assert.Contains("disk -> IDE updated DiskText", answer.Details);
            Assert.Contains("IDE -> disk IdeText.st", answer.Details);
            Assert.Contains("merged Both", answer.Details);
        }

        static IDictionary<string, object> TreeWithGuids(string[] path)
        {
            var root = new Dictionary<string, object> { { "name", "demo" }, { "children", new List<IDictionary<string, object>>() } };
            var node = root;
            for (var index = 0; index < path.Length; index++)
            {
                var child = new Dictionary<string, object> { { "name", path[index] }, { "guid", "guid-" + (index + 1) }, { "children", new List<IDictionary<string, object>>() } };
                if (index == path.Length - 2) child["type"] = "738bea1e-99bb-4f04-90bb-a7a567e74e3a";
                ((IList<IDictionary<string, object>>)node["children"]).Add(child);
                node = child;
            }
            return root;
        }

        static IDictionary<string, object> Tree(string[] path)
        {
            var root = new Dictionary<string, object> { { "name", "demo" }, { "children", new List<IDictionary<string, object>>() } };
            var node = root;
            foreach (var name in path)
            {
                var children = (IList<IDictionary<string, object>>)node["children"];
                var child = new Dictionary<string, object> { { "name", name }, { "guid", "guid-" + (node == root ? 1 : ((IList<IDictionary<string, object>>)node["children"]).Count + 1) }, { "children", new List<IDictionary<string, object>>() } };
                children.Add(child);
                node = child;
            }
            node["guid"] = "11111111-1111-1111-1111-111111111111";
            return root;
        }

        // The IDE tree a dry run reads: every object of the view, where the view has it.
        static IDictionary<string, object> ViewTree(string view)
        {
            var root = new Dictionary<string, object> { { "name", "demo" }, { "children", new List<IDictionary<string, object>>() } };
            var count = 0;
            foreach (var item in StViewReader.Read(view).Objects)
            {
                var node = (IDictionary<string, object>)root;
                foreach (var name in item.Path)
                {
                    var children = (IList<IDictionary<string, object>>)node["children"];
                    var child = children.FirstOrDefault(candidate => Equals(candidate["name"], name));
                    if (child == null)
                    {
                        child = new Dictionary<string, object> { { "name", name }, { "guid", new Guid(++count, 0, 0, new byte[8]).ToString() }, { "children", new List<IDictionary<string, object>>() } };
                        children.Add(child);
                    }
                    node = child;
                }
            }
            return root;
        }

        CliCall ImportCall(string[] flags, Func<string, IDictionary<string, object>, IDictionary<string, object>> fake, bool online = false, IEnumerable<string> deny = null, string ideStamp = null)
        {
            return Call("import", flags, fake, online, deny, ideStamp);
        }

        CliCall SyncCall(string[] flags, Func<string, IDictionary<string, object>, IDictionary<string, object>> fake, bool online = false, IEnumerable<string> deny = null, string ideStamp = null)
        {
            return Call("sync", flags, fake, online, deny, ideStamp);
        }

        CliCall Call(string commandName, string[] flags, Func<string, IDictionary<string, object>, IDictionary<string, object>> fake, bool online, IEnumerable<string> deny, string ideStamp)
        {
            var command = CliCommands.All.Single(item => item.Name == commandName);
            var args = new[] { commandName }.Concat(flags ?? Array.Empty<string>()).ToArray();
            var options = CliOptions.Parse(args, null, command);
            var project = new Dictionary<string, object> { { "path", _project }, { "sync_folder", _root } };
            var hello = new Hello(42, new Dictionary<string, object> { { "project", project }, { "ide_stamp", ideStamp ?? _stamp } });
            // Each reply crosses JSON as on the pipe: arrays arrive as List<object>.
            return new CliCall(command, options, hello, 30, (method, args) => (IDictionary<string, object>)Json.Parse(Json.Serialize(method == "project.status"
                ? new Dictionary<string, object> { { "plc", new Dictionary<string, object> { { "online", online } } } }
                : method == "project.permissions" ? new Dictionary<string, object> { { "deny", (deny ?? Enumerable.Empty<string>()).Cast<object>().ToList() } }
                : method == "project.source" ? Marked(Convert.ToString(args["source"]))
                : fake(method, args))));
        }

        // The labels `project.source` was given, in order.
        readonly List<string> _sources = new List<string>();

        IDictionary<string, object> Marked(string source)
        {
            _sources.Add(source);
            return new Dictionary<string, object> { { "changed", true } };
        }

        void Export(Func<string, IDictionary<string, object>, IDictionary<string, object>> fake)
        {
            var command = CliCommands.All.Single(item => item.Name == "export");
            var options = CliOptions.Parse(new[] { "export" }, null, command);
            var project = new Dictionary<string, object> { { "path", _project }, { "sync_folder", _root } };
            var hello = new Hello(42, new Dictionary<string, object> { { "project", project }, { "ide_stamp", _stamp } });
            ExportCommand.Execute(new CliCall(command, options, hello, 30, fake));
        }

        string StampPath() => Path.Combine(GitRepository.Run(_root, "rev-parse --absolute-git-dir").Trim(), "cts", "ide-stamp.json");
        void Git(string args) => GitRepository.Run(_root, args);
        void Peer(string args) => GitRepository.Run(_peer, args);
        public void Dispose() { try { Directory.Delete(_root, true); } catch (IOException) { } try { Directory.Delete(_peer, true); } catch (IOException) { } }

        [Fact]
        public void A_commit_says_the_IDE_project_stays_unsaved()
        {
            var data = new Dictionary<string, object>
            {
                { "committed", true }, { "commit", "fc7a965fbb2e" }, { "branch", "master" }, { "files", 1 }, { "differ", 0 }, { "ide_unsaved", true },
            };
            var answer = CommitCommand.Command.Build(data);
            Assert.DoesNotContain(answer.Pairs, pair => pair.Key == "ide_differs");
            Assert.Equal("the IDE project stays unsaved: the commit holds the folder's files, not the project file; cts save when the engineer wants it saved", answer.Details.Last());
            data.Remove("ide_unsaved");
            Assert.DoesNotContain(CommitCommand.Command.Build(data).Details, line => line.Contains("stays unsaved"));
        }

        [Fact]
        public void A_commit_of_a_disk_the_IDE_differs_from_warns_and_still_commits()
        {
            var data = new Dictionary<string, object> { { "committed", true }, { "commit", "fc7a965fbb2e" }, { "branch", "master" }, { "files", 2 }, { "differ", 3 } };
            var answer = CommitCommand.Command.Build(data);
            Assert.Equal("ok", answer.Status);
            Assert.Contains(answer.Pairs, pair => pair.Key == "ide_differs" && Equals(pair.Value, 3));
            Assert.StartsWith("[WARN] the IDE and the disk differ in 3 object(s)", answer.Details.Single());
        }
    }
}
