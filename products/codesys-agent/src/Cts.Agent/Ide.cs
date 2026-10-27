// Reflection facade over the IDE core. The DLL has no compile-time reference to a
// CODESYS assembly: every type is found by name in the AppDomain, so the same file
// runs inside CODESYS (32-bit) and Astra.IDE (64-bit) and a missing member is an
// error reply naming it, not a crash.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Threading;

namespace Cts.Agent
{
    // The other halves: Objects.cs (create/delete/rename/save), Fields.cs, Export.cs,
    // IdeManager.cs (object manager, permissions, online state) and IdeReflection.cs
    // (text parts, errors, reflection).
    internal sealed partial class Ide
    {
        readonly object _engine;
        readonly Type _engineIface, _projectsIface, _projectIface;
        readonly Type _objectManagerIface, _metaObjectIface, _metaObject7Iface, _projectInfoIface;
        readonly Type _frameIface, _editorViewIface, _editorIface;
        readonly object _objectManager;
        readonly Dictionary<string, MethodInfo> _managerMethods = new Dictionary<string, MethodInfo>();

        // Where the project's Project Information object was last found, so the
        // permission check of every write does not read each object again.
        int _infoHandle = -1;
        Guid _infoGuid;

        public object OnlineManager { get; private set; }
        public Type OnlineManagerType { get; private set; }
        public Type OnlineApplicationType { get; private set; }

        // The modal sniffer's snapshot, set by AgentHost.  Every UI call checks
        // it before it starts and refuses to run while a dialog is up (UiCall).
        public ModalState Modal { get; set; }

        // The live confirm step, set by AgentHost.  UiCall asks it once before a
        // refusal based on the cached snapshot, so the first command after a
        // dialog closes is not refused on a stale reading.
        public IModalProbe Probe { get; set; }

        public Ide()
        {
            _engineIface = FindType("_3S.CoDeSys.Core.IEngine");
            _projectsIface = FindType("_3S.CoDeSys.Core.IProjects");
            _projectIface = FindType("_3S.CoDeSys.Core.IProject");
            _objectManagerIface = FindType("_3S.CoDeSys.Core.Objects.IObjectManager");
            _metaObjectIface = FindType("_3S.CoDeSys.Core.Objects.IMetaObject");
            // Absent before V3.5 SP17: TypeOf then reads the object's TypeGuid attribute.
            _metaObject7Iface = FindTypeOrNull("_3S.CoDeSys.Core.Objects.IMetaObject7");
            _projectInfoIface = FindType("_3S.CoDeSys.ProjectInfoObject.IProjectInfoObject");
            _frameIface = FindType("_3S.CoDeSys.Core.Views.IFrame");
            _editorViewIface = FindType("_3S.CoDeSys.Core.Views.IEditorView");
            _editorIface = FindType("_3S.CoDeSys.Core.Objects.IEditor");
            OnlineManagerType = FindType("_3S.CoDeSys.Core.Online.IOnlineManager");
            OnlineApplicationType = FindType("_3S.CoDeSys.Core.Online.IOnlineApplication");
            _engine = SystemInstance("_3S.CoDeSys.Core.IEngine");
            _objectManager = SystemInstance("_3S.CoDeSys.Core.Objects.IObjectManager");
            OnlineManager = SystemInstance("_3S.CoDeSys.Core.Online.IOnlineManager");
        }

        // The IEngine system instance, for `dev.reflect` root "engine".
        public object Engine { get { return _engine; } }

        public object ObjectManager { get { return _objectManager; } }
        public Type ObjectManagerType { get { return _objectManagerIface; } }

        // Set by AgentHost: a write method's events are cts's own, not the user's.
        public ObjectJournal Journal { get; set; }

        // ---- UI thread

        // Queues `action` on the UI thread and returns at once (InvokeInPrimaryThread
        // with bAsync).  UiCall waits for it with a deadline and marks a call it gave
        // up on abandoned, so a UI thread that never reaches the queue costs no
        // thread: a synchronous invoke held a pool thread per call, and once a
        // stuck download had left sixteen of them waiting, the agent refused
        // every later call until the IDE was restarted.
        void Post(Action action)
        {
            _engineIface.GetMethod("InvokeInPrimaryThread").Invoke(_engine, new object[] { action, new object[0], true });
        }

        // The project file the request being answered began with (its
        // `project_path`), or null; set before each handler runs.
        public readonly AsyncLocal<string> ExpectedProject = new AsyncLocal<string>();

