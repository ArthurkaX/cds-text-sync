using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;

namespace Cts.Agent
{
    // The object manager, the Project Information permissions and the online state.
    internal sealed partial class Ide
    {
        // ---- the object manager

        object PrimaryProject()
        {
            return Prop(_projectsIface, Prop(_engineIface, _engine, "Projects"), "PrimaryProject");
        }

        object OpenProject()
        {
            var project = PrimaryProject();
            if (project == null) throw new ProtocolException(ErrorCodes.BadParams, "No project is open in this IDE");
            return project;
        }

        int Handle(object project)
        {
            return (int)Prop(_projectIface, project, "Handle");
        }

        int ProjectHandle()
        {
            return Handle(OpenProject());
        }

        // IObjectManager.<name>, looked up once; Unavailable when this IDE has none.
        MethodInfo ManagerMethod(string name, params Type[] signature)
        {
            var key = name + "/" + signature.Length;
            lock (_managerMethods)
            {
                MethodInfo method;
                if (!_managerMethods.TryGetValue(key, out method))
                    _managerMethods[key] = method = NeedMethod(_objectManagerIface, name, signature, "IObjectManager." + name + " is not present in this IDE");
                return method;
            }
        }

        object Manager(string name, int handle, Guid guid)
        {
            return ManagerMethod(name, typeof(int), typeof(Guid)).Invoke(_objectManager, new object[] { handle, guid });
        }

        Guid[] AllGuids(int handle)
        {
            return (Guid[])ManagerMethod("GetAllObjects", typeof(int)).Invoke(_objectManager, new object[] { handle });
        }

        // An object the caller knows exists (one of AllGuids, say); null when not.
        object ReadMeta(int handle, Guid guid)
        {
            return Manager("GetObjectToRead", handle, guid);
        }

        // A caller-named object: an unknown guid is bad_params, not a fault.
        object ObjectMeta(int handle, Guid guid, string methodName)
        {
            object meta;
            try { meta = Manager(methodName, handle, guid); }
            catch (Exception e) { throw UnknownObject(guid, e); }
            if (meta == null) throw UnknownObject(guid, null);
            return meta;
        }

        // IObjectManager.SetObject(meta, setAsModified, libraryName): the one
        // commit of every write.
        MethodInfo SetObjectMethod()
        {
            foreach (var candidate in _objectManagerIface.GetMethods())
                if (candidate.Name == "SetObject" && candidate.GetParameters().Length == 3) return candidate;
            throw new ProtocolException(ErrorCodes.Unavailable, "IObjectManager.SetObject is not present in this IDE");
        }

        string NameOf(object meta)
        {
            return Convert.ToString(Prop(_metaObjectIface, meta, "Name"));
        }

        // V3.5 SP20 Patch 1 answers an empty ObjectTypeGuid for a task call;
        // the object's class still carries its type.
        Guid TypeOf(object meta)
        {
            var guid = _metaObject7Iface != null ? (Guid)Prop(_metaObject7Iface, meta, "ObjectTypeGuid") : Guid.Empty;
            return guid != Guid.Empty ? guid : TypeGuidOf(Prop(_metaObjectIface, meta, "Object").GetType());
        }

        // An object class's [TypeGuid], what ObjectTypeGuid answers on V3.5 SP17
        // and later; found by the attribute's name, whatever its namespace.
        static Guid TypeGuidOf(Type type)
        {
            var attribute = type.GetCustomAttributes(true).FirstOrDefault(a => a.GetType().Name == "TypeGuidAttribute")
                ?? throw new ProtocolException(ErrorCodes.Unavailable, "no TypeGuid attribute on " + type.FullName);
            foreach (var property in attribute.GetType().GetProperties())
            {
                var value = property.GetValue(attribute, null);
                if (value is Guid guid) return guid;
                if (value is string text && Guid.TryParse(text, out guid)) return guid;
            }
            throw new ProtocolException(ErrorCodes.Unavailable, "unreadable TypeGuid attribute on " + type.FullName);
        }

        Guid ParentOf(object meta)
        {
            return (Guid)Prop(_metaObjectIface, meta, "ParentObjectGuid");
        }

        // A guid as the protocol writes it (the "D" form is lower case).
        static string Id(Guid guid)
        {
            return guid.ToString("D");
        }

        // The display path of `guid`; GetObjectNamePath is the array ObjectLookup
        // joins with "/", so the `path` matches what objects.find already answers.
        string NamePath(int handle, Guid guid)
        {
            return string.Join("/", (string[])Manager("GetObjectNamePath", handle, guid));
        }

