// `project.export {path}`: the IDE snapshot the engine compares, written here
// from IObjectManager2.ExportObject per object (~5x faster than a
// whole-project export_native on a small project).
// Each structured view is walked node by node; a node's object is exported
// with the CompactXml archive writer, which writes exactly the MetaObject /
// Object pair of an export_native entry, and SnapshotFile wraps it.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        static readonly Guid CompactXmlWriter = new Guid("47B44770-18B8-4f47-92CC-AD8DD6B5B1B9");

        // `guids` null: every object; otherwise only those, each in its place,
        // and an object the views do not hold is left out (`objects` counts).
        public Dictionary<string, object> ExportSnapshot(string path, string[] guids)
        {
            if (string.IsNullOrEmpty(path)) throw new ProtocolException(ErrorCodes.BadParams, "path is required");
            var wanted = guids == null ? null : new HashSet<Guid>(guids.Select(ParseObjectGuid));
            var handle = ProjectHandle();
            var export = ExportObjectMethod();
            var clock = Stopwatch.StartNew();
            var temporary = path + ".part";
            int count;
            try { count = WriteSnapshot(temporary, handle, export, wanted); }
            catch
            {
                // A half-written snapshot is no snapshot: nothing is left behind.
                try { File.Delete(temporary); } catch { }
                throw;
            }
            SafeFile.Replace(temporary, path);
            return new Dictionary<string, object>
            {
                { "path", path }, { "objects", count }, { "ms", clock.ElapsedMilliseconds },
            };
        }

        // Characters of exported XML one `objects.export` reply carries before
        // it stops: a large project's screens are megabytes each, and all of
        // them in one reply run the IDE (a 32-bit process) out of memory.
        const int ExportReplyBudget = 4 * 1024 * 1024;

        // `objects.export {guids, known}`: each object's MetaObject and Object as the
        // members of its export entry (SnapshotFile.AsMember), so a client can
        // compare them with the disk `.xml` and write them into it the way
        // `project.export` lays them out.  Once the reply holds
        // ExportReplyBudget characters the guids not exported yet are answered
        // as `rest`, for the client to ask again.  Each record carries the
        // object's TimeStamp; an object `known` names with its current
        // TimeStamp is answered `unchanged`, without its XML.
        public Dictionary<string, object> ExportObjects(string[] guids, Dictionary<Guid, long> known)
        {
            if (guids == null) throw new ProtocolException(ErrorCodes.BadParams, "guids is required");
            var handle = ProjectHandle();
            var export = ExportObjectMethod();
            var records = new List<Dictionary<string, object>>();
            var size = 0;
            foreach (var text in guids)
            {
                if (size >= ExportReplyBudget)
                    return new Dictionary<string, object> { { "objects", records }, { "rest", guids.Skip(records.Count).ToArray() } };
                var guid = ParseObjectGuid(text);
                var timestamp = TimeStamp(ObjectMeta(handle, guid, "GetObjectToRead"));
                long seen;
                if (known.TryGetValue(guid, out seen) && seen == timestamp)
                {
                    records.Add(new Dictionary<string, object> { { "guid", Id(guid) }, { "timestamp", timestamp }, { "unchanged", true } });
                    continue;
                }
                string meta, obj;
                ExportOne(export, handle, guid, out meta, out obj);
                size += (meta ?? "").Length + (obj ?? "").Length;
                records.Add(new Dictionary<string, object>
                {
                    { "guid", Id(guid) },
                    { "timestamp", timestamp },
                    { "meta", SnapshotFile.AsMember(meta, "MetaObject") },
                    { "object", SnapshotFile.AsMember(obj, "Object") },
                });
            }
            return new Dictionary<string, object> { { "objects", records } };
        }

        int WriteSnapshot(string file, int handle, MethodInfo export, HashSet<Guid> wanted)
        {
            var count = 0;
            using (var writer = new StreamWriter(file, false, new UTF8Encoding(false)))
            {
                SnapshotFile.Begin(writer);
                foreach (var view in StructuredViews(handle))
                {
                    var nodes = wanted == null ? view.Nodes : view.Nodes.Where(n => wanted.Contains(n.Object)).ToList();
                    if (wanted != null && !nodes.Any()) continue;
                    SnapshotFile.BeginView(writer, view.Guid);
                    foreach (var node in nodes)
                    {
                        string meta, obj;
                        ExportOne(export, handle, node.Object, out meta, out obj);
                        SnapshotFile.Entry(writer, new SnapshotEntry
                        {
                            IsRoot = node.IsRoot, Meta = meta, Object = obj,
                            ParentSvNode = node.ParentNode, Path = node.Path, Index = node.Index,
                        });
                        count++;
                    }
                    SnapshotFile.EndView(writer);
                }
                SnapshotFile.End(writer);
            }
            return count;
        }

        public Dictionary<string, object> ProjectSkeleton()
        {
            var handle = ProjectHandle();
            var nodes = new List<Dictionary<string, object>>();
            foreach (var view in StructuredViews(handle))
            foreach (var placement in view.Nodes)
            {
                var meta = ObjectMeta(handle, placement.Object, "GetObjectToRead");
                var parent = ParentOf(meta);
                nodes.Add(new Dictionary<string, object>
                {
                    { "guid", Id(placement.Object) },
                    { "parent_guid", parent == Guid.Empty ? null : Id(parent) },
                    { "name", NameOf(meta) },
                    { "type_guid", Id(TypeOf(meta)) },
                    { "path", placement.Path },
                    { "is_root", placement.IsRoot },
                    { "view_guid", Id(view.Guid) },
                    { "timestamp", TimeStamp(meta) },
                });
            }
            return new Dictionary<string, object> { { "nodes", nodes } };
        }

        // export_native writes two views: POUs (the project-level roots) and
        // Devices (each device's subtree); the one tree the IDE answers is
        // split here.
        static readonly Guid PousView = new Guid("21af5390-2942-461a-bf89-951aaf6999f1");
        static readonly Guid DevicesView = new Guid("d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84");

        sealed class ViewWalk
        {
            public Guid Guid;
            public IEnumerable<SvPlacement> Nodes;
        }

        IEnumerable<ViewWalk> StructuredViews(int handle)
        {
            var view = ReadStructuredView(handle);
            // A "__" root is the IDE's own project-level alias (__VisualizationStyle):
            // the export writes only the application's copy below the device.
            var roots = view.Roots.Where(n => !view.Access.NameOf(n).StartsWith("__", StringComparison.Ordinal)).ToList();
            yield return new ViewWalk { Guid = PousView, Nodes = SvWalk.Walk(roots.Where(n => !view.IsDevice(n)), view.Access) };
            yield return new ViewWalk { Guid = DevicesView, Nodes = SvWalk.Walk(roots.Where(view.IsDevice), view.Access) };
        }

        // IObjectManager2.ExportObject(handle, guid, metaStream, objectStream, writerGuid).
        MethodInfo ExportObjectMethod()
        {
            var iface = FindType("_3S.CoDeSys.Core.Objects.IObjectManager2");
            if (iface != null)
                foreach (var candidate in iface.GetMethods())
                    if (candidate.Name == "ExportObject" && candidate.GetParameters().Length == 5) return candidate;
            throw new ProtocolException(ErrorCodes.Unavailable, "IObjectManager2.ExportObject is not present in this IDE");
        }

        void ExportOne(MethodInfo export, int handle, Guid guid, out string meta, out string obj)
        {
            using (var metaStream = new MemoryStream())
            using (var objStream = new MemoryStream())
            {
                try { export.Invoke(_objectManager, new object[] { handle, guid, metaStream, objStream, CompactXmlWriter }); }
                catch (Exception e)
                {
                    throw new ProtocolException(ErrorCodes.Internal,
                        "ExportObject " + Id(guid) + ": " + Invocation.Cause(e).Message);
                }
                meta = SnapshotFile.Text(metaStream.ToArray());
                obj = SnapshotFile.Text(objStream.ToArray());
            }
        }
    }
}
