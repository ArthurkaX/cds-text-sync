// Files on the PLC the active application's device points at, through its
// online device -- the services the IDE's file view uses (`cts plc`):
//
//   `plc.files {path}` (`ls`): the entries of one directory,
//     IOnlineDevice3.CreateDirFunctionService -> IDirectoryFunctionService.
//   `plc.upload {src, dest}` (`put`): a file of this PC written to the PLC,
//     IOnlineDevice2.CreateFileDownload -> IFileDownload. It replaces a file
//     there: the transfer's bForceOverwrite only says whether to send a file
//     the PLC already holds unchanged, so it is true.
//   `plc.fetch {file, output}` (`get`): a PLC file saved on this PC,
//     IOnlineDevice2.CreateFileUpload -> IFileUpload.
//   `plc.remove {path}`, `plc.mkdir {path}`, `plc.move {from, to}` (`rm`,
//     `mkdir`, `mv`): the directory service's DeleteFile/DeleteDir,
//     CreateDirectory and RenameFile/RenameDir.
//
// A transfer is checked against the CRC32 the PLC computes for its file
// (IDirectoryFunctionService4.GetFileContentInfo), which costs no transfer.
// The IDE names the directions from the PLC's side (download = to the PLC).
// None of them logs in: each connects to the active application's device for
// its run, with a share of the connection, so it works offline and leaves a
// login as it was. The deny list keys are `plc_files`, `plc_fetch` and, for
// every change, `plc_upload` (denied by default).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Threading.Tasks;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        //: How long a listing, or the connection to the device, may take.
        const int PlcFilesMs = 30000;
        //: How long a file transfer may take: a runtime log can be tens of MB.
        const int PlcTransferMs = 300000;

        internal Dictionary<string, object> PlcFiles(string requested, int startMs)
        {
            var path = PlcPaths.Normal("path", requested);
            return Connected(DenyRules.PlcFiles, "plc.files", startMs, online => List(online, path, startMs));
        }

        internal Dictionary<string, object> PlcUpload(string src, string dest, int startMs)
        {
            var source = PlcPaths.HostFile("src", src);
            if (!File.Exists(source))
                throw new ProtocolException(ErrorCodes.BadParams, "No file '" + source + "' on this PC.");
            var target = PlcPaths.Normal("dest", dest);
            if (target == "") target = Path.GetFileName(source);
            var transferIface = FindType("_3S.CoDeSys.Core.Online.IFileDownload");
            object transfer = null;
            var answer = new Dictionary<string, object>
            {
                { "source", source },
                { "destination", target },
                { "size", new FileInfo(source).Length },
            };
            using (var stream = File.OpenRead(source))
                Connected(DenyRules.PlcUpload, "plc.upload", startMs, online =>
                {
                    OnDevice("plc.upload", startMs, PlcTransferMs, "write '" + target + "'", () =>
                    {
                        transfer = NeedMethod(FindType("_3S.CoDeSys.Core.Online.IOnlineDevice2"), "CreateFileDownload", new[] { typeof(Stream), typeof(string) },
                            "IOnlineDevice2.CreateFileDownload is not present in this IDE").Invoke(online, new object[] { stream, target });
                        return (IAsyncResult)transferIface.GetMethod("BeginDownload").Invoke(transfer, new object[] { true, null, null });
                    }, pending => End(transferIface, "EndDownload", transfer, pending, "Cannot write '" + target + "' to the PLC: "));
                    return Check(answer, online, target, PlcPaths.Crc32(source), "The file written to the PLC as '" + target + "' differs from '" + source + "'", startMs);
                });
            return answer;
        }

        // Into a file beside `output` first, so a failed read leaves an
        // existing `output` as it was.  The transfer writes to the stream and
        // reads it back, and needs the host path besides.
        internal Dictionary<string, object> PlcFetch(string file, string output, int startMs)
        {
            var source = PlcPaths.Normal("file", file);
            if (source == "")
                throw new ProtocolException(ErrorCodes.BadParams, "parameter 'file' must name a file on the PLC");
            var target = PlcPaths.HostFile("output", output);
            var part = target + ".cts-part";
            var transferIface = FindType("_3S.CoDeSys.Core.Online.IFileUpload");
            object transfer = null;
            var answer = new Dictionary<string, object> { { "file", source }, { "saved_to", target } };
            try
            {
                using (var stream = new FileStream(part, FileMode.Create, FileAccess.ReadWrite, FileShare.ReadWrite | FileShare.Delete))
                    Connected(DenyRules.PlcFetch, "plc.fetch", startMs, online =>
                    {
                        OnDevice("plc.fetch", startMs, PlcTransferMs, "read '" + source + "'", () =>
                        {
                            transfer = NeedMethod(FindType("_3S.CoDeSys.Core.Online.IOnlineDevice2"), "CreateFileUpload", new[] { typeof(Stream), typeof(string) },
                                "IOnlineDevice2.CreateFileUpload is not present in this IDE").Invoke(online, new object[] { stream, source });
                            NeedMethod(FindType("_3S.CoDeSys.Core.Online.IFileUpload3"), "SetHostPath", new[] { typeof(string) },
                                "IFileUpload3.SetHostPath is not present in this IDE").Invoke(transfer, new object[] { part });
                            return (IAsyncResult)transferIface.GetMethod("BeginUpload").Invoke(transfer, new object[] { true, null, null });
                        }, pending => End(transferIface, "EndUpload", transfer, pending, "Cannot read '" + source
                            + "' from the PLC ('cts plc ls " + PlcPaths.Parent(source) + "' lists that directory): "));
                        stream.Flush();
                        stream.Position = 0;
                        return Check(answer, online, source, PlcPaths.Crc32(stream), "The copy of '" + source + "' differs from the PLC's file", startMs);
                    });
                SafeFile.Replace(part, target);
            }
            finally
            {
                if (File.Exists(part)) File.Delete(part);
            }
            answer["size"] = new FileInfo(target).Length;
            return answer;
        }

        // A file or a directory removed from the PLC; the device removes
        // only an empty directory, so `recursive` removes what it holds first.
        internal Dictionary<string, object> PlcRemove(string requested, bool recursive, int startMs)
        {
            var path = Named("path", requested);
            return Connected(DenyRules.PlcUpload, "plc.remove", startMs, online =>
            {
                var directory = IsDirectory(online, path, startMs);
                var removed = Remove(online, path, directory, recursive, startMs);
                return new Dictionary<string, object> { { "removed", path }, { "is_directory", directory }, { "entries", removed } };
            });
        }

        // How many entries went, `path` included.
        int Remove(object online, string path, bool directory, bool recursive, int startMs)
        {
            var removed = 0;
            if (directory)
            {
                var entries = ((IEnumerable<object>)List(online, path, startMs)["files"]).Cast<Dictionary<string, object>>().ToList();
                if (entries.Count > 0 && !recursive)
                    throw new ProtocolException(ErrorCodes.BadParams, "The directory '" + path + "' on the PLC holds " + entries.Count
                        + (entries.Count == 1 ? " entry" : " entries") + "; 'cts plc rm --recursive " + path + "' removes it with them.");
                foreach (var entry in entries)
                    removed += Remove(online, path + "/" + entry["name"], (bool)entry["is_directory"], true, startMs);
            }
            var service = DirService(online);
            var iface = FindType("_3S.CoDeSys.Core.Online.IDirectoryFunctionService");
            var kind = directory ? "Dir" : "File";
            OnDevice("plc.remove", startMs, PlcFilesMs, "remove '" + path + "'",
                () => (IAsyncResult)iface.GetMethod("BeginDelete" + kind).Invoke(service, new object[] { null, null, path }),
                pending => End(iface, "EndDelete" + kind, service, pending, "Cannot remove '" + path + "' from the PLC: "));
            return removed + 1;
        }

        internal Dictionary<string, object> PlcMakeDirectory(string requested, int startMs)
        {
            var path = Named("path", requested);
            return Connected(DenyRules.PlcUpload, "plc.mkdir", startMs, online =>
            {
                var service = DirService(online);
                OnUi("plc.mkdir", startMs, () => Ended(() => FindType("_3S.CoDeSys.Core.Online.IDirectoryFunctionService").GetMethod("CreateDirectory")
                    .Invoke(service, new object[] { path }), "Cannot make the directory '" + path + "' on the PLC: "));
                return new Dictionary<string, object> { { "created", path } };
            });
        }

        // A file or a directory given another path on the PLC.
        internal Dictionary<string, object> PlcMove(string from, string to, int startMs)
        {
            var source = Named("from", from);
            var target = Named("to", to);
            return Connected(DenyRules.PlcUpload, "plc.move", startMs, online =>
            {
                var directory = IsDirectory(online, source, startMs);
                var service = DirService(online);
                var iface = FindType("_3S.CoDeSys.Core.Online.IDirectoryFunctionService2");
                var kind = directory ? "Dir" : "File";
                OnDevice("plc.move", startMs, PlcFilesMs, "move '" + source + "'",
                    () => (IAsyncResult)NeedMethod(iface, "BeginRename" + kind, new[] { typeof(AsyncCallback), typeof(object), typeof(string), typeof(string) },
                        "IDirectoryFunctionService2.BeginRename" + kind + " is not present in this IDE").Invoke(service, new object[] { null, null, target, source }),
                    pending => End(iface, "EndRename" + kind, service, pending, "Cannot move '" + source + "' to '" + target + "' on the PLC: "));
                return new Dictionary<string, object> { { "from", source }, { "to", target }, { "is_directory", directory } };
            });
        }

        static string Named(string name, string value)
        {
            var path = PlcPaths.Normal(name, value);
            if (path == "")
                throw new ProtocolException(ErrorCodes.BadParams, "parameter '" + name + "' must name a file or a directory on the PLC, not its root");
            return path;
        }

        object DirService(object online)
        {
            return NeedMethod(FindType("_3S.CoDeSys.Core.Online.IOnlineDevice3"), "CreateDirFunctionService", Type.EmptyTypes,
                "IOnlineDevice3.CreateDirFunctionService is not present in this IDE").Invoke(online, null);
        }

        Dictionary<string, object> List(object online, string path, int startMs)
        {
            var serviceIface = FindType("_3S.CoDeSys.Core.Online.IDirectoryFunctionService");
            object service = null;
            return OnDevice("plc.files", startMs, PlcFilesMs, "list '" + path + "'", () =>
            {
                service = DirService(online);
                return (IAsyncResult)serviceIface.GetMethod("BeginGetDirectoryInfos").Invoke(service, new object[] { null, null, path, true });
            }, pending => Listing(serviceIface, service, pending, path));
        }

        // Whether `path` is a directory, from its parent's listing; a path the
        // PLC lacks fails.
        bool IsDirectory(object online, string path, int startMs)
        {
            var parent = PlcPaths.Parent(path);
            var name = path.Substring(parent == "." ? 0 : parent.Length + 1);
            var entry = ((IEnumerable<object>)List(online, PlcPaths.Normal("path", parent), startMs)["files"]).Cast<Dictionary<string, object>>()
                .FirstOrDefault(e => string.Equals((string)e["name"], name, StringComparison.Ordinal));
            if (entry == null)
                throw new ProtocolException(ErrorCodes.BadParams, "No '" + path + "' on the PLC ('cts plc ls " + parent + "' lists that directory).");
            return (bool)entry["is_directory"];
        }

        // `answer` with the CRC32 of the PLC's file, which the device computes
        // without a transfer, once it matches `crc`; a device that does not
        // compute it leaves the file unchecked and says why.
        Dictionary<string, object> Check(Dictionary<string, object> answer, object online, string file, uint crc, string differs, int startMs)
        {
            var iface = FindTypeOrNull("_3S.CoDeSys.Core.Online.IDirectoryFunctionService4");
            var service = DirService(online);
            if (iface == null || !iface.IsInstanceOfType(service))
            {
                answer["unchecked"] = "this IDE cannot ask the PLC for a file's CRC";
                return answer;
            }
            object info;
            try
            {
                info = OnDevice("plc.crc", startMs, PlcFilesMs, "compute the CRC of '" + file + "'",
                    () => (IAsyncResult)iface.GetMethod("BeginGetFileContentInfo").Invoke(service, new object[] { null, null, file }),
                    pending => Ended(() => iface.GetMethod("EndGetFileContentInfo").Invoke(service, new object[] { pending }), ""));
            }
            catch (ProtocolException e)
            {
                answer["unchecked"] = "the PLC did not give the file's CRC: " + e.Message;
                return answer;
            }
            var plc = (uint)Prop(FindType("_3S.CoDeSys.Core.Online.IFileContentInfo"), info, "CRCCheckSum");
            if (plc != crc)
                throw new ProtocolException(ErrorCodes.Internal, differs + ": CRC32 " + PlcPaths.Hex(plc) + " on the PLC, " + PlcPaths.Hex(crc) + " here.");
            answer["crc32"] = PlcPaths.Hex(crc);
            return answer;
        }

        // Begin on the UI thread, wait off it, End on it again: the device
        // services complete through the UI thread, so an End waiting on it
        // there never returns.
        T OnDevice<T>(string what, int startMs, int waitMs, string doing, Func<IAsyncResult> begin, Func<IAsyncResult, T> end)
        {
            var pending = OnUi(what, startMs, begin);
            if (!pending.AsyncWaitHandle.WaitOne(waitMs))
                throw new ProtocolException(ErrorCodes.Internal, "The PLC did not " + doing + " within " + waitMs / 1000 + " s.");
            return OnUi(what, startMs, () => end(pending));
        }

        //: The owner of this agent's share of a device connection.
        static readonly object DeviceShare = new object();

        // `use` with the online device of the active application's device,
        // once the deny list allows `key`, connected for the run by a share of
        // the connection (IOnlineDevice3.SharedConnect): a login keeps its own.
        T Connected<T>(string key, string what, int startMs, Func<object, T> use)
        {
            var online = OnUi(what, startMs, () =>
            {
                RequireKey(key);
                var device = LoginDevice(ProjectHandle(), FindType("_3S.CoDeSys.DeviceObject.IDeviceObject4"));
                return NeedMethod(OnlineManagerType, "GetOnlineDevice", new[] { typeof(Guid) }, "IOnlineManager.GetOnlineDevice is not present in this IDE")
                    .Invoke(OnlineManager, new object[] { device });
            });
            var shared = FindType("_3S.CoDeSys.Core.Online.IOnlineDevice3");
            Share(NeedMethod(shared, "SharedConnect", new[] { typeof(object) }, "IOnlineDevice3.SharedConnect is not present in this IDE"), online, "connect to");
            try { return use(online); }
            finally { Share(shared.GetMethod("SharedDisconnect", new[] { typeof(object) }), online, "close the connection to"); }
        }

        // The share taken or given back off the UI thread, where the call waits
        // for the PLC; its Begin form throws "will (hopefully) be implemented soon".
        static void Share(MethodInfo call, object online, string doing)
        {
            var task = Task.Run(() => call.Invoke(online, new[] { DeviceShare }));
            try
            {
                if (!task.Wait(PlcFilesMs))
                    throw new ProtocolException(ErrorCodes.Unavailable, "Could not " + doing + " the PLC within " + PlcFilesMs / 1000 + " s.");
            }
            catch (AggregateException e) { throw new ProtocolException(ErrorCodes.Unavailable, "Cannot " + doing + " the PLC: " + Invocation.Cause(e.InnerException).Message); }
        }

        static object End(Type transferIface, string name, object transfer, IAsyncResult pending, string failure)
        {
            try { transferIface.GetMethod(name).Invoke(transfer, new object[] { pending }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, failure + Invocation.Cause(e).Message); }
            return null;
        }

        Dictionary<string, object> Listing(Type serviceIface, object service, IAsyncResult pending, string path)
        {
            Array infos;
            try { infos = (Array)serviceIface.GetMethod("EndGetDirectoryInfo").Invoke(service, new object[] { pending }); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams, "Cannot list '" + path + "' on the PLC: " + Invocation.Cause(e).Message);
            }
            var infoIface = FindType("_3S.CoDeSys.Core.Online.IDirInfo");
            var sized = FindType("_3S.CoDeSys.Core.Online.IDirInfo3");
            var names = infos.Cast<object>().Select(info => Convert.ToString(Prop(infoIface, info, "Name"))).ToList();
            PlcPaths.RequireDirectory(path, names);
            var files = new List<Dictionary<string, object>>();
            foreach (var info in infos)
            {
                var name = Convert.ToString(Prop(infoIface, info, "Name"));
                if (PlcPaths.IsSelfOrParent(name)) continue;
                var size = sized.IsInstanceOfType(info) ? Convert.ToInt64(Prop(sized, info, "Size")) : 0L;
                files.Add(PlcPaths.Entry(name, (uint)Prop(infoIface, info, "Flag"), size,
                    (DateTime)Prop(infoIface, info, "Creation"), (DateTime)Prop(infoIface, info, "LastModification")));
            }
            return new Dictionary<string, object>
            {
                { "path", path },
                { "files", files.Cast<object>().ToList() },
                { "count", files.Count },
            };
        }
    }
}