        public T OnUi<T>(string what, int timeoutMs, Func<T> fn)
        {
            // Checked on the UI thread right before the work: another project
            // opened since the command began is refused, not written to.
            var expected = ExpectedProject.Value;
            if (expected != null)
            {
                var work = fn;
                fn = () => { CheckProject(expected); return work(); };
            }
            var journal = Journal;
            if (journal != null && ObjectJournal.IsWrite(what))
            {
                var write = fn;
                fn = () => { using (journal.Own()) return write(); };
            }
            if (OpenEditors.CommitFirst(what))
            {
                // Outside Own: what the editors give is the user's edit.
                var call = fn;
                fn = () => { CommitEditors(); return call(); };
            }
            return UiCall.Run(Post, fn, timeoutMs, what, Modal, StartTimeout.FinishBackstopMs, Probe);
        }

        void CheckProject(string expected)
        {
            var primary = PrimaryProject();
            if (primary == null) return;
            var path = (string)Prop(_projectIface, primary, "Path");
            if (!string.Equals(path, expected, StringComparison.OrdinalIgnoreCase))
                throw new ProtocolException(ErrorCodes.ProjectChanged, "the IDE has " + path + " open now, not " + expected
                    + " that the command began with; nothing was done");
        }

        // Every open editor gives its object the text it holds (see OpenEditors).
        // An IDE without a window has no editors; an editor that cannot give
        // its text keeps it, and the method still runs on what the object holds.
        void CommitEditors()
        {
            var frameProp = FindProperty(_engine.GetType(), "Frame");
            var frame = frameProp == null ? null : Value(frameProp, _engine);
            if (frame == null) return;
            var views = NeedMethod(_frameIface, "GetEditorViews", Type.EmptyTypes, "IFrame.GetEditorViews not found")
                .Invoke(frame, null) as System.Collections.IEnumerable;
            if (views == null) return;
            var save = NeedMethod(_editorIface, "Save", new[] { typeof(bool) }, "IEditor.Save not found");
            foreach (var view in views)
            {
                try
                {
                    var editor = Prop(_editorViewIface, view, "Editor");
                    if (editor != null) save.Invoke(editor, new object[] { true });
                }
                catch (TargetInvocationException) { }
            }
        }

        // The name of each object, or null for one the project no longer has.
        public Dictionary<Guid, string> NamesOf(IEnumerable<Guid> guids)
        {
            var handle = ProjectHandle();
            var names = new Dictionary<Guid, string>();
            foreach (var guid in guids)
            {
                try
                {
                    var meta = ReadMeta(handle, guid);
                    names[guid] = meta == null ? null : NameOf(meta);
                }
                catch { names[guid] = null; }
            }
            return names;
        }

        // Every object's name in the open project, for the problem report to leave out.
        public IEnumerable<string> ObjectNames() => NamesOf(AllGuids(ProjectHandle())).Values.Where(name => name != null);

        // Each object's declaration and implementation as one string, for telling
        // whether it changed; an object with neither, or not readable, is left out.
        public Dictionary<Guid, string> TextsOf(IEnumerable<Guid> guids)
        {
            var handle = ProjectHandle();
            var texts = new Dictionary<Guid, string>();
            foreach (var guid in guids)
            {
                try
                {
                    var meta = ReadMeta(handle, guid);
                    if (meta == null) continue;
                    var obj = Prop(_metaObjectIface, meta, "Object");
                    var declaration = PartText(obj, "Interface");
                    var implementation = PartText(obj, "Implementation");
                    if (declaration != null || implementation != null) texts[guid] = declaration + "\0" + implementation;
                }
                catch { }
            }
            return texts;
        }

        // Whether the object is a task's call entry (see TaskCallType); false
        // when it cannot be read.
        public bool IsTaskCall(Guid guid)
        {
            try
            {
                var meta = ReadMeta(ProjectHandle(), guid);
                return meta != null && TypeOf(meta) == TaskCallType;
            }
            catch { return false; }
        }

        // Runs `fn` on the UI thread with no modal guard.  For the calls that
        // must answer even while a dialog is open: `state`/`hello` (a blocked
        // IDE has to still look alive) and `dialog.answer` (it has to run inside
        // the dialog's own modal loop).
        //
        // The finish budget is short on purpose: these are diagnostics that have
        // to come back, so a UI thread that started them and went away is
        // reported as `timeout` after ten seconds rather than hanging the caller.
        public T OnUiUnguarded<T>(string what, int timeoutMs, Func<T> fn)
        {
            return UiCall.Run(Post, fn, timeoutMs, what, null, StartTimeout.DefaultMs);
        }

