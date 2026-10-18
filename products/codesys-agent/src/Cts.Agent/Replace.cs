// `objects.replace {guid, xml, properties?}`: one object's content written
// back from its disk `.xml` (an export entry), for the kinds that have no text
// form -- visualizations, devices, folders, project settings.  The object is
// deserialized with the CompactXml archive reader (IObjectManager2.ImportObject,
// which places nothing) and swapped into the existing object
// (GetObjectToModify -> IMetaObject2.ReplaceObject -> SetObject), so its guid,
// place in the tree and children stay.  `properties` names the MetaObject
// properties (by their type guid) the file holds differently from the IDE:
// each is removed from the object and the file's copy, if it has one, added.
// The rest of the MetaObject (its name) does not travel and the caller's
// read-back reports it.  Same online refusal and permission as every write.
// A Library Manager swapped this way has not loaded the libraries it now
// names (the IDE loads one when it is added in its editor): each is loaded
// after the swap, and one that does not load is named in `libraries`.
using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        static readonly Guid CompactXmlReader = new Guid("6F129F88-6420-403f-B776-7752427BD61F");

        public Dictionary<string, object> ReplaceObject(string guidText, string xml, string[] properties)
        {
            var guid = ParseObjectGuid(guidText);
            var documents = EntryDocuments.Parse(xml);
            if (documents.Guid != guid)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "the xml is object " + Id(documents.Guid) + ", not " + Id(guid));
            var import = ImportObjectMethod();
            var replace = ReplaceObjectMethod();
            var result = Modify("objects.replace", guidText, (parsed, meta) =>
            {
                string name;
                Array carried;
                var obj = Deserialize(import, documents, out name, out carried);
                try { replace.Invoke(meta, new[] { obj }); }
                catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "ReplaceObject: " + Invocation.Cause(e).Message); }
                if (properties != null) CarryProperties(meta, carried, properties);
                return new Dictionary<string, object> { { "guid", Id(parsed) } };
            });
            var libraries = LoadLibraries(guid);
            if (libraries != null) result["libraries"] = libraries;
            return result;
        }

        // Each library a Library Manager names, loaded (ILibManItem2.TryLoad):
        // the ones that failed, with why; null for any other object.
        List<object> LoadLibraries(Guid guid)
        {
            var libManIface = FindType("_3S.CoDeSys.LibManObject.ILibManObject");
            var itemIface = FindType("_3S.CoDeSys.LibManObject.ILibManItem2");
            var obj = Prop(_metaObjectIface, ReadMeta(ProjectHandle(), guid), "Object");
            if (libManIface == null || itemIface == null || !libManIface.IsInstanceOfType(obj)) return null;
            var all = NeedMethod(libManIface, "GetAllLibraries", new[] { typeof(bool) }, "ILibManObject.GetAllLibraries is not present in this IDE");
            var tryLoad = NeedMethod(itemIface, "TryLoad", Type.EmptyTypes, "ILibManItem2.TryLoad is not present in this IDE");
            var failed = new List<object>();
            foreach (var item in (all.Invoke(obj, new object[] { false }) as Array) ?? new object[0])
            {
                if (item == null || !itemIface.IsInstanceOfType(item)) continue;
                var error = tryLoad.Invoke(item, null) as Exception;
                if (error != null)
                    failed.Add(new Dictionary<string, object> { { "name", Convert.ToString(Prop(FindType("_3S.CoDeSys.LibManObject.ILibManItem"), item, "Name")) }, { "error", error.Message } });
            }
            return failed;
        }

        // IObjectManager2.ImportObject(metaStream, objectStream, readerGuid,
        // out parent, out guid, out object, out name, out properties).
        MethodInfo ImportObjectMethod()
        {
            var iface = FindType("_3S.CoDeSys.Core.Objects.IObjectManager2");
            if (iface != null)
                foreach (var candidate in iface.GetMethods())
                    if (candidate.Name == "ImportObject" && candidate.GetParameters().Length == 8) return candidate;
            throw new ProtocolException(ErrorCodes.Unavailable, "IObjectManager2.ImportObject is not present in this IDE");
        }

        MethodInfo ReplaceObjectMethod()
        {
            var meta = FindType("_3S.CoDeSys.Core.Objects.IMetaObject2");
            var obj = FindType("_3S.CoDeSys.Core.Objects.IObject");
            if (meta == null || obj == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "IMetaObject2.ReplaceObject is not present in this IDE");
            return NeedMethod(meta, "ReplaceObject", new[] { obj }, "IMetaObject2.ReplaceObject is not present in this IDE");
        }

        // Each named property (a type guid) leaves the object, and the file's
        // copy of it goes in when the file has one.
        void CarryProperties(object meta, Array carried, string[] properties)
        {
            var remove = NeedMethod(_metaObjectIface, "RemoveProperty", new[] { typeof(Guid) },
                "IMetaObject.RemoveProperty is not present in this IDE");
            var held = new HashSet<Guid>();
            var current = Prop(_metaObjectIface, meta, "Properties") as Array;
            if (current != null)
                foreach (var property in current) held.Add(PropertyGuid(property));
            foreach (var text in properties)
            {
                Guid guid;
                if (!Guid.TryParse(text, out guid))
                    throw new ProtocolException(ErrorCodes.BadParams, "properties: '" + text + "' is not a guid");
                if (held.Contains(guid))
                {
                    try { remove.Invoke(meta, new object[] { guid }); }
                    catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "RemoveProperty: " + Invocation.Cause(e).Message); }
                }
                if (carried == null) continue;
                foreach (var property in carried)
                    if (property != null && PropertyGuid(property) == guid) AddProperty(meta, property, guid.ToString("D"));
            }
        }

        // A meta property's key: the type guid its class is registered under
        // (the `TypeGuid` attribute the archive writes as its `Type`).
        static Guid PropertyGuid(object property)
        {
            foreach (var attribute in property.GetType().GetCustomAttributes(false))
            {
                var type = attribute.GetType();
                if (type.Name != "TypeGuidAttribute") continue;
                var value = type.GetProperty("Guid");
                if (value != null && value.PropertyType == typeof(Guid)) return (Guid)value.GetValue(attribute, null);
            }
            throw new ProtocolException(ErrorCodes.Internal, property.GetType().FullName + " has no TypeGuid");
        }

        // The entry's object, detached, and the name and properties its
        // MetaObject carries.
        object Deserialize(MethodInfo import, EntryDocuments documents, out string name, out Array properties)
        {
            using (var meta = new MemoryStream(documents.Meta))
            using (var data = new MemoryStream(documents.Object))
            {
                var args = new object[] { meta, data, CompactXmlReader, null, null, null, null, null };
                try { import.Invoke(_objectManager, args); }
                catch (Exception e) { throw new ProtocolException(ErrorCodes.BadParams, "ImportObject: " + Invocation.Cause(e).Message); }
                if (args[5] == null) throw new ProtocolException(ErrorCodes.BadParams, "ImportObject read no object from the xml");
                name = args[6] as string;
                properties = args[7] as Array;
                return args[5];
            }
        }
    }
}
