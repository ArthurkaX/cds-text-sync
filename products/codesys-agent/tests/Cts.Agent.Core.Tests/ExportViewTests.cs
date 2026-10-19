using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Text;
using System.Xml.Linq;
using Cts.Cli;
using Cts.Sync;
using Xunit;

namespace Cts.Agent.Tests
{
    public sealed class ExportViewTests
    {
        [Fact]
        public void A_snapshot_entry_gives_the_exported_native_and_text_list_files()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var nodes = SnapshotReader.Read(Path.Combine(fixture, "snapshot.xml")).Nodes.Values;
            foreach (var path in new[]
            {
                Path.Combine("PLC_Stabur", "Plc Logic", "Application", "Task Configuration", "Task.xml"),
                Path.Combine("PLC_Stabur", "Plc Logic", "Application", "Visualization.xml"),
                Path.Combine("POUs", "GlobalTextList.xml"),
            })
            {
                var node = nodes.Single(candidate => candidate.Name == Path.GetFileNameWithoutExtension(path));
                Assert.Equal(File.ReadAllBytes(Path.Combine(fixture, "expected", path)), ViewExport.NativeBytes(node.Entry, TextListRows.IsTextList(node.Type)));
            }
            var list = nodes.Single(candidate => candidate.Name == "GlobalTextList");
            Assert.Equal(File.ReadAllBytes(Path.Combine(fixture, "expected", "POUs", "GlobalTextList.csv")), ViewExport.CsvBytes(list.Entry, null));
        }