        // ---- reads (call from inside OnUi)

        // `state` / `hello`: whether a project is open, its file and sync folder.
        public Dictionary<string, object> ProjectState()
        {
            var primary = PrimaryProject();
            var info = new Dictionary<string, object> { { "open", primary != null } };
            if (primary == null) return info;
            var path = (string)Prop(_projectIface, primary, "Path");
            info["path"] = path;
            AddSyncFolder(info, primary, path);
            return info;
        }

        // The project's id and its sync folder on this machine; without the
        // folder, the one `cts set-sync-folder` would offer.
        void AddSyncFolder(Dictionary<string, object> info, object project, string path)
        {
            var projectInfo = FindProjectInfo(Handle(project));
            if (projectInfo == null) return;
            ProjectInfo.AddSyncFolder(info, ProjectText(projectInfo, ProjectInfo.IdProperty), path, ProjectInfo.RegistryPath());
            var source = ProjectText(projectInfo, ProjectInfo.SourceProperty);
            if (source.Length > 0) info["source"] = source;
            if (!info.ContainsKey("sync_folder"))
                info["suggested_sync_folder"] = ProjectInfo.Suggested(path);
        }

        // `project.status`: what `cts status` reports of the IDE -- the open
        // project's file and sync folder, whether it has unsaved changes, and
        // whether an application is logged in.
        public Dictionary<string, object> ProjectStatus()
        {
            var primary = PrimaryProject();
            var status = new Dictionary<string, object> { { "open", primary != null } };
            if (primary == null) return status;
            var path = Convert.ToString(Prop(_projectIface, primary, "Path"));
            status["path"] = path;
            status["unsaved_changes"] = Prop(_projectIface, primary, "Dirty");
            AddSyncFolder(status, primary, path);
            status["plc"] = OnlineStatus(Handle(primary));
            return status;
        }

        // `online` true while an application is logged in, false when none
        // is, null when the IDE cannot say; the first logged-in application's
        // name and state (`run`, `stop`) with it.
        Dictionary<string, object> OnlineStatus(int handle)
        {
            var plc = new Dictionary<string, object> { { "online", null } };
            object[] applications;
            try { applications = LoggedInApplications(); }
            catch (ProtocolException e) { plc["error"] = e.Message; return plc; }
            plc["online"] = applications.Length > 0;
            if (applications.Length == 0) return plc;
            var app = applications[0];
            var state = Convert.ToString(Prop(OnlineApplicationType, app, "ApplicationState")).ToLowerInvariant();
            plc["application_state"] = state;
            plc["running"] = state == "run";
            var guid = Prop(OnlineApplicationType, app, "ApplicationGuid");
            if (guid is Guid) plc["application"] = NameOf(ReadMeta(handle, (Guid)guid));
            return plc;
        }

        public Dictionary<string, object> Tree(int depth)
        {
            return ProjectTree.Build(ReadTree(OpenProject()), depth);
        }

        public Dictionary<string, object> FindObjects(string name, string path, string app)
        {
            var handle = ProjectHandle();
            var records = new List<ObjectRecord>();
            foreach (var guid in AllGuids(handle))
            {
                var meta = ReadMeta(handle, guid);
                records.Add(new ObjectRecord { Guid = Id(guid), Name = NameOf(meta), Parent = ParentOf(meta), Type = Id(TypeOf(meta)) });
            }
            return new Dictionary<string, object> { { "matches", ObjectLookup.Match(records, name, path, app) } };
        }

        // The declaration and/or implementation text of one object. A part the
        // object does not have -- a GVL has no implementation, a graphical body
        // (SFC/CFC) has no TextDocument -- is null, never an error.
        public Dictionary<string, object> ReadObjectText(string guidText)
        {
            var guid = ParseObjectGuid(guidText);
            var meta = ObjectMeta(ProjectHandle(), guid, "GetObjectToRead");
            var obj = Prop(_metaObjectIface, meta, "Object");
            return new Dictionary<string, object>
            {
                { "guid", Id(guid) },
                { "name", NameOf(meta) },
                { "type", Id(TypeOf(meta)) },
                { "timestamp", TimeStamp(meta) },
                { "declaration", PartText(obj, "Interface") },
                { "implementation", PartText(obj, "Implementation") },
            };
        }

