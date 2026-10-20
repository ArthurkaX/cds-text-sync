// `objects.create`, `objects.delete`, `objects.rename`, `objects.move` and `project.save`:
// the writes that add, remove, rename or move whole objects, through the IDE's own
// object factories and object manager.  Every one is refused while an
// application is logged in (except save) and checks the project's deny list.
using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows.Forms;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        // ---- objects.create

        // Creates one object under `parentGuid` through the IDE's object model:
        // the factory is picked by ObjectType full name, Create() makes a detached
        // object, AddObject inserts it (index -1 because an Application parent is
        // not ordered), and the text goes through SetObjectText, so there is
        // exactly one text-write path.  A text write that fails removes the
        // half-made object again, so a caller never sees a nameless object.
        public Dictionary<string, object> CreateObject(ObjectCreate spec)
        {
            RefuseWhileOnline();
            RequirePermission("objects.create");
            var handle = ProjectHandle();
            // The project root has no meta object: its parent is null, and the
            // structured view itself is the node a root folder goes below.
            var parent = spec.AtRoot ? null : ObjectMeta(handle, spec.ParentGuid, "GetObjectToRead");
            var parentObject = parent == null ? null : Prop(_metaObjectIface, parent, "Object");
            var factory = Factory(spec.TypeName, parentObject);
            // A folder, or anything directly below one, is placed through the
            // structured view: a plain AddObject with a folder (or Application)
            // parent lands at the project root instead of inside the folder.
            if (spec.StructuredView.HasValue || spec.Kind == "folder" || parent != null && IsFolder(parent))
                return CreateInFolder(handle, factory, spec);
            if (!Accepts(factory, parentObject))
            {
                // A METHOD below an interface needs the interface-method factory;
                // every other refusal is a caller mistake.
                if (spec.Kind != "method" || parent == null) throw BadParent(spec, parent);
                factory = Factory(ObjectKinds.InterfaceMethodType, parentObject);
                if (!Accepts(factory, parentObject)) throw BadParent(spec, parent);
            }
            object created;
            string[] batchArguments = null;
            try
            {
                WarmFactory(factory);
                // A PROPERTY's factory makes its Get/Set accessors only through
                // the batch-argument route; the zero-argument Create() leaves a
                // property with no accessors (and crashed the IDE once, so it is
                // never used for one).
                if (spec.Kind == "property") batchArguments = PropertyArguments(factory, spec.Name, spec.Declaration);
                created = batchArguments == null
                    ? factory.GetType().GetMethod("Create", Type.EmptyTypes).Invoke(factory, null)
                    : factory.GetType().GetMethod("Create", new[] { typeof(string[]) }).Invoke(factory, new object[] { batchArguments });
            }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "create " + spec.Kind + ": " + Invocation.Cause(e).Message); }
            var guid = Guid.NewGuid();
            var add = _objectManagerIface.GetMethod("AddObject");
            if (add == null) throw new ProtocolException(ErrorCodes.Unavailable, "IObjectManager.AddObject is not present in this IDE");
            try
            {
                add.Invoke(_objectManager, new object[] { handle, spec.ParentGuid, guid, created, spec.Name, -1 });
            }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot create '" + spec.Name + "' " + Where(parent) + ": " + Invocation.Cause(e).Message);
            }
            if (spec.Kind == "property")
            {
                // The factory makes the accessors only after ObjectCreated; the
                // caller's bodies are then written into them, and their identity
                // is handed back with the property's, so the caller can write
                // each one's declaration too.
                var result = FinishCreate(handle, guid, null);
                try
                {
                    InvokeObjectCreated(factory, handle, guid, batchArguments);
                    result["accessors"] = WriteAccessors(handle, guid, spec.Accessors);
                }
                catch
                {
                    // Same rule as a failed text write: no half-made
                    // property (or accessor without its body) stays behind.
                    try { RemoveObject(handle, guid); } catch { }
                    throw;
                }
                return result;
            }
            return FinishCreate(handle, guid, spec.Edit());
        }

        // Whether the meta object is a folder (its SV node, not its
        // ParentObjectGuid, says where its children live).
        bool IsFolder(object meta)
        {
            return Id(TypeOf(meta)) == ObjectKinds.FolderType;
        }

        // Creates one object inside a structured-view node: the folder itself
        // below its container's node, or an object below its folder's node,
        // in the caller's view or the one that holds the parent.  A root
        // folder goes to the POUs tab.  A property cannot go this way (its
        // factory needs the batch-argument route and its parent is always a
        // POU, never a folder).
        Dictionary<string, object> CreateInFolder(int handle, object factory, ObjectCreate spec)
        {
            if (spec.Kind == "property")
                throw new ProtocolException(ErrorCodes.BadParams,
                    "a property cannot be created through a structured view");
            var node = spec.AtRoot ? StructuredViewOf(handle, spec.StructuredView ?? PousView)
                : spec.StructuredView.HasValue ? SvParentNode(handle, spec.StructuredView.Value, spec.ParentGuid)
                : SvNode(handle, spec.ParentGuid, out _);
            WarmFactory(factory);
            object created;
            try
            {
                created = factory.GetType().GetMethod("Create", Type.EmptyTypes).Invoke(factory, null);
            }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "create " + spec.Kind + ": " + Invocation.Cause(e).Message); }
            Guid placed;
            try
            {
                if (spec.AtRoot) placed = SvAddAtTop(node, created, spec.Name);
                else SvAddObject(node, created, spec.Name, Guid.NewGuid(), out placed);
                // The folder factory wires the folder into the view only here.
                if (spec.Kind == "folder") InvokeFolderCreated(factory, handle, placed);
            }
            catch (ProtocolException) { throw; }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "create " + spec.Kind + ": " + Invocation.Cause(e).Message); }
            return FinishCreate(handle, placed, spec.Edit());
        }

        // The answer every create returns: the new object's identity, then the
        // caller's text through the one text-write path; a failed write removes
        // the half-made object again, so no nameless object stays behind.
        Dictionary<string, object> FinishCreate(int handle, Guid guid, TextEdit edit)
        {
            var meta = ObjectMeta(handle, guid, "GetObjectToRead");
            var result = new Dictionary<string, object>
            {
                { "guid", Id(guid) },
                { "type_guid", Id(TypeOf(meta)) },
                // The object's own parent: below a folder that is the folder's
                // container, since a folder is a structured-view node only.
                { "parent_guid", Id(ParentOf(meta)) },
                { "path", NamePath(handle, guid) },
            };
            if (edit != null)
            {
                try { SetObjectText(Id(guid), edit); }
                catch
                {
                    try { RemoveObject(handle, guid); } catch { }
                    throw;
                }
            }
            return result;
        }

        // The structured-view node new objects are placed below: the folder
        // itself below its container's node, or an object below its folder.
        object SvParentNode(int handle, Guid svGuid, Guid nodeGuid)
        {
            var sv = StructuredViewOf(handle, svGuid);
            var getNode = NeedMethod(sv.GetType(), "GetNode", new[] { typeof(Guid) }, "IStructuredView.GetNode is not present in this IDE");
            object node;
            try { node = getNode.Invoke(sv, new object[] { nodeGuid }); }
            catch (Exception e) { throw UnknownObject(nodeGuid, e); }
            if (node == null) throw UnknownObject(nodeGuid, null);
            return node;
        }

        // The node of `nodeGuid` in the view of the tab that shows it.  A view
        // answers a node for objects of the other tab too, so the Devices tab
        // is the one whose node has a device at the top of its branch; a
        // folder is a node only (no parent object to follow).
        object SvNode(int handle, Guid nodeGuid, out Guid view)
        {
            var nodeIface = FindType("_3S.CoDeSys.Core.Objects.ISVNode");
            var devices = StructuredViewOf(handle, DevicesView);
            object top = null;
            try
            {
                var node = NeedMethod(devices.GetType(), "GetNode", new[] { typeof(Guid) }, "IStructuredView.GetNode is not present in this IDE").Invoke(devices, new object[] { nodeGuid });
                for (; node != null; node = Prop(nodeIface, node, "Parent")) top = node;
            }
            catch (System.Reflection.TargetInvocationException) { /* not a node of the Devices view */ }
            view = top != null && IsDeviceNode(top) ? DevicesView : PousView;
            return SvParentNode(handle, view, nodeGuid);
        }

        bool IsDeviceNode(object node)
        {
            return ((Type)Prop(FindType("_3S.CoDeSys.Core.Objects.ISVNode"), node, "ObjectType")).GetInterfaces().Any(i => i.Name == "IDeviceObject");
        }

        object StructuredViewOf(int handle, Guid svGuid)
        {
            var getView = ManagerMethod("GetStructuredView", typeof(int), typeof(Guid));
            try { return getView.Invoke(_objectManager, new object[] { handle, svGuid }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "unknown structured view " + Id(svGuid) + ": " + Invocation.Cause(e).Message); }
        }

        // The node's 5-argument AddObject (ISVNode2, out guid): the 4-argument
        // form exists live too, but this is what runs here (probed live).
        void SvAddObject(object node, object obj, string name, Guid guid, out Guid placed)
        {
            var add = NeedMethod(node.GetType(), "AddObject",
                new[] { typeof(Guid), FindType("_3S.CoDeSys.Core.Objects.IObject"), typeof(string), typeof(int), typeof(Guid).MakeByRefType() },
                "ISVNode.AddObject is not present in this IDE");
            var args = new object[] { guid, obj, name, -1, Guid.Empty };
            try { add.Invoke(node, args); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "cannot create '" + name + "' here: " + Invocation.Cause(e).Message); }
            if (!(args[4] is Guid) || (Guid)args[4] == Guid.Empty)
                throw new ProtocolException(ErrorCodes.Internal, "AddObject did not answer the new guid of '" + name + "'");
            placed = (Guid)args[4];
        }

        // The view's own 3-argument AddObject puts an object at its top (a
        // view has no 5-argument form); the guid passed in is the new one.
        Guid SvAddAtTop(object view, object obj, string name)
        {
            var add = NeedMethod(view.GetType(), "AddObject",
                new[] { typeof(Guid), FindType("_3S.CoDeSys.Core.Objects.IObject"), typeof(string) },
                "IStructuredView.AddObject is not present in this IDE");
            var guid = Guid.NewGuid();
            try { add.Invoke(view, new object[] { guid, obj, name }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "cannot create '" + name + "' at the project root: " + Invocation.Cause(e).Message); }
            return guid;
        }

        // The folder factory's 2-argument ObjectCreated, which wires the new
        // folder into the structured view.
        void InvokeFolderCreated(object factory, int handle, Guid guid)
        {
            var method = NeedMethod(factory.GetType(), "ObjectCreated", new[] { typeof(int), typeof(Guid) }, "ObjectCreated(int, Guid) is not present on this factory");
            try { method.Invoke(factory, new object[] { handle, guid }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "ObjectCreated: " + Invocation.Cause(e).Message); }
        }

        // The PROPERTY factory's batch arguments, with the declaration replaced by
        // the caller's `PROPERTY <name> : <type>` text (the factory's own default
        // is a placeholder).  The layout comes from the factory's wizard page, so
        // no language GUID or argument order is hard-coded here.
        string[] PropertyArguments(object factory, string name, string declaration)
        {
            var page = WizardPage(factory);
            if (page == null) throw new ProtocolException(ErrorCodes.Unavailable, "the property factory has no wizard page");
            var fromPage = NeedMethod(factory.GetType(), "CreateBatchArgumentsFromWizardPage", new[] { page.GetType() },
                "CreateBatchArgumentsFromWizardPage is not present on the property factory");
            var arguments = (string[])fromPage.Invoke(factory, new object[] { page });
            var header = declaration != null && declaration.TrimStart().StartsWith("PROPERTY", StringComparison.OrdinalIgnoreCase)
                ? declaration
                : "PROPERTY " + name + " : ";
            for (var i = 0; i < arguments.Length; i++)
                if (arguments[i] != null && arguments[i].TrimStart().StartsWith("PROPERTY", StringComparison.OrdinalIgnoreCase))
                    arguments[i] = header;
            return arguments;
        }

        // The Get/Set children the property factory just made, their bodies written
        // from `bodies`; the list carries each one's identity for the caller.
        List<object> WriteAccessors(int handle, Guid propertyGuid, IDictionary<string, string> bodies)
        {
            var accessors = new List<object>();
            var property = ObjectMeta(handle, propertyGuid, "GetObjectToRead");
            foreach (var childGuid in (Guid[])Prop(_metaObjectIface, property, "SubObjectGuids"))
            {
                var childMeta = ObjectMeta(handle, childGuid, "GetObjectToRead");
                var name = NameOf(childMeta);
                if (name != "Get" && name != "Set") continue;
                string body;
                if (bodies.TryGetValue(name, out body))
                    SetObjectText(Id(childGuid), TextEdit.Of(true, "", true, body));
                accessors.Add(new Dictionary<string, object>
                {
                    { "name", name },
                    { "guid", Id(childGuid) },
                    { "type_guid", Id(TypeOf(childMeta)) },
                    { "path", NamePath(handle, childGuid) },
                });
            }
            return accessors;
        }

        // Call the factory's 3-argument ObjectCreated, which makes a property's
        // Get/Set accessors; the parameter types select the overload (there is a
        // 2-argument form too).
        void InvokeObjectCreated(object factory, int handle, Guid guid, string[] batchArguments)
        {
            var method = NeedMethod(factory.GetType(), "ObjectCreated", new[] { typeof(int), typeof(Guid), typeof(string[]) },
                "ObjectCreated(int, Guid, string[]) is not present on this factory");
            try { method.Invoke(factory, new object[] { handle, guid, batchArguments }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "ObjectCreated: " + Invocation.Cause(e).Message); }
        }

        // A POU, a method and an action factory build their object from a wizard
        // page, and Create() throws ArgumentNullException on a factory whose page
        // control does not exist yet -- one Add Object dialog never opened this
        // session.  Creating the control is enough, and is harmless for a kind
        // that needs no page (a global variable list); its language list is then
        // set to Structured Text.
        void WarmFactory(object factory)
        {
            var page = WizardPage(factory);
            var createControl = page == null ? null : page.GetType().GetMethod("CreateControl", Type.EmptyTypes);
            if (createControl == null) return;
            try
            {
                createControl.Invoke(page, null);
                var control = page as Control;
                if (control != null) ChooseStructuredText(control);
            }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "wizard page: " + Invocation.Cause(e).Message); }
        }

        // The page starts on the language a person last chose in an Add Object
        // dialog, the first of the list (CFC) in a fresh profile, where a POU
        // has no implementation text to write: every language list on it is
        // set to Structured Text, as a person would choose it.
        static void ChooseStructuredText(Control parent)
        {
            foreach (Control control in parent.Controls)
            {
                var list = control as ComboBox;
                if (list != null)
                    for (var i = 0; i < list.Items.Count; i++)
                    {
                        var guid = FindProperty(list.Items[i].GetType(), "TypeGuidString");
                        if (guid == null || !string.Equals(Convert.ToString(Value(guid, list.Items[i])), ObjectKinds.StructuredText,
                            StringComparison.OrdinalIgnoreCase)) continue;
                        if (list.SelectedIndex != i) list.SelectedIndex = i;
                        break;
                    }
                ChooseStructuredText(control);
            }
        }

        static object WizardPage(object factory)
        {
            var pageProp = FindProperty(factory.GetType(), "WizardPage");
            return pageProp == null ? null : Value(pageProp, factory);
        }

        // The factory whose ObjectType full name is `fullName`.  Every kind has
        // one, but a property has two -- an interface-only factory and the plain
        // one -- under the same ObjectType; they differ in which parents they
        // accept, so the first factory that accepts `parent` (when given) wins.
        object Factory(string fullName, object parent = null)
        {
            var manager = Prop(_objectManagerIface, _objectManager, "ObjectFactoryManager");
            var factories = (Array)Prop(manager.GetType(), manager, "Factories");
            var names = new List<string>();
            object fallback = null;
            foreach (var factory in factories)
            {
                var type = (Type)Prop(factory.GetType(), factory, "ObjectType");
                if (type == null || type.FullName != fullName)
                {
                    names.Add(Convert.ToString(type == null ? null : type.FullName));
                    continue;
                }
                if (parent == null) return factory;
                var accepts = factory.GetType().GetMethod("AcceptsParentObject");
                if (accepts != null && (bool)accepts.Invoke(factory, new object[] { parent })) return factory;
                if (fallback == null) fallback = factory;
            }
            if (fallback != null) return fallback;
            throw new ProtocolException(ErrorCodes.Unavailable,
                "this IDE has no factory for " + fullName + "; it has: " + string.Join(", ", names.ToArray()));
        }

        static bool Accepts(object factory, object parentObject)
        {
            var accepts = factory.GetType().GetMethod("AcceptsParentObject");
            if (accepts == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "IObjectFactory.AcceptsParentObject is not present in this IDE");
            return (bool)accepts.Invoke(factory, new object[] { parentObject });
        }

        ProtocolException BadParent(ObjectCreate spec, object parent)
        {
            return new ProtocolException(ErrorCodes.BadParams,
                "a " + spec.Kind + " cannot be created " + Where(parent));
        }

        string Where(object parent) => parent == null ? "at the project root" : "below " + NameOf(parent);

        // ---- objects.delete / objects.rename

        // Removes one object by GUID.  The project's deny list is enforced here:
        // a project that denies `delete_pou` must not lose an object just
        // because the agent performs it.
        public Dictionary<string, object> DeleteObject(ObjectDelete spec)
        {
            RefuseWhileOnline();
            RequirePermission("objects.delete");
            RemoveObject(ProjectHandle(), spec.Guid);
            return new Dictionary<string, object>
            {
                { "deleted", true },
                { "guid", Id(spec.Guid) },
            };
        }

        // Renames one object by GUID. The IDE rewrites the declaration header
        // itself; the body and the child methods (same parent guid) are untouched.
        public Dictionary<string, object> RenameObject(ObjectRename spec)
        {
            RefuseWhileOnline();
            RequirePermission("objects.rename");
            var handle = ProjectHandle();
            var rename = ManagerMethod("RenameObject", typeof(int), typeof(Guid), typeof(string));
            try { rename.Invoke(_objectManager, new object[] { handle, spec.Guid, spec.Name }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "RenameObject: " + Invocation.Cause(e).Message); }
            return new Dictionary<string, object>
            {
                { "guid", Id(spec.Guid) },
                { "name", spec.Name },
                { "path", NamePath(handle, spec.Guid) },
            };
        }

        // Moves one object below a folder or an Application, on either tab,
        // through the view of the tab it goes to: the IDE changes only where
        // the tree shows it, so the object keeps its guid and its text.  The
        // top of the POUs tab has no node: MoveObject takes no parent for it.
        public Dictionary<string, object> MoveObject(ObjectMove spec)
        {
            RefuseWhileOnline();
            RequirePermission("objects.move");
            var handle = ProjectHandle();
            var view = PousView;
            var target = spec.AtRoot ? null : SvNode(handle, spec.ParentGuid, out view);
            var node = SvParentNode(handle, view, spec.Guid);
            var nodeType = FindType("_3S.CoDeSys.Core.Objects.ISVNode");
            var move = node.GetType().GetMethods().FirstOrDefault(method => method.Name == "MoveObject"
                && method.GetParameters().Length == 2 && method.GetParameters()[1].ParameterType == typeof(int)
                && method.GetParameters()[0].ParameterType == nodeType);
            if (move == null) throw new ProtocolException(ErrorCodes.Unavailable, "ISVNode.MoveObject is not present in this IDE");
            try { move.Invoke(node, new object[] { target, -1 }); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "cannot move " + Id(spec.Guid) + " there: " + Invocation.Cause(e).Message); }
            return new Dictionary<string, object>
            {
                { "guid", Id(spec.Guid) },
                { "path", NamePath(handle, spec.Guid) },
            };
        }

        // ExistsObject is checked first: RemoveObject on an unknown GUID killed
        // the IDE once, so a GUID that is not a live object never reaches the
        // object manager.
        void RemoveObject(int handle, Guid guid)
        {
            if (!(bool)Manager("ExistsObject", handle, guid)) throw UnknownObject(guid, null);
            try { Manager("RemoveObject", handle, guid); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "RemoveObject: " + Invocation.Cause(e).Message); }
        }

        // ---- project.save

        // Persist the primary project (`cts save`, `cts import --save`) and
        // name the file it went to. No online refusal: saving while logged in
        // is allowed.
        public Dictionary<string, object> SaveProject()
        {
            RequirePermission("project.save");
            var project = OpenProject();
            var save = _projectIface.GetMethod("Save", Type.EmptyTypes)
                ?? project.GetType().GetMethod("Save", Type.EmptyTypes);
            if (save == null) throw new ProtocolException(ErrorCodes.Unavailable, "IProject.Save is not present in this IDE");
            object saved;
            try { saved = save.Invoke(project, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Save: " + Invocation.Cause(e).Message); }
            if (saved is bool && !(bool)saved) throw new ProtocolException(ErrorCodes.Internal, "Save: the IDE did not save the project");
            var answer = new Dictionary<string, object> { { "saved", true } };
            var path = Convert.ToString(Prop(_projectIface, project, "Path"));
            if (!string.IsNullOrEmpty(path))
            {
                answer["path"] = path;
                var file = new System.IO.FileInfo(path);
                if (file.Exists) answer["size"] = file.Length;
            }
            return answer;
        }
    }
}
