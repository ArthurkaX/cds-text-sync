// The Trace CtsTrace of the active application (`cts trace`): the PLC's
// trace manager records its variables in a task's cycle into a ring buffer,
// read back while it runs.  All through the IDE's public interfaces:
//
//   `trace.read`: the trace as the project holds it (ITraceObject6.Record,
//     the ITraceMgrPacket the PLC gets) and, when the PLC holds it too, its
//     state there and how many samples it has;
//   `trace.set {...}`: the trace made (TraceObjectFactory, as the Add Object
//     dialog makes it) or changed through IObjectManager; the PLC keeps the
//     one it has until trace.start;
//   `trace.start`: the PLC's packet deleted first (IDeviceTraceManager.
//     DeletePacket: else the editor asks "The trace already exists on the
//     device. Delete?"), then downloaded by the trace's editor
//     (ITraceEditorController.DownloadTrace resolves the variables' addresses
//     in the logged-in application and starts the trace);
//   `trace.stop`: IDeviceTraceManager.StopPacket; the samples stay until the
//     next start;
//   `trace.samples`: IDeviceTraceManager3.ReadPacket2 of the PLC's own packet:
//     the whole buffer, typed, while the trace runs or after.
//
// A trace is not code: the IDE makes and changes one while online, and the
// application stays unchanged.  The PLC keeps recording with the IDE
// disconnected.  The deny list key of the writes is `trace`.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Threading;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        const string TraceName = TraceRequest.Name;
        static readonly Guid TraceType = new Guid("f7aa3620-8073-4c91-b6ec-86ed9eb60303");
        static readonly Guid TraceEditorFactory = new Guid("591287c5-97f7-4387-8fb8-40f36efd07cc");
        //: How long the PLC may take to take a downloaded trace and start it.
        const int TraceStartMs = 10000;
        const int TracePollMs = 100;

        static Type TraceIface(string name) => FindType("_3S.CoDeSys.TraceObject." + name);
        static Type OnlineIface(string name) => FindType("_3S.CoDeSys.Core.Online." + name);

        internal Dictionary<string, object> TraceRead(int startMs)
        {
            var found = OnUi("trace.read", startMs, () => FindTrace(false));
            if (found == null) return new Dictionary<string, object> { { "exists", false }, { "application", ActiveApplicationName(startMs) } };
            var answer = OnUi("trace.read", startMs, () => Described(found));
            // The project's trace is worth reading with the PLC out of reach.
            try
            {
                Connected(DenyRules.PlcFiles, "trace.read", startMs, online =>
                {
                    var packet = PlcPacket(online, found, startMs);
                    answer["on_plc"] = packet != null;
                    if (packet != null) Status(answer, packet, true);
                    return answer;
                });
            }
            catch (ProtocolException e) when (e.Code == ErrorCodes.Unavailable) { answer["plc_error"] = e.Message; }
            return answer;
        }

        internal Dictionary<string, object> TraceSet(TraceRequest request, int startMs)
        {
            return OnUi("trace.set", startMs, () =>
            {
                RequirePermission("trace.set");
                var found = FindTrace(true);
                var handle = ProjectHandle();
                var meta = ObjectMeta(handle, found.Guid, "GetObjectToModify");
                var setObject = SetObjectMethod();
                try
                {
                    Configure(Prop(_metaObjectIface, meta, "Object"), found, request);
                    setObject.Invoke(_objectManager, new object[] { meta, true, null });
                }
                catch
                {
                    try { setObject.Invoke(_objectManager, new object[] { meta, false, null }); }
                    catch { /* never committed; a release that fails cannot make it worse */ }
                    if (found.Created) try { RemoveObject(handle, found.Guid); } catch { }
                    throw;
                }
                var answer = Described(found);
                answer["created"] = found.Created;
                return answer;
            });
        }

        internal Dictionary<string, object> TraceStart(int startMs)
        {
            var found = OnUi("trace.start", startMs, () =>
            {
                RequirePermission("trace.start");
                return FindTrace(false) ?? throw new ProtocolException(ErrorCodes.BadParams, "the application has no " + TraceName + ": cts trace set VAR ... makes it");
            });
            return Connected(DenyRules.PlcFiles, "trace.start", startMs, online =>
            {
                var manager = TraceManager(online, found, startMs);
                var name = PacketName(found, startMs);
                if (PacketNames(manager).Contains(name)) Invoke(OnlineIface("IDeviceTraceManager"), "DeletePacket", manager, name);
                OnUi("trace.start", startMs, () => { Download(found); return true; });
                var watch = Stopwatch.StartNew();
                object packet = null;
                var state = "";
                while (watch.ElapsedMilliseconds < TraceStartMs)
                {
                    packet = PlcPacket(manager, name);
                    state = packet == null ? "" : Convert.ToString(Prop(OnlineIface("ITraceMgrStatus"), Prop(OnlineIface("ITraceMgrPacket"), packet, "tmsStatus"), "psPacketState"));
                    if (state == "Started") break;
                    if (state == "Enabled" || state == "Stopped")
                        Invoke(OnlineIface("IDeviceTraceManager"), "StartPacket", manager, Prop(OnlineIface("ITraceMgrPacket"), packet, "nPacketHandle"));
                    Thread.Sleep(TracePollMs);
                }
                if (state != "Started")
                    throw new ProtocolException(ErrorCodes.Unavailable, "the PLC did not start the trace within " + TraceStartMs / 1000 + " s (state "
                        + (state == "" ? "none" : state) + "); its reason is in the IDE's messages: cts read-log --category Trace");
                var answer = new Dictionary<string, object> { { "packet", name } };
                Status(answer, packet, false);
                return answer;
            });
        }

        internal Dictionary<string, object> TraceStop(int startMs)
        {
            var found = OnUi("trace.stop", startMs, () =>
            {
                RequirePermission("trace.stop");
                return FindTrace(false) ?? throw new ProtocolException(ErrorCodes.BadParams, "the application has no " + TraceName);
            });
            return Connected(DenyRules.PlcFiles, "trace.stop", startMs, online =>
            {
                var manager = TraceManager(online, found, startMs);
                var packet = PlcPacket(manager, PacketName(found, startMs))
                    ?? throw new ProtocolException(ErrorCodes.BadParams, "the PLC has no " + TraceName + ": cts trace start downloads it");
                Invoke(OnlineIface("IDeviceTraceManager"), "StopPacket", manager, Prop(OnlineIface("ITraceMgrPacket"), packet, "nPacketHandle"));
                var answer = new Dictionary<string, object> { { "packet", PacketName(found, startMs) } };
                Status(answer, ReadPacket(manager, PacketName(found, startMs)), true);
                return answer;
            });
        }

        internal Dictionary<string, object> TraceSamples(int startMs)
        {
            var found = OnUi("trace.samples", startMs, () => FindTrace(false))
                ?? throw new ProtocolException(ErrorCodes.BadParams, "the application has no " + TraceName + ": cts trace set VAR ... makes it");
            return Connected(DenyRules.PlcFetch, "trace.samples", startMs, online =>
            {
                var manager = TraceManager(online, found, startMs);
                var packet = PlcPacket(manager, PacketName(found, startMs))
                    ?? throw new ProtocolException(ErrorCodes.BadParams, "the PLC has no " + TraceName + ": cts trace start downloads it");
                var packetIface = OnlineIface("ITraceMgrPacket");
                var answer = new Dictionary<string, object> { { "packet", Prop(packetIface, packet, "stPacketName") } };
                Status(answer, packet, false);
                answer["microseconds"] = Flags(packet).Contains("Timestamp_US");
                answer["variables"] = ((Array)Prop(packetIface, packet, "Variables")).Cast<object>().Select(Samples).Cast<object>().ToList();
                return answer;
            });
        }

        // ---- the object

        sealed class FoundTrace
        {
            internal Guid Guid, Application;
            internal string ApplicationName;
            internal bool Created;
        }

        // CtsTrace below the active application; made there when *make*,
        // else null when it has none.  On the UI thread.
        FoundTrace FindTrace(bool make)
        {
            var handle = ProjectHandle();
            var application = ActiveApplication();
            if (application == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "the project has no active application; set one in CODESYS (Set Active Application)");
            var applicationMeta = ReadMeta(handle, application);
            var found = new FoundTrace { Application = application, ApplicationName = NameOf(applicationMeta) };
            foreach (var child in (Guid[])Prop(_metaObjectIface, applicationMeta, "SubObjectGuids"))
            {
                var meta = ReadMeta(handle, child);
                if (meta != null && TypeOf(meta) == TraceType && NameOf(meta) == TraceName) { found.Guid = child; return found; }
            }
            if (!make) return null;
            var factory = Factory("_3S.CoDeSys.TraceObject.TraceObject", Prop(_metaObjectIface, applicationMeta, "Object"));
            WarmFactory(factory);
            object created;
            try { created = factory.GetType().GetMethod("Create", Type.EmptyTypes).Invoke(factory, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "create the trace: " + Invocation.Cause(e).Message); }
            found.Guid = Guid.NewGuid();
            found.Created = true;
            try { _objectManagerIface.GetMethod("AddObject").Invoke(_objectManager, new object[] { handle, application, found.Guid, created, TraceName, -1 }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "cannot add " + TraceName + " below " + found.ApplicationName + ": " + Invocation.Cause(e).Message); }
            var objectCreated = factory.GetType().GetMethod("ObjectCreated", new[] { typeof(int), typeof(Guid) });
            if (objectCreated != null) objectCreated.Invoke(factory, new object[] { handle, found.Guid });
            return found;
        }

        string ActiveApplicationName(int startMs) => OnUi("trace.read", startMs, () =>
        {
            var application = ActiveApplication();
            return application == Guid.Empty ? null : NameOf(ReadMeta(ProjectHandle(), application));
        });

        // The trace object's record, the packet the PLC gets.
        static object Record(object trace) => Prop(TraceIface("ITraceObject6"), trace, "Record");

        // What *request* names, written into the object being modified; a
        // new trace gets its names and a buffer of TraceRequest.DefaultSamples.
        void Configure(object trace, FoundTrace found, TraceRequest request)
        {
            var record = Record(trace);
            var packet = OnlineIface("ITraceMgrPacket");
            if (found.Created)
            {
                Assign(TraceIface("ITraceRecord"), record, "stRecordName", TraceName);
                Assign(packet, record, "stApplicationName", found.ApplicationName);
                Assign(packet, record, "stPacketName", found.ApplicationName + "." + TraceName);
                Assign(packet, record, "uiBufferEntries", (uint)TraceRequest.DefaultSamples);
            }
            if (request.Task != null) Assign(packet, record, "stTaskName", request.Task);
            if (string.IsNullOrEmpty((string)Prop(packet, record, "stTaskName")))
                throw new ProtocolException(ErrorCodes.BadParams, "the trace has no task: name it with --task");
            if (request.Every.HasValue) Assign(packet, record, "uiEveryNCycles", (uint)request.Every.Value);
            if (request.Samples.HasValue) Assign(packet, record, "uiBufferEntries", (uint)request.Samples.Value);
            if (request.Variables != null)
            {
                var list = Prop(TraceIface("ITraceRecord"), record, "VariableList");
                var listIface = TraceIface("ITraceVariableList");
                Invoke(listIface, "Clear", list);
                foreach (var name in request.Variables)
                {
                    var variable = Invoke(TraceIface("ITraceObject5"), "CreateTraceVariable", trace);
                    Assign(OnlineIface("ITraceMgrVariable"), variable, "stVariableName", name);
                    listIface.GetMethod("Add").Invoke(list, new[] { variable });
                }
            }
            var packet3 = OnlineIface("ITraceMgrPacket3");
            var triggered = Convert.ToString(Prop(packet, record, "tfTriggerFlags")).Contains("Defined");
            if (request.NoTrigger)
            {
                Assign(packet, record, "tfTriggerFlags", Enum.Parse(OnlineIface("TriggerFlags"), "Undefined"));
                Assign(packet, record, "stTriggerVariable", "");
            }
            if (request.Trigger != null)
            {
                Assign(packet, record, "stTriggerVariable", request.Trigger);
                Assign(packet, record, "tfTriggerFlags", Enum.Parse(OnlineIface("TriggerFlags"), "Defined, UpdatesAfterTrigger"));
                Assign(packet, record, "byTriggerPosition", (byte)0);
                // A first trigger: on a rising edge, half the buffer after it.
                if (request.Edge == null && Convert.ToString(Prop(packet, record, "teTriggerEdge")) == "None")
                    Assign(packet, record, "teTriggerEdge", Enum.Parse(OnlineIface("TriggerEdge"), "Positive"));
                if (request.Post == null && !triggered)
                    Assign(packet3, record, "uiPostTriggerSamples", (uint)Prop(packet, record, "uiBufferEntries") / 2);
            }
            if (request.Edge != null) Assign(packet, record, "teTriggerEdge", Enum.Parse(OnlineIface("TriggerEdge"), request.Edge));
            if (request.Level != null)
            {
                Assign(OnlineIface("ITraceMgrPacket2"), record, "TriggerLevel", request.Level);
                Assign(TraceIface("ITraceRecord"), record, "stTriggerLevel", request.Level);
            }
            if (request.Post.HasValue) Assign(packet3, record, "uiPostTriggerSamples", (uint)request.Post.Value);
            if (request.Condition != null) Assign(TraceIface("ITraceRecord7"), record, "RecordCondition", request.Condition);
            // The IDE's editor draws each variable in a diagram; a new
            // variable gets one as the editor would give it.
            Invoke(TraceIface("ITraceRecord6"), "AssureDiagramConfiguration", record);
        }

        // The trace as the project holds it.  On the UI thread.
        Dictionary<string, object> Described(FoundTrace found)
        {
            var record = Record(Prop(_metaObjectIface, ObjectMeta(ProjectHandle(), found.Guid, "GetObjectToRead"), "Object"));
            var packet = OnlineIface("ITraceMgrPacket");
            var list = Prop(TraceIface("ITraceRecord"), record, "VariableList");
            var count = (int)Prop(TraceIface("ITraceVariableList"), list, "Count");
            var variables = Enumerable.Range(0, count)
                .Select(i => (object)Prop(OnlineIface("ITraceMgrVariable"), TraceIface("ITraceVariableList").GetMethod("get_Item").Invoke(list, new object[] { i }), "stVariableName"))
                .ToList();
            var answer = new Dictionary<string, object>
            {
                { "exists", true },
                { "application", found.ApplicationName },
                { "task", Prop(packet, record, "stTaskName") },
                { "every", (long)(uint)Prop(packet, record, "uiEveryNCycles") },
                { "samples", (long)(uint)Prop(packet, record, "uiBufferEntries") },
                { "variables", variables },
            };
            var trigger = Convert.ToString(Prop(packet, record, "stTriggerVariable"));
            if (Convert.ToString(Prop(packet, record, "tfTriggerFlags")).Contains("Defined") && trigger.Length > 0)
            {
                answer["trigger"] = trigger;
                answer["edge"] = TraceRequest.EdgeName(Convert.ToString(Prop(packet, record, "teTriggerEdge")));
                var level = Convert.ToString(Prop(OnlineIface("ITraceMgrPacket2"), record, "TriggerLevel"));
                if (level.Length > 0) answer["level"] = level;
                answer["post"] = (long)(uint)Prop(OnlineIface("ITraceMgrPacket3"), record, "uiPostTriggerSamples");
            }
            var condition = Convert.ToString(Prop(TraceIface("ITraceRecord7"), record, "RecordCondition"));
            if (condition.Length > 0) answer["condition"] = condition;
            return answer;
        }

        // The trace's editor, opened when it is not (it stays open, as after
        // the IDE's own download), downloads the trace.  On the UI thread.
        void Download(FoundTrace found)
        {
            var handle = ProjectHandle();
            var frame = Prop(_engineIface, _engine, "Frame") ?? throw new ProtocolException(ErrorCodes.Unavailable, "the IDE has no window to open the trace's editor in");
            var controllerIface = FindType("_3S.CoDeSys.TraceEditor.ITraceEditorController");
            var views = (Array)NeedMethod(_frameIface, "GetEditorViews", new[] { typeof(int), typeof(Guid) }, "IFrame.GetEditorViews is not present in this IDE")
                .Invoke(frame, new object[] { handle, found.Guid });
            var editor = views.Cast<object>().FirstOrDefault(controllerIface.IsInstanceOfType);
            if (editor == null)
            {
                var stub = ManagerMethod("GetMetaObjectStub", typeof(int), typeof(Guid)).Invoke(_objectManager, new object[] { handle, found.Guid });
                editor = _frameIface.GetMethod("OpenEditorView").Invoke(frame, new[] { stub, TraceEditorFactory, null });
                if (!controllerIface.IsInstanceOfType(editor))
                    throw new ProtocolException(ErrorCodes.Unavailable, "the trace's editor is not a trace editor in this IDE");
            }
            if (!(bool)Prop(controllerIface, editor, "CanDownloadTrace"))
                throw new ProtocolException(ErrorCodes.BadParams, "the IDE cannot download the trace now: it downloads one to a logged-in application that runs the code it has (cts connect)");
            try { controllerIface.GetMethod("DownloadTrace").Invoke(editor, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Unavailable, "the trace's download: " + Invocation.Cause(e).Message); }
        }

        // ---- the PLC's packet

        object TraceManager(object online, FoundTrace found, int startMs)
        {
            // The trace object makes the variables a read fills.
            var trace = OnUi("trace", startMs, () => Prop(_metaObjectIface, ObjectMeta(ProjectHandle(), found.Guid, "GetObjectToRead"), "Object"));
            return Invoke(OnlineIface("IOnlineDevice6"), "CreateTraceManager", online, trace);
        }

        object PlcPacket(object online, FoundTrace found, int startMs) =>
            PlcPacket(TraceManager(online, found, startMs), PacketName(found, startMs));

        // The PLC's packet *name* with its samples; null when the PLC has none.
        static object PlcPacket(object manager, string name) =>
            PacketNames(manager).Contains(name) ? ReadPacket(manager, name) : null;

        static List<string> PacketNames(object manager) =>
            ((IEnumerable)Invoke(OnlineIface("IDeviceTraceManager"), "ReadPacketList", manager)).Cast<string>().ToList();

        static object ReadPacket(object manager, string name)
        {
            var packet = NeedMethod(OnlineIface("IDeviceTraceManager"), "ReadPacketConfig", new[] { typeof(string) }, "IDeviceTraceManager.ReadPacketConfig is not present in this IDE")
                .Invoke(manager, new object[] { name });
            // Its status comes only with its samples.
            Invoke(OnlineIface("IDeviceTraceManager3"), "ReadPacket2", manager, packet);
            return packet;
        }

        string PacketName(FoundTrace found, int startMs) => OnUi("trace", startMs, () =>
            (string)Prop(OnlineIface("ITraceMgrPacket"), Record(Prop(_metaObjectIface, ObjectMeta(ProjectHandle(), found.Guid, "GetObjectToRead"), "Object")), "stPacketName"));

        static string Flags(object packet) => Convert.ToString(Prop(OnlineIface("ITraceMgrPacket"), packet, "pfPacketFlags"));

        // The packet's state, its trigger's, its times (the PLC's clock, in
        // its resolution) and, when *count*, how many samples it holds.
        static void Status(Dictionary<string, object> answer, object packet, bool count)
        {
            var status = Prop(OnlineIface("ITraceMgrPacket"), packet, "tmsStatus");
            var statusIface = OnlineIface("ITraceMgrStatus");
            answer["state"] = Convert.ToString(Prop(statusIface, status, "psPacketState"));
            answer["trigger_state"] = Convert.ToString(Prop(statusIface, status, "tsTriggerState"));
            answer["start"] = (long)(ulong)Prop(statusIface, status, "ulTraceStartTimeStamp");
            var trigger = (ulong)Prop(statusIface, status, "ulTriggerTimeStamp");
            if (trigger > 0) answer["trigger_at"] = (long)trigger;
            if (!count) return;
            var first = ((Array)Prop(OnlineIface("ITraceMgrPacket"), packet, "Variables")).Cast<object>().FirstOrDefault();
            var stamps = first == null ? null : Prop(OnlineIface("ITraceMgrVariable3"), first, "TimeStampBuffer") as ICollection;
            answer["count"] = (long)(stamps == null ? 0 : stamps.Count);
        }

        // One variable's samples: its type and the times and values, each a
        // number (a BOOL as 0 or 1) or, for a text, a string.
        static Dictionary<string, object> Samples(object variable)
        {
            var info = Prop(OnlineIface("ITraceMgrVariable"), variable, "tmiVariableInfo");
            var stamps = (IEnumerable)Prop(OnlineIface("ITraceMgrVariable3"), variable, "TimeStampBuffer") ?? new ulong[0];
            var values = (IEnumerable)Prop(OnlineIface("ITraceMgrVariable3"), variable, "ValueBuffer") ?? new object[0];
            return new Dictionary<string, object>
            {
                { "name", Prop(OnlineIface("ITraceMgrVariable"), variable, "stVariableName") },
                { "type", info == null ? "" : Convert.ToString(Prop(OnlineIface("ITraceMgrInfo"), info, "tcTypeClass")) },
                { "t", stamps.Cast<object>().Select(stamp => (object)Convert.ToInt64(stamp, CultureInfo.InvariantCulture)).ToList() },
                { "v", values.Cast<object>().Select(SampleValue).ToList() },
            };
        }

        static object SampleValue(object value)
        {
            switch (value)
            {
                case null: return null;
                case bool flag: return flag ? 1L : 0L;
                case float single: return (double)single;
                case double number: return number;
                case ulong big when big > long.MaxValue: return (double)big;
                case string text: return text;
                case IConvertible convertible when !(value is char) && !(value is DateTime): return convertible.ToInt64(CultureInfo.InvariantCulture);
                default: return Convert.ToString(value, CultureInfo.InvariantCulture);
            }
        }

        // ---- reflection

        static object Invoke(Type iface, string name, object target, params object[] args)
        {
            var method = iface.GetMethods().FirstOrDefault(m => m.Name == name && m.GetParameters().Length == args.Length)
                ?? throw new ProtocolException(ErrorCodes.Unavailable, iface.Name + "." + name + " is not present in this IDE");
            try { return method.Invoke(target, args); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Unavailable, iface.Name + "." + name + ": " + Invocation.Cause(e).Message); }
        }

        static void Assign(Type iface, object target, string name, object value)
        {
            var property = iface.GetProperty(name) ?? throw new ProtocolException(ErrorCodes.Unavailable, iface.Name + "." + name + " is not present in this IDE");
            try { property.SetValue(target, value, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, name + ": " + Invocation.Cause(e).Message); }
        }
    }
}