        // The project as the IDE's tree shows it (SvWalk.Tree).
        ProjectNode ReadTree(object project)
        {
            var view = ReadStructuredView(Handle(project));
            var root = new ProjectNode { Name = System.IO.Path.GetFileNameWithoutExtension(Convert.ToString(Prop(_projectIface, project, "Path") ?? "")) };
            foreach (var node in SvWalk.Tree(view.Roots, view.Access)) root.Children.Add(node);
            if (root.Children.Count == 0) throw new ProtocolException(ErrorCodes.Unavailable, "Project contains no root object");
            return root;
        }

        // A task's "call" entries (the POUs it invokes): nodes in the tree, no
        // object of their own in an export.
        static readonly Guid TaskCallType = new Guid("413e2a7d-adb1-4d2c-be29-6ae6e4fab820");

        sealed class StructuredView
        {
            public List<object> DeviceRoots;
            public List<object> PouRoots;
            public SvNodeAccess Access;
            public Func<object, bool> IsDevice;

            public IEnumerable<object> Roots { get { return DeviceRoots.Concat(PouRoots); } }
        }

        // The project's structured views, each tab's roots as its own view
        // shows them, and how to read a node.  The POUs view alone has the
        // POUs tab's folders; the Devices view lists that tab's objects too,
        // flat, so of its roots only a device or a folder of the Devices tab
        // is taken.
        StructuredView ReadStructuredView(int handle)
        {
            var nodeIface = FindType("_3S.CoDeSys.Core.Objects.ISVNode");
            var viewIface = FindType("_3S.CoDeSys.Core.Objects.IStructuredView");
            var stub6Iface = FindTypeOrNull("_3S.CoDeSys.Core.Objects.IMetaObjectStub6");
            var stubIface = FindType("_3S.CoDeSys.Core.Objects.IMetaObjectStub");
            var getStub = NeedMethod(nodeIface, "GetMetaObjectStub", Type.EmptyTypes, "ISVNode.GetMetaObjectStub is not present in this IDE");
            // An empty ObjectTypeGuid (a task call on V3.5 SP20 Patch 1) is read
            // from the stub's ObjectType, as on an IDE without IMetaObjectStub6.
            Func<object, Guid> typeOf = n =>
            {
                var stub = getStub.Invoke(n, null);
                var guid = stub6Iface != null ? (Guid)Prop(stub6Iface, stub, "ObjectTypeGuid") : Guid.Empty;
                if (guid != Guid.Empty) return guid;
                var type = (Type)Prop(stubIface, stub, "ObjectType");
                return type == null ? Guid.Empty : TypeGuidOf(type);
            };
            var getView = ManagerMethod("GetStructuredView", typeof(int), typeof(Guid));
            Func<Guid, List<object>> rootsOf = guid => ((Array)Prop(viewIface, getView.Invoke(_objectManager, new object[] { handle, guid }), "Children")).Cast<object>().ToList();
            Func<object, bool> isDevice = IsDeviceNode;
            Func<object, Guid> objectOf = n => (Guid)Prop(nodeIface, n, "ObjectGuid");
            Func<object, IEnumerable<object>> childrenOf = n => ((Array)Prop(nodeIface, n, "Children")).Cast<object>();
            var folderType = new Guid(ObjectKinds.FolderType);
            // The POUs view lists the objects of an application's folders flat
            // at its top too: of its roots only a folder or an object with no
            // parent object is the tab's own.
            var pouRoots = rootsOf(PousView).Where(n => !isDevice(n)
                && (typeOf(n) == folderType || (Guid)Prop(stubIface, getStub.Invoke(n, null), "ParentObjectGuid") == Guid.Empty)).ToList();
            var onPousTab = new HashSet<Guid>();
            var pending = new Stack<object>(pouRoots);
            while (pending.Count > 0)
            {
                var node = pending.Pop();
                onPousTab.Add(objectOf(node));
                foreach (var child in childrenOf(node)) pending.Push(child);
            }
            return new StructuredView
            {
                DeviceRoots = rootsOf(DevicesView).Where(n => isDevice(n) || typeOf(n) == folderType && !onPousTab.Contains(objectOf(n))).ToList(),
                PouRoots = pouRoots,
                Access = new SvNodeAccess
                {
                    ObjectOf = objectOf,
                    NameOf = n => (string)Prop(nodeIface, n, "Name"),
                    ObjectNameOf = n =>
                    {
                        var stub = getStub.Invoke(n, null);
                        var name = FindProperty(stub.GetType(), "Name");
                        return name == null ? null : Value(name, stub) as string;
                    },
                    ChildrenOf = childrenOf,
                    IndexOf = n => (int)Prop(nodeIface, n, "Index"),
                    TypeOf = typeOf,
                    Skip = n => typeOf(n) == TaskCallType,
                },
                IsDevice = isDevice,
            };
        }

        // ---- the project's Project Information