        [Fact]
        public void Skeleton_and_snapshot_models_have_the_same_parts()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml");
            var snapshot = SnapshotReader.Read(fixture);
            var fields = snapshot.Nodes.Values.Select(node => new SnapshotNodeFields
            {
                Guid = node.Guid,
                ParentGuid = node.ParentGuid,
                Name = node.Name,
                Type = node.Type,
                Path = node.DisplayPath,
                Entry = node.Entry,
            });
            var skeleton = SnapshotReader.FromSkeleton(fields, snapshot.Namespace);
            Assert.Equal(snapshot.Nodes.Keys.OrderBy(value => value), skeleton.Nodes.Keys.OrderBy(value => value));
            foreach (var guid in snapshot.Nodes.Keys)
                Assert.Equal(snapshot.Nodes[guid].Parts(snapshot), skeleton.Nodes[guid].Parts(skeleton));
        }

        [Fact]
        public void A_changed_method_subset_patch_matches_a_full_render()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-partial-view-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
            var source = Path.Combine(fixture, "snapshot.xml");
            var changedSnapshot = Path.Combine(root, "changed.xml");
            try
            {
                var document = XDocument.Load(source, LoadOptions.PreserveWhitespace);
                var ns = document.Root.Name.Namespace;
                var method = SnapshotReader.Read(source).Nodes.Values.Single(node => node.Name == "M_Toggle");
                var entry = document.Descendants(ns + "Single").Single(candidate =>
                    string.Equals(candidate.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid")?.Value.Trim().Trim('{', '}'), method.Guid, StringComparison.OrdinalIgnoreCase));
                var body = entry.Descendants().First(element => (string)element.Attribute("Name") == "TextBlobForSerialisation" && element.Value.Contains("xOpen := NOT xOpen;"));
                body.Value = body.Value.Replace("xOpen := NOT xOpen;", "xOpen := TRUE;");
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);

                var original = SnapshotReader.Read(source);
                var oldView = new MemoryViewFiles();
                var oldRender = ViewExport.WriteTo(source, root, null, oldView);
                var skeletonFields = original.Nodes.Values.Select(node => new SnapshotNodeFields
                {
                    Guid = node.Guid, ParentGuid = node.ParentGuid, Name = node.Name, Type = node.Type, Path = node.DisplayPath,
                }).ToList();
                var skeleton = SnapshotReader.FromSkeleton(skeletonFields, original.Namespace);
                var expanded = ViewExport.ExpandFetchGuids(skeleton, new[] { method.Guid });
                var changedModel = SnapshotReader.Read(changedSnapshot);
                foreach (var fields in skeletonFields.Where(fields => expanded.Contains(fields.Guid, StringComparer.OrdinalIgnoreCase)))
                    fields.Entry = changedModel.Nodes[fields.Guid].Entry;
                var sparse = SnapshotReader.FromSkeleton(skeletonFields, original.Namespace);
                Assert.Equal("FB_Valve", sparse.Nodes[sparse.Nodes.Values.Single(node => node.Name == "M_Toggle").ParentGuid].Name);
                var subsetFiles = new MemoryViewFiles();
                var subset = ViewExport.WriteSubset(sparse, root, subsetFiles, expanded);
                Assert.Contains(subset.GuidFiles.Keys, guid => sparse.Nodes[guid].Name == "FB_Valve");
                Assert.False(subsetFiles.Paths.Any(path => path.EndsWith("/M_Toggle.xml", StringComparison.OrdinalIgnoreCase)), string.Join(",", expanded.Select(guid => sparse.Nodes[guid].Name)) + " files=" + string.Join(",", subsetFiles.Paths.Where(path => path.Contains("FB_Valve", StringComparison.OrdinalIgnoreCase))));
                var patched = ViewExport.Patch(sparse, oldView, oldRender.GuidFiles, subsetFiles, subset.GuidFiles, expanded, Array.Empty<string>());
                Assert.Null(patched.FallbackReason);

                var completeFiles = new MemoryViewFiles();
                ViewExport.WriteTo(changedSnapshot, root, null, completeFiles);
                Assert.True(completeFiles.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase).SequenceEqual(patched.Files.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase), StringComparer.OrdinalIgnoreCase), "expected=" + string.Join(";", completeFiles.Paths.Where(path => path.Contains("M_Toggle", StringComparison.OrdinalIgnoreCase))) + " actual=" + string.Join(";", patched.Files.Paths.Where(path => path.Contains("M_Toggle", StringComparison.OrdinalIgnoreCase))));
                Assert.Equal(completeFiles.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase), patched.Files.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase));
                foreach (var path in completeFiles.Paths)
                    Assert.Equal(completeFiles.Read(path), patched.Files.Read(path));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Partial_planner_falls_back_for_collapsed_changes_and_large_groups()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "snapshot.xml");
            var model = SnapshotReader.Read(fixture);
            var collapsed = model.Nodes.Values.First(node => model.IsCollapsed(node));
            Assert.Equal("a collapsed parent changed", ViewExport.PartialFallbackReason(model, new[] { collapsed.Guid }, new[] { collapsed.Guid }));
            var settings = model.Nodes.Values.Single(node => node.Name == "Project Settings");
            Assert.Equal("Project Settings changed", ViewExport.PartialFallbackReason(model, new[] { settings.Guid }, new[] { settings.Guid }));
            var oversized = Enumerable.Range(0, 51).Select(_ => Guid.NewGuid().ToString("D")).ToList();
            Assert.Equal("more than 50 objects need entries", ViewExport.PartialFallbackReason(model, Array.Empty<string>(), oversized));
        }

        [Fact]
        public void Partial_patch_falls_back_when_a_moved_native_file_has_no_fresh_entry()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-partial-move-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
            try
            {
                var snapshot = Path.Combine(fixture, "snapshot.xml");
                var original = SnapshotReader.Read(snapshot);
                var previous = new MemoryViewFiles();
                var rendered = ViewExport.WriteTo(snapshot, root, null, previous);
                var fields = original.Nodes.Values.Select(node => new SnapshotNodeFields
                {
                    Guid = node.Guid, ParentGuid = node.ParentGuid, Name = node.Name, Type = node.Type,
                    Path = node.DisplayPath.Concat(new[] { node.Guid == original.Nodes.Values.First(value => value.Name == "Task").Guid ? "Moved" : "" }).Where(value => value.Length > 0).ToList(),
                });
                var moved = SnapshotReader.FromSkeleton(fields, original.Namespace);
                var patch = ViewExport.Patch(moved, previous, rendered.GuidFiles, new MemoryViewFiles(), new Dictionary<string, IList<string>>(), Array.Empty<string>(), Array.Empty<string>());
                Assert.Equal("a moved native XML needs a fresh entry", patch.FallbackReason);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Added_native_object_subset_patch_matches_a_full_render()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-add-");
            var changedSnapshot = Path.Combine(root, "added.xml");
            try
            {
                var document = XDocument.Load(Path.Combine(fixture, "snapshot.xml"), LoadOptions.PreserveWhitespace);
                var ns = document.Root.Name.Namespace;
                var source = document.Descendants(ns + "Single").Single(entry =>
                    entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Name")?.Value == "Task");
                var added = new XElement(source);
                var meta = added.Elements().First(element => (string)element.Attribute("Name") == "MetaObject");
                meta.Elements().First(element => (string)element.Attribute("Name") == "Guid").Value = "00000000-0000-0000-0000-000000000001";
                meta.Elements().First(element => (string)element.Attribute("Name") == "Name").Value = "TaskCopy";
                source.Parent.Add(added);
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                AssertPartialMatchesFull(Path.Combine(fixture, "snapshot.xml"), changedSnapshot, root, new[] { "00000000-0000-0000-0000-000000000001" }, Array.Empty<string>());
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void A_graphical_pou_is_an_xml_with_its_st_members_beside_it()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-graphical-");
            var changedSnapshot = Path.Combine(root, "graphical.xml");
            try
            {
                var document = XDocument.Load(Path.Combine(fixture, "snapshot.xml"), LoadOptions.PreserveWhitespace);
                var implementation = EntryByGuid(document, "52d091fb-dc8a-40db-9a29-3cf23964be01").Elements().First(element => (string)element.Attribute("Name") == "Object")
                    .Elements().First(element => (string)element.Attribute("Name") == "Implementation");
                implementation.ReplaceNodes(new XElement(document.Root.Name.Namespace + "List", new XAttribute("Name", "NetworkList")));
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                var files = new MemoryViewFiles();
                var result = ViewExport.WriteTo(changedSnapshot, root, null, files);
                var valve = files.Paths.Where(path => path.Contains("FB_Valve")).OrderBy(path => path, StringComparer.Ordinal).ToList();
                Assert.Equal(new[] { "FB_Valve.A_Reset.xml", "FB_Valve.M_Toggle.xml", "FB_Valve.P_Open.Get.xml", "FB_Valve.P_Open.Set.xml", "FB_Valve.P_Open.xml", "FB_Valve.xml" }, valve.Select(Path.GetFileName));
                // Compare finds an object's guid by this path; sync writes only what it can name.
                var reset = result.Model.Nodes.Values.Single(node => node.Name == "A_Reset");
                Assert.Contains(result.Model.XmlPath(reset), valve);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Removed_native_object_subset_patch_matches_a_full_render()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-delete-");
            var changedSnapshot = Path.Combine(root, "deleted.xml");
            try
            {
                var document = XDocument.Load(Path.Combine(fixture, "snapshot.xml"), LoadOptions.PreserveWhitespace);
                var ns = document.Root.Name.Namespace;
                var task = document.Descendants(ns + "Single").Single(entry =>
                    entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Name")?.Value == "Task");
                var guid = task.Elements().First(element => (string)element.Attribute("Name") == "MetaObject").Elements().First(element => (string)element.Attribute("Name") == "Guid").Value.Trim().Trim('{', '}');
                task.Remove();
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                AssertPartialMatchesFull(Path.Combine(fixture, "snapshot.xml"), changedSnapshot, root, Array.Empty<string>(), new[] { guid });
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Removed_top_level_object_rerenders_its_parent_with_whole_owners()
        {
            // Compare seeds a removed object's parent; the parent's members
            // come with their owners, or they render as files of their own.
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-delete-gvl-");
            var oldSnapshot = Path.Combine(fixture, "snapshot.xml");
            var changedSnapshot = Path.Combine(root, "deleted.xml");
            try
            {
                var gvl = SnapshotReader.Read(oldSnapshot).Nodes.Values.Single(node => node.Name == "GVL_Bench");
                var document = XDocument.Load(oldSnapshot, LoadOptions.PreserveWhitespace);
                EntryByGuid(document, gvl.Guid).Remove();
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                AssertPartialMatchesFull(oldSnapshot, changedSnapshot, root, new[] { gvl.ParentGuid }, new[] { gvl.Guid });
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Renamed_folder_with_children_subset_patch_matches_a_full_render()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-folder-rename-");
            var oldSnapshot = Path.Combine(fixture, "folder-case", "snapshot.xml");
            var changedSnapshot = Path.Combine(root, "folder-renamed.xml");
            try
            {
                var model = SnapshotReader.Read(oldSnapshot);
                var folder = model.Nodes.Values.First(node => TypeKinds.All.Kind(node.Type) == "folder");
                var oldName = folder.Name;
                var newName = oldName + "_Renamed";
                var document = XDocument.Load(oldSnapshot, LoadOptions.PreserveWhitespace);
                var entry = EntryByGuid(document, folder.Guid);
                entry.Elements().First(element => (string)element.Attribute("Name") == "MetaObject").Elements().First(element => (string)element.Attribute("Name") == "Name").Value = newName;
                var ns = document.Root.Name.Namespace;
                foreach (var path in document.Descendants(ns + "Array").Where(element => (string)element.Attribute("Name") == "Path"))
                    foreach (var segment in path.Elements().Where(element => element.Value == oldName)) segment.Value = newName;
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                AssertPartialMatchesFull(oldSnapshot, changedSnapshot, root, new[] { folder.Guid }, Array.Empty<string>());
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Renamed_pou_takes_the_collapsed_parent_fallback()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-pou-rename-");
            var oldSnapshot = Path.Combine(fixture, "snapshot.xml");
            var changedSnapshot = Path.Combine(root, "pou-renamed.xml");
            try
            {
                var model = SnapshotReader.Read(oldSnapshot);
                var pou = model.Nodes.Values.Single(node => node.Name == "FB_Valve");
                var document = XDocument.Load(oldSnapshot, LoadOptions.PreserveWhitespace);
                var entry = EntryByGuid(document, pou.Guid);
                entry.Elements().First(element => (string)element.Attribute("Name") == "MetaObject").Elements().First(element => (string)element.Attribute("Name") == "Name").Value = "FB_Valve_Renamed";
                var ns = document.Root.Name.Namespace;
                foreach (var path in document.Descendants(ns + "Array").Where(element => (string)element.Attribute("Name") == "Path"))
                    foreach (var segment in path.Elements().Where(element => element.Value == "FB_Valve")) segment.Value = "FB_Valve_Renamed";
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                var changedModel = SnapshotReader.Read(changedSnapshot);
                var fetch = ViewExport.ExpandFetchGuids(changedModel, new[] { pou.Guid });
                Assert.Equal("a collapsed parent changed", ViewExport.PartialFallbackReason(changedModel, new[] { pou.Guid }, fetch));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Creating_a_name_collision_subset_patch_matches_a_full_render()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = NewRenderRoot(fixture, "cts-partial-collision-");
            var oldSnapshot = Path.Combine(fixture, "snapshot.xml");
            var changedSnapshot = Path.Combine(root, "collision.xml");
            const string addedGuid = "00000000-0000-0000-0000-000000000002";
            try
            {
                var document = XDocument.Load(oldSnapshot, LoadOptions.PreserveWhitespace);
                var ns = document.Root.Name.Namespace;
                var source = document.Descendants(ns + "Single").Single(entry =>
                    entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Name")?.Value == "Task");
                var added = new XElement(source);
                added.Elements().First(element => (string)element.Attribute("Name") == "MetaObject").Elements().First(element => (string)element.Attribute("Name") == "Guid").Value = addedGuid;
                source.Parent.Add(added);
                document.Save(changedSnapshot, SaveOptions.DisableFormatting);
                AssertPartialMatchesFull(oldSnapshot, changedSnapshot, root, new[] { addedGuid }, Array.Empty<string>());
            }
            finally { Directory.Delete(root, true); }
        }

        static string NewRenderRoot(string fixture, string prefix)
        {
            var root = Path.Combine(Path.GetTempPath(), prefix + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
            return root;
        }

        static XElement EntryByGuid(XDocument document, string guid)
        {
            XNamespace ns = document.Root.Name.Namespace;
            return document.Descendants(ns + "Single").Single(entry =>
                string.Equals(entry.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "MetaObject")?.Elements().FirstOrDefault(element => (string)element.Attribute("Name") == "Guid")?.Value.Trim().Trim('{', '}'), guid, StringComparison.OrdinalIgnoreCase));
        }

        static void AssertPartialMatchesFull(string oldSnapshot, string changedSnapshot, string root, IEnumerable<string> changedGuids, IEnumerable<string> removedGuids)
        {
            var oldModel = SnapshotReader.Read(oldSnapshot);
            var changedModel = SnapshotReader.Read(changedSnapshot);
            var previous = new MemoryViewFiles();
            var oldRender = ViewExport.WriteTo(oldSnapshot, root, null, previous);
            var fields = changedModel.Nodes.Values.Select(node => new SnapshotNodeFields
            {
                Guid = node.Guid, ParentGuid = node.ParentGuid, Name = node.Name, Type = node.Type, Path = node.DisplayPath,
            }).ToList();
            var skeleton = SnapshotReader.FromSkeleton(fields, changedModel.Namespace);
            var removed = removedGuids.ToList();
            var changed = changedGuids.Where(skeleton.Nodes.ContainsKey).ToList();
            foreach (var node in changedModel.Nodes.Values)
                if (oldModel.Nodes.TryGetValue(node.Guid, out var oldNode) && !oldNode.Parts(oldModel).SequenceEqual(node.Parts(changedModel), StringComparer.OrdinalIgnoreCase)) changed.Add(node.Guid);
            changed = changed.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            var fetch = ViewExport.ExpandFetchGuids(skeleton, changed);
            foreach (var entry in fields.Where(field => fetch.Contains(field.Guid, StringComparer.OrdinalIgnoreCase)))
                entry.Entry = changedModel.Nodes[entry.Guid].Entry;
            var sparse = SnapshotReader.FromSkeleton(fields, changedModel.Namespace);
            var subsetFiles = new MemoryViewFiles();
            var subset = ViewExport.WriteSubset(sparse, root, subsetFiles, fetch);
            var patched = ViewExport.Patch(sparse, previous, oldRender.GuidFiles, subsetFiles, subset.GuidFiles, fetch, removed);
            Assert.Null(patched.FallbackReason);
            var complete = new MemoryViewFiles();
            ViewExport.WriteTo(changedSnapshot, root, null, complete);
            Assert.Equal(complete.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase), patched.Files.Paths.OrderBy(path => path, StringComparer.OrdinalIgnoreCase));
            foreach (var path in complete.Paths) Assert.Equal(complete.Read(path), patched.Files.Read(path));
        }

        [Theory]
        [InlineData("FUNCTION_BLOCK", "END_FUNCTION_BLOCK")]
        [InlineData("PROGRAM", "END_PROGRAM")]
        [InlineData("FUNCTION", "END_FUNCTION")]
        [InlineData("INTERFACE", "END_INTERFACE")]
        [InlineData("METHOD", "END_METHOD")]
        [InlineData("PROPERTY", "END_PROPERTY")]
        [InlineData("VAR_GLOBAL", "")]
        [InlineData("TYPE", "")]
        public void Text_parts_lose_blank_edges_and_keep_first_line_indentation(string kind, string end)
        {
            var part = new ViewExport.TextPart
            {
                Kind = kind,
                Declaration = "DECL\n\n",
                Implementation = "\n\tBODY := 1;\n\n",
            };

            var content = ViewExport.Join(part, Array.Empty<ViewExport.TextPart>());

            Assert.StartsWith("DECL\n" + StPragma.ImplementationMarker + "\n\tBODY := 1;\n", content);
            Assert.EndsWith(end.Length > 0 ? "\tBODY := 1;\n" + end + "\n" : "\tBODY := 1;\n", content);
        }

        [Fact]
        public void Same_output_name_siblings_get_guid_suffixes_on_both_paths()
        {
            var model = new Cts.Sync.ProjectModel();
            var first = new Cts.Sync.ProjectNode { Guid = "abcdef01-0000-0000-0000-000000000001", Name = "First", OutputName = "synthetic.bin" };
            var second = new Cts.Sync.ProjectNode { Guid = "abcdef02-0000-0000-0000-000000000002", Name = "Second", OutputName = "synthetic.bin" };
            first.DisplayPath.Add("Embedded");
            second.DisplayPath.Add("Embedded");
            model.Nodes.Add(first.Guid, first);
            model.Nodes.Add(second.Guid, second);

            Assert.Equal("Embedded/synthetic.bin__abcdef01.xml", model.XmlPath(first));
            Assert.Equal("Embedded/synthetic.bin__abcdef02.xml", model.XmlPath(second));
        }

        [Fact]
        public void Export_writes_both_same_name_embedded_resources()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-duplicates-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                var snapshot = Path.Combine(root, "snapshot.xml");
                var entries = new[]
                {
                    SyntheticResource("abcdef01-0000-0000-0000-000000000001"),
                    SyntheticResource("abcdef02-0000-0000-0000-000000000002"),
                };
                new XDocument(new XElement("Snapshot", new XElement("List2", new XAttribute("Name", "EntryList"), entries))).Save(snapshot);

                ViewExport.Write(snapshot, root, null);

                var view = Path.Combine(root, "project-view", "Resources", "Embedded");
                Assert.Equal(new[] { "synthetic.bin__abcdef01.xml", "synthetic.bin__abcdef02.xml" },
                    Directory.GetFiles(view).Select(Path.GetFileName).OrderBy(name => name, StringComparer.Ordinal));
            }
            finally { Directory.Delete(root, true); }
        }

        static XElement SyntheticResource(string guid)
        {
            return new XElement("Single",
                new XElement("Single", new XAttribute("Name", "MetaObject"),
                    new XElement("Single", new XAttribute("Name", "Guid"), guid),
                    new XElement("Single", new XAttribute("Name", "Name"), "bundle|synthetic.bin"),
                    new XElement("Single", new XAttribute("Name", "TypeGuid"), "9001d745-b9c5-4d77-90b7-b29c3f77a23b"),
                    new XElement("Single", new XAttribute("Name", "ParentGuid"), "00000000-0000-0000-0000-000000000000")),
                new XElement("Object"));
        }

        [Fact]
        public void Action_and_property_accessor_bodies_keep_first_line_indentation()
        {
            var action = new ViewExport.TextPart
            {
                Kind = "ACTION",
                Node = new Cts.Sync.ProjectNode { Name = "SyntheticAction" },
                Implementation = "\n\tACTION_BODY := TRUE;\n\n",
            };
            var property = new ViewExport.TextPart
            {
                Kind = "PROPERTY",
                Declaration = "PROPERTY SyntheticProperty : BOOL",
                Accessors = new List<ViewExport.TextPart>
                {
                    new ViewExport.TextPart { Kind = "GET", Implementation = "\n\tACCESS_BODY := TRUE;\n\n" },
                },
            };

            var actionContent = ViewExport.Join(new ViewExport.TextPart { Kind = "FUNCTION_BLOCK", Declaration = "FUNCTION_BLOCK Synthetic" }, new[] { action });
            var propertyContent = ViewExport.Join(new ViewExport.TextPart { Kind = "FUNCTION_BLOCK", Declaration = "FUNCTION_BLOCK Synthetic" }, new[] { property });

            Assert.Contains("ACTION SyntheticAction:\n\tACTION_BODY := TRUE;\nEND_ACTION", actionContent);
            Assert.Contains("GET\n// --- implementation ---\n\tACCESS_BODY := TRUE;\nEND_GET", propertyContent);
        }

        [Fact]
        public void FreshExportMatchesGoldenView()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
            var result = ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
            Assert.NotEmpty(result.Natives);
            Assert.Empty(result.KeptOrphans);
            var expected = Directory.GetFiles(Path.Combine(fixture, "expected"), "*", SearchOption.AllDirectories)
                .ToDictionary(p => Path.GetRelativePath(Path.Combine(fixture, "expected"), p).Replace('\\', '/'));
            var actualRoot = Path.Combine(root, "project-view");
            var actual = Directory.GetFiles(actualRoot, "*", SearchOption.AllDirectories)
                .ToDictionary(p => Path.GetRelativePath(actualRoot, p).Replace('\\', '/'));
            Assert.Equal(expected.Keys.OrderBy(x => x), actual.Keys.OrderBy(x => x));
            foreach (var key in expected.Keys) Assert.Equal(File.ReadAllBytes(expected[key]), File.ReadAllBytes(actual[key]));
            Directory.Delete(root, true);
        }

        [Fact]
        public void An_object_the_IDE_reads_empty_refuses_the_export_before_a_file_is_written()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-unread-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                // What an older CODESYS keeps of an object a newer one saved:
                // the object, with every line of its text empty.
                var snapshot = XDocument.Load(Path.Combine(fixture, "snapshot.xml"));
                var emptied = snapshot.Descendants().First(e => (string)e.Attribute("Name") == "Interface"
                    && e.Elements().Any(child => (string)child.Attribute("Name") == "TextDocument"));
                foreach (var text in emptied.Descendants().Where(e => (string)e.Attribute("Name") is "Text" or "TextBlobForSerialisation")) text.Value = "";
                var path = Path.Combine(root, "snapshot.xml");
                snapshot.Save(path);

                var refused = Assert.Throws<InvalidOperationException>(() => ViewExport.Write(path, root, null));

                Assert.Contains("1 object(s) read empty in the IDE", refused.Message);
                Assert.Empty(Directory.GetFiles(Path.Combine(root, "project-view"), "*", SearchOption.AllDirectories));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void Folder_and_memory_render_targets_write_the_same_paths_and_bytes()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-targets-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                var memory = new MemoryViewFiles();
                ViewExport.WriteTo(Path.Combine(fixture, "snapshot.xml"), root, null, memory);
                var folder = new DirectoryViewFiles(Path.Combine(root, "project-view"));
                Assert.Equal(folder.Paths.OrderBy(path => path), memory.Paths.OrderBy(path => path));
                foreach (var path in folder.Paths)
                {
                    Assert.Equal(folder.Read(path), memory.Read(path));
                }
            }
            finally
            {
                Directory.Delete(root, true);
            }
        }

        [Fact]
        public void Export_keeps_a_file_that_differs_from_the_IDE_only_in_blank_edges()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-edges-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                var motor = Path.Combine(root, "project-view", "PLC_Stabur", "Plc Logic", "Application", "FB_Motor.st");
                var spaced = File.ReadAllText(motor).Replace("END_VAR\n// --- implementation ---\n", "END_VAR\n\n// --- implementation ---\n\n");
                File.WriteAllText(motor, spaced);
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                Assert.Equal(spaced, File.ReadAllText(motor));

                var logger = Path.Combine(Path.GetDirectoryName(motor), "FB_Logger.st");
                var text = File.ReadAllText(logger);
                var fmt = text.IndexOf("\n\n(*\nPrints an integer", StringComparison.Ordinal);
                var moved = text.Substring(0, fmt + 1).Replace("END_FUNCTION_BLOCK\n", "END_FUNCTION_BLOCK\n\n" + text.Substring(fmt + 2));
                Assert.NotEqual(text, moved);
                File.WriteAllText(logger, moved);
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                Assert.Equal(moved, File.ReadAllText(logger));

                File.WriteAllText(motor, spaced.Replace("xStartPrev := xStart;", "xStartPrev := FALSE;"));
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                Assert.Contains("END_VAR\n// --- implementation ---\nxStartRise", File.ReadAllText(motor));
            }
            finally
            {
                Directory.Delete(root, true);
            }
        }

        [Theory]
        [InlineData("<a></a>", "<a />")]
        [InlineData("<a x=\"1\"></a>", "<a x=\"1\" />")]
        [InlineData("<o><a></a><b>t</b><c y=\"&gt;\"></c></o>", "<o><a /><b>t</b><c y=\"&gt;\" /></o>")]
        [InlineData("<ab></a>", "<ab></a>")]
        [InlineData("<a>x</a></b>", "<a>x</a></b>")]
        [InlineData("<n:v.w-1></n:v.w-1>", "<n:v.w-1 />")]
        [InlineData("<_a></_a><b></b>", "<_a /><b />")]
        [InlineData("text without tags", "text without tags")]
        public void SelfCloseClosesOnlyAStartTagFollowedByItsOwnEndTag(string xml, string expected)
        {
            Assert.Equal(expected, ViewExport.SelfClose(xml));
        }

        [Fact]
        public void ReaderAcceptsEveryGoldenExportTextFile()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-read-view-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                var writtenParts = new List<ExportedTextPart>();
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null, writtenParts);
                var result = StViewReader.Read(Path.Combine(root, "project-view"));
                Assert.Empty(result.Errors);
                Assert.NotEmpty(result.Objects);
                Assert.Contains(result.Objects, o => o.Kind == "FUNCTION_BLOCK");
                Assert.Contains(result.Objects, o => o.Kind == "METHOD");
                Assert.All(result.Objects, o => Assert.False(string.IsNullOrEmpty(o.File)));
                Assert.Equal(writtenParts.Count, result.Objects.Count);
                foreach (var expectedPart in writtenParts)
                {
                    var matchingParts = result.Objects.Where(o => o.Path.SequenceEqual(expectedPart.Path, StringComparer.Ordinal)).ToList();
                    Assert.True(matchingParts.Count == 1, string.Join("/", expectedPart.Path) + " matched " + string.Join(";", result.Objects.Select(o => o.Key)));
                    var actualPart = matchingParts[0];
                    Assert.True(expectedPart.Kind == actualPart.Kind, string.Join("/", expectedPart.Path) + " expected " + expectedPart.Kind + " got " + actualPart.Kind);
                    var expectedDeclaration = (expectedPart.Declaration ?? "").Replace("\r\n", "\n").Replace('\r', '\n');
                    if (expectedDeclaration.StartsWith("(* cds-text-sync:", StringComparison.Ordinal))
                        expectedDeclaration = expectedDeclaration.Substring(expectedDeclaration.IndexOf('\n') + 1);
                    Assert.Equal(expectedDeclaration.TrimEnd(), (actualPart.Declaration ?? "").Replace("\r\n", "\n").Replace('\r', '\n').TrimEnd());
                    Assert.Equal((expectedPart.Implementation ?? "").Trim(), (actualPart.Implementation ?? "").Trim());
                }
            }
            finally { Directory.Delete(root, true); }
        }

        // A folder made by an import records "PLC Logic" where its device's
        // folder is "Plc Logic": it lands in the one directory, and an
        // interface carries its method inside its file.
        [Fact]
        public void FolderTakesItsContainersSpelling()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture", "folder-case");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-folder-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                File.Copy(Path.Combine(fixture, "..", "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                var view = Path.Combine(root, "project-view");
                var files = Directory.GetFiles(view, "*", SearchOption.AllDirectories)
                    .Select(p => Path.GetRelativePath(view, p).Replace('\\', '/')).OrderBy(p => p, StringComparer.Ordinal);
                Assert.Equal(File.ReadAllLines(Path.Combine(fixture, "files.txt")), files);
                var application = Path.Combine(view, "PLC_Stabur", "Plc Logic", "Application");
                Assert.Equal(File.ReadAllBytes(Path.Combine(fixture, "I_LiveTmp.st")), File.ReadAllBytes(Path.Combine(application, "I_LiveTmp.st")));
                Assert.Equal(File.ReadAllBytes(Path.Combine(fixture, "LiveTmpFolder.cds-object.xml")),
                    File.ReadAllBytes(Path.Combine(application, "LiveTmpFolder", ".cds-object.xml")));
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void CSharpBaseTreeMatchesPythonExportGolden()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-base-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                GitRepository.Run(root, "init --quiet");
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                SyncBase.Record(root, "project-view", new List<string>());
                var actual = GitRun.In(root, "ls-tree -r --full-tree refs/cts/base");
                Assert.Equal(0, actual.ExitCode);
                Assert.Equal(File.ReadAllText(Path.Combine(fixture, "python-base-tree.txt")), actual.Output);
                var shape = GitRun.In(root, "show -s --format=%P%n%s refs/cts/base");
                Assert.Equal("\ncts base: export\n", shape.Output);
            }
            finally { Directory.Delete(root, true); }
        }

        // Someone edits the view while an export writes it. A file changed before cts wrote
        // it keeps that edit and its base; one changed after keeps the edit, and its base
        // takes the IDE's text, which cts wrote; a file made meanwhile stays out of the base.
        [Fact]
        public void Files_changed_while_the_export_writes_keep_their_edits_out_of_the_base()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-meanwhile-" + Guid.NewGuid().ToString("N"));
            var view = Path.Combine(root, "project-view");
            Directory.CreateDirectory(root);
            try
            {
                RunGit(root, "init --quiet");
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                var first = ViewStamps.Take(view);
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null, null, first);
                File.WriteAllText(Path.Combine(view, "Stray.st"), "made meanwhile");
                SyncBase.Record(root, "project-view", new List<string>(), first);
                Assert.DoesNotContain("project-view/Stray.st", RunGit(root, "ls-tree -r --name-only refs/cts/base"));

                var files = Directory.GetFiles(view, "*.st", SearchOption.AllDirectories).Where(path => !path.EndsWith("Stray.st")).Take(2).ToList();
                string Repo(string full) => "project-view/" + ExportCommand.Relative(view, full);
                string Base(string full) => GitRepository.Run(root, "show " + ProcessArgs.Quote("refs/cts/base:" + Repo(full)));
                var ide = files.Select(File.ReadAllText).ToList();
                File.WriteAllText(files[1], "an older sync's text\n");
                SyncBase.Record(root, "project-view", new List<string>());

                var stamps = ViewStamps.Take(view);
                File.AppendAllText(files[0], "// edited before cts wrote it\n");
                ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null, null, stamps);
                Assert.Equal(ide[1], File.ReadAllText(files[1]));
                File.AppendAllText(files[1], "// edited after cts wrote it\n");
                File.WriteAllText(Path.Combine(view, "New.st"), "made meanwhile");
                SyncBase.Record(root, "project-view", new List<string>(), stamps);

                Assert.EndsWith("// edited before cts wrote it\n", File.ReadAllText(files[0]));
                Assert.Equal(ide[0], Base(files[0]));
                Assert.EndsWith("// edited after cts wrote it\n", File.ReadAllText(files[1]));
                Assert.Equal(ide[1], Base(files[1]));
                Assert.DoesNotContain("project-view/New.st", RunGit(root, "ls-tree -r --name-only refs/cts/base"));
                Assert.Equal(new[] { "New.st", ExportCommand.Relative(view, files[0]), ExportCommand.Relative(view, files[1]) }.OrderBy(path => path, StringComparer.OrdinalIgnoreCase),
                    stamps.Changed);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void ForceSnapshotStoresTheDiskViewOnTheOverwrittenRef()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-export-force-" + Guid.NewGuid().ToString("N"));
            var view = Path.Combine(root, "project-view", "POUs");
            Directory.CreateDirectory(view);
            try
            {
                GitRepository.Run(root, "init --quiet");
                var file = Path.Combine(view, "MAIN.st");
                File.WriteAllText(file, "PROGRAM MAIN // disk edit\n");
                SyncBase.KeepOverwritten(root, "project-view");
                var saved = GitRun.In(root, "show refs/cts/overwritten:project-view/POUs/MAIN.st");
                Assert.Equal(0, saved.ExitCode);
                Assert.Equal("PROGRAM MAIN // disk edit\n", saved.Output);
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void ForceImportStoresTheIDEFileOnTheOverwrittenRefBeforeReplacement()
        {
            var root = Path.Combine(Path.GetTempPath(), "cts-import-force-" + Guid.NewGuid().ToString("N"));
            var view = Path.Combine(root, "project-view", "POUs");
            Directory.CreateDirectory(view);
            try
            {
                GitRepository.Run(root, "init --quiet");
                File.WriteAllText(Path.Combine(view, "MAIN.st"), "PROGRAM MAIN\\nIDE version\\n");
                File.WriteAllText(Path.Combine(view, "KEEP.st"), "PROGRAM KEEP\\n");
                var result = SyncBase.KeepOverwritten(root, "project-view", new Dictionary<string, byte[]>
                {
                    { "project-view/POUs/MAIN.st", Encoding.UTF8.GetBytes("PROGRAM MAIN\\nIDE version\\n") },
                });
                Assert.NotNull(result);
                Assert.Contains("IDE version", GitRun.In(root, "show refs/cts/overwritten:project-view/POUs/MAIN.st").Output);
                Assert.Contains("PROGRAM KEEP", GitRun.In(root, "show refs/cts/overwritten:project-view/POUs/KEEP.st").Output);
                GitRepository.Run(root, "diff --cached --quiet");
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void ExportHelpAndVerdictExposeTheCommandContract()
        {
            var command = CliCommands.All.Single(item => item.Name == "export");
            var help = CliRun.Help(command);
            Assert.Contains("--sync-folder PATH", help);
            Assert.Contains("--force", help);
            Assert.Contains("refs/cts/overwritten", help);
            var data = new System.Collections.Generic.Dictionary<string, object>
            {
                { "text_sync", "success" }, { "size", 42L }, { "sync_folder", "/sync" },
                { "ide", "exported" },
                { "pending_import", new[] { "POUs/MAIN.st" } }, { "kept", new[] { "POUs/Old.st" } },
            };
            var answer = ExportCommand.Build(data);
            Assert.Equal("ok export text_sync=success bytes=42 folder=/sync ide=exported kept=2", Verdict.Line(answer.Status, command.Verb, answer.Pairs));
            var fast = ExportCommand.Build(new System.Collections.Generic.Dictionary<string, object>
            {
                { "text_sync", "success" }, { "sync_folder", "/sync" }, { "ide", "unchanged" },
            });
            Assert.Equal("ok export text_sync=success folder=/sync ide=unchanged", Verdict.Line(fast.Status, command.Verb, fast.Pairs));
        }

        [Fact]
        public void NativeCacheKeepsThePythonJsonShapeForItsProjectOnly()
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-native-cache-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                GitRepository.Run(root, "init --quiet");
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                var result = ViewExport.Write(Path.Combine(fixture, "snapshot.xml"), root, null);
                SyncBase.SaveNatives(root, "C:\\projects\\a.project", result.Natives, Path.Combine(root, "project-view"));
                var cachePath = Path.Combine(RunGit(root, "rev-parse --absolute-git-dir"), "cts", "same-natives.json");
                var cache = Json.Parse(File.ReadAllText(cachePath)) as IDictionary<string, object>;
                Assert.Equal("3.5.0", cache["cts"]);
                var objects = cache["objects"] as IDictionary<string, object>;
                var stored = result.Natives.Where(native => File.Exists(Path.Combine(root, "project-view", native.Path.Replace('/', Path.DirectorySeparatorChar))))
                    .GroupBy(native => native.Guid.Trim('{', '}').ToLowerInvariant()).Select(group => group.Last()).ToList();
                Assert.Equal(stored.Count, objects.Count);
                var native = stored[0];
                var pair = objects[native.Guid.Trim('{', '}').ToLowerInvariant()] as IList<object>;
                Assert.Equal(native.Timestamp, pair[0]);
                Assert.Equal(ViewExport.BlobId(File.ReadAllBytes(Path.Combine(root, "project-view", native.Path.Replace('/', Path.DirectorySeparatorChar)))), pair[1]);
                Assert.Equal(objects.Count, SyncBase.LoadNatives(root, "C:\\projects\\a.project").Count);
                Assert.Empty(SyncBase.LoadNatives(root, "C:\\projects\\b.project"));
            }
            finally { Directory.Delete(root, true); }
        }

        [Theory]
        [InlineData(false, "no-force")]
        [InlineData(true, "force")]
        public void IncrementalExportMatchesPythonGolden(bool force, string label)
        {
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var cases = Path.Combine(fixture, "sync-cases");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-replay-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                GitRepository.Run(root, "init --quiet");
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                var initialSnapshot = Path.Combine(fixture, "snapshot.xml");
                ViewExport.Write(initialSnapshot, root, null);
                SyncBase.Record(root, "project-view", new List<string>());
                var originalBase = GitRun.In(root, "rev-parse refs/cts/base").Output.Trim();
                Assert.Equal(File.ReadAllText(Path.Combine(fixture, "python-base-tree.txt")), GitRun.In(root, "ls-tree -r --full-tree refs/cts/base").Output);
                GitRepository.Run(root, "add -A");
                GitRepository.Run(root, "-c user.name=Fixture -c user.email=fixture@localhost commit -qm \"fixture view\"");

                var main = Path.Combine(root, "project-view", "PLC_Stabur", "Plc Logic", "Application", "MAIN.st");
                File.WriteAllText(main, "PROGRAM MAIN\n// local edit\n");
                var stray = Path.Combine(root, "project-view", "POUs", "Loose.st");
                File.WriteAllText(stray, "FUNCTION Loose\n");
                var result = ExportCommand.WriteToDisk(Path.Combine(cases, "snapshot-without-fscale.xml"), root, "C:\\projects\\demo.project", force);

                var viewRoot = Path.Combine(root, "project-view");
                var files = Directory.GetFiles(viewRoot, "*", SearchOption.AllDirectories)
                    .Select(path => Path.GetRelativePath(viewRoot, path).Replace('\\', '/')).OrderBy(path => path, StringComparer.Ordinal);
                Assert.Equal(File.ReadAllText(Path.Combine(cases, label + "-view.txt")), string.Join("\n", files) + "\n");
                Assert.Equal(File.ReadAllText(Path.Combine(cases, label + "-base-tree.txt")), GitRun.In(root, "ls-tree -r --full-tree refs/cts/base").Output);
                Assert.True(result.BaseRecorded);
                var shape = GitRun.In(root, "show -s --format=%P%n%s refs/cts/base").Output;
                Assert.Equal(originalBase + "\ncts base: export\n", shape);
                var pythonShape = File.ReadAllLines(Path.Combine(cases, label + "-base-shape.txt"));
                Assert.Equal(40, pythonShape[0].Length);
                Assert.Equal("cts base: export", pythonShape[1]);
                if (force)
                {
                    Assert.Empty(result.PendingImport);
                    Assert.Empty(result.KeptOrphans);
                    Assert.Empty(File.ReadAllLines(Path.Combine(cases, "force-pending.txt")));
                    Assert.Empty(File.ReadAllLines(Path.Combine(cases, "force-kept.txt")));
                    Assert.Equal(File.ReadAllText(Path.Combine(cases, "force-overwritten-tree.txt")), GitRun.In(root, "ls-tree -r --full-tree refs/cts/overwritten").Output);
                    Assert.DoesNotContain("Loose.st", File.ReadAllText(Path.Combine(cases, "force-view.txt")));
                }
                else
                {
                    Assert.Equal(File.ReadAllLines(Path.Combine(cases, "no-force-pending.txt")), result.PendingImport);
                    Assert.Equal(File.ReadAllLines(Path.Combine(cases, "no-force-kept.txt")), result.KeptOrphans);
                    Assert.Equal("PROGRAM MAIN\n// local edit\n", File.ReadAllText(main));
                    Assert.Equal("FUNCTION Loose\n", File.ReadAllText(stray));
                }
            }
            finally { Directory.Delete(root, true); }
        }

        [Fact]
        public void FirstExportIntoANewSyncFolderWritesTheView()
        {
            // set-sync-folder commits cds-text-sync.json: HEAD exists, project-view does not yet.
            var fixture = Path.Combine(AppContext.BaseDirectory, "Golden", "ExportFixture");
            var root = Path.Combine(Path.GetTempPath(), "cts-export-new-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(root);
            try
            {
                RunGit(root, "init --quiet");
                File.Copy(Path.Combine(fixture, "cds-text-sync.json"), Path.Combine(root, "cds-text-sync.json"));
                RunGit(root, "add -A");
                RunGit(root, "-c user.name=Fixture -c user.email=fixture@localhost commit -qm \"set up the sync folder\"");

                var result = ExportCommand.WriteToDisk(Path.Combine(fixture, "snapshot.xml"), root, "C:\\projects\\demo.project", false);

                Assert.True(result.BaseRecorded);
                Assert.NotEmpty(Directory.GetFiles(Path.Combine(root, "project-view"), "*.st", SearchOption.AllDirectories));
                Assert.Contains("project-view/", RunGit(root, "ls-tree -r --name-only refs/cts/base"));
            }
            finally { Directory.Delete(root, true); }
        }

        static string RunGit(string root, string args) => GitRepository.Run(root, args).Trim();
    }
}