        // The text of every object that has one, or of the named guids.  Reuses
        // PartText, so the shape of a record is the one `objects.text` answers;
        // an object whose Interface and Implementation are both absent (a
        // graphical POU, a task, a device) is not a text object and is skipped.
        public Dictionary<string, object> ReadObjectsText(string[] guids)
        {
            var sw = System.Diagnostics.Stopwatch.StartNew();
            var handle = ProjectHandle();
            var candidates = new List<Guid>();
            if (guids != null)
                foreach (var text in guids) candidates.Add(ParseObjectGuid(text));
            else
                candidates.AddRange(AllGuids(handle));
            var records = new List<object>();
            foreach (var guid in candidates)
            {
                var meta = ReadMeta(handle, guid);
                if (meta == null) throw UnknownObject(guid, null);
                var obj = Prop(_metaObjectIface, meta, "Object");
                var declaration = PartText(obj, "Interface");
                var implementation = PartText(obj, "Implementation");
                if (declaration == null && implementation == null) continue;
                records.Add(new Dictionary<string, object>
                {
                    { "guid", Id(guid) },
                    { "name", NameOf(meta) },
                    { "parent", Id(ParentOf(meta)) },
                    { "type", Id(TypeOf(meta)) },
                    { "timestamp", TimeStamp(meta) },
                    { "declaration", declaration },
                    { "implementation", implementation },
                });
            }
            sw.Stop();
            return new Dictionary<string, object>
            {
                { "objects", records },
                { "count", records.Count },
                { "ms", sw.Elapsed.TotalMilliseconds },
            };
        }

        // Set the named parts verbatim and commit the object. Refused while any
        // application is logged in: CODESYS does not support an offline edit
        // while the project is online.
        public Dictionary<string, object> SetObjectText(string guidText, TextEdit edit)
        {
            var guid = ParseObjectGuid(guidText);
            RefuseWhileOnline();
            RequirePermission("objects.settext");
            var meta = ObjectMeta(ProjectHandle(), guid, "GetObjectToModify");
            var setObject = SetObjectMethod();
            try
            {
                var obj = Prop(_metaObjectIface, meta, "Object");
                // Resolve both parts before writing either, so a refused part leaves the object untouched.
                var declaration = edit.HasDeclaration ? WritableText(obj, "Interface") : null;
                var implementation = edit.HasImplementation ? WritableText(obj, "Implementation") : null;
                if (declaration != null) SetText(declaration, "Interface", edit.Declaration);
                if (implementation != null) SetText(implementation, "Implementation", edit.Implementation);
            }
            catch
            {
                // Check the object back in uncommitted; otherwise it stays "already in use".
                setObject.Invoke(_objectManager, new object[] { meta, false, null });
                throw;
            }
            try { setObject.Invoke(_objectManager, new object[] { meta, true, null }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "SetObject: " + Invocation.Cause(e).Message); }
            return new Dictionary<string, object>
            {
                { "guid", Id(guid) },
                { "timestamp", TimeStamp(meta) },
            };
        }

        public Dictionary<string, object> ApplicationInfo(Guid guid)
        {
            var info = new Dictionary<string, object> { { "guid", guid.ToString() } };
            var app = ApplicationOf(guid);
            if (app == null) { info["known"] = false; return info; }
            info["known"] = true;
            info["logged_in"] = Prop(OnlineApplicationType, app, "IsLoggedIn");
            info["application_state"] = Convert.ToString(Prop(OnlineApplicationType, app, "ApplicationState"));
            info["operating_state"] = Convert.ToString(Prop(OnlineApplicationType, app, "OperatingState"));
            return info;
        }

        // IOnlineManager.GetApplication: the online side of one application.
        public object ApplicationOf(Guid guid)
        {
            return NeedMethod(OnlineManagerType, "GetApplication", new[] { typeof(Guid) }, "IOnlineManager.GetApplication is not present in this IDE")
                .Invoke(OnlineManager, new object[] { guid });
        }

        // The open project's ActiveApplication, or Guid.Empty with no project.
        public Guid ActiveApplication()
        {
            var primary = PrimaryProject();
            if (primary == null) return Guid.Empty;
            var value = Prop(_projectIface, primary, "ActiveApplication");
            return value is Guid ? (Guid)value : Guid.Empty;
        }

    }
}