        // The IProjectInfoObject, or null when the project has none.  The guid
        // it was found under is remembered, so only the first call (or one after
        // the project changed) reads every object.
        object FindProjectInfo(int handle)
        {
            if (handle == _infoHandle)
            {
                try
                {
                    var known = Prop(_metaObjectIface, ReadMeta(handle, _infoGuid), "Object");
                    if (_projectInfoIface.IsInstanceOfType(known)) return known;
                }
                catch { /* gone or a different project under the same handle: look again */ }
            }
            foreach (var guid in AllGuids(handle))
            {
                var value = Prop(_metaObjectIface, ReadMeta(handle, guid), "Object");
                if (!_projectInfoIface.IsInstanceOfType(value)) continue;
                _infoHandle = handle;
                _infoGuid = guid;
                return value;
            }
            return null;
        }

        object ProjectValue(object projectInfo, string key)
        {
            return _projectInfoIface.GetMethod("GetValue").Invoke(projectInfo, new object[] { key });
        }

        // A property as text, "" when the project has none: GetValue on a
        // key that is not there may throw.
        string ProjectText(object projectInfo, string key)
        {
            var keys = (string[])Prop(_projectInfoIface, projectInfo, "Keys");
            return keys.Contains(key) ? Convert.ToString(ProjectValue(projectInfo, key)) ?? "" : "";
        }

        // The project's deny list, for the write `agentMethod` stands for.
        void RequirePermission(string agentMethod)
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.RequireWrite(raw, readable, agentMethod);
        }

        // The deny list and where it lives (`cts permissions`); read-only.
        internal Dictionary<string, object> Permissions()
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            return DenyRules.Describe(raw, readable);
        }

        // The same deny list for a key no project write answers to: a PLC
        // variable write (`write_variable`), a message read (`read_log`).
        internal void RequireKey(string key)
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            DenyRules.Require(raw, readable, key);
        }

        // The deny list in force for the quick window; null when the sync
        // folder's cds-text-sync.json cannot be read.
        internal List<string> DenyList()
        {
            string raw; bool readable;
            DenyConfig(out raw, out readable);
            return DenyRules.DenyList(raw, readable);
        }

        // Switches *key* in the sync folder's deny list (the quick window's
        // Permissions page, a person's choice: no command reaches this) and
        // answers the list now in force.  Written as cts writes the file, so
        // its diff is the change.
        internal List<string> TogglePermission(string key)
        {
            var folder = PermissionsFolder();
            if (folder == "") throw new ProtocolException(ErrorCodes.BadParams, "the project has no sync folder");
            var text = DenyRules.Toggle(ProjectInfo.Settings(folder), key);
            ProjectInfo.SaveSettings(folder, text);
            return DenyRules.DenyList(text, true);
        }

        // The open project's sync folder, "" with no project or none set;
        // throws when the project cannot be read.
        string PermissionsFolder()
        {
            var project = PrimaryProject();
            if (project == null) return "";
            var projectInfo = FindProjectInfo(Handle(project));
            if (projectInfo == null) return "";
            return ProjectInfo.SyncFolder(ProjectText(projectInfo, ProjectInfo.IdProperty),
                Convert.ToString(Prop(_projectIface, project, "Path")), ProjectInfo.RegistryPath());
        }

        // The sync folder's cds-text-sync.json.  ("", true) when there is no
        // project, no sync folder or no file: the built-in defaults are then the
        // deny list, not an error.  ("", false) when the project or the file
        // cannot be read -- the deny list fails closed on that.
        void DenyConfig(out string raw, out bool readable)
        {
            raw = "";
            readable = true;
            string folder;
            try { folder = PermissionsFolder(); }
            catch { readable = false; return; }
            if (folder == "") return;
            try { raw = ProjectInfo.Settings(folder); }
            catch (System.IO.IOException) { readable = false; }
            catch (UnauthorizedAccessException) { readable = false; }
        }

        // ---- online state

        // Any application of the project being logged in means the project must
        // not be edited; IOnlineManager3.GetLoggedInApplications is the only
        // member that answers "is any of them online".
        void RefuseWhileOnline()
        {
            var applications = LoggedInApplications();
            if (applications.Length > 0)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "the project is online (" + applications.Length + " application(s) logged in); disconnect before writing");
        }

        object[] LoggedInApplications()
        {
            MethodInfo getLoggedIn;
            try
            {
                getLoggedIn = DevReflection.ResolveMethod(OnlineManager.GetType(), false,
                    "GetLoggedInApplications", new object[] { false });
            }
            catch (ProtocolException e)
            {
                throw new ProtocolException(ErrorCodes.Unavailable,
                    "cannot tell whether the project is online: " + e.Message);
            }
            object[] applications;
            try { applications = (object[])getLoggedIn.Invoke(OnlineManager, new object[] { false }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Unavailable, "cannot read the online state: " + Invocation.Cause(e).Message); }
            return applications ?? new object[0];
        }
    }
}
