// `objects.fields`, `objects.setfield` and `objects.listadd/listremove`: one
// object's persisted field tree, read or written.
//
// The object-manager chain is the one FindObjects and objects.settext use
// (GetObjectToRead / GetObjectToModify / SetObject); the tree itself is
// ObjectFields, reflection over the object's own IArchivable members.  Like
// objects.settext, a write is refused while an application is logged in and
// checks its object back in uncommitted when it fails, so one bad request does
// not leave the object "already in use" and fail every later call.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        // ---- objects.fields

        public Dictionary<string, object> Fields(string guid, string prop, int depth)
        {
            var parsed = ParseObjectGuid(guid);
            var meta = ObjectMeta(ProjectHandle(), parsed, "GetObjectToRead");
            var result = new Dictionary<string, object>
            {
                { "guid", Id(parsed) },
                { "name", NameOf(meta) },
                { "type", Id(TypeOf(meta)) },
                { "fields", ObjectFields.Tree(Source(meta, prop), depth) },
            };
            if (prop.Length > 0) result["prop"] = prop;
            return result;
        }

        // ---- objects.setfield

        // The modified object is checked back in uncommitted on any failure, the
        // way objects.settext does: otherwise it stays "already in use" and every
        // later modify of it fails until a restart.
        public Dictionary<string, object> SetField(string guid, string path, string value, string prop)
        {
            return Modify("objects.setfield", guid, (parsed, meta) =>
            {
                bool created;
                var source = SourceForWrite(meta, prop, out created);
                var steps = ObjectFields.ParsePath(path);
                var parent = ObjectFields.Walk(source, steps.GetRange(0, steps.Count - 1));
                var last = steps[steps.Count - 1];
                var old = ObjectFields.Get(parent, last);
                ObjectFields.Write(parent, last, FieldValue.Convert(value, old));
                var result = new Dictionary<string, object>
                {
                    { "guid", Id(parsed) },
                    { "old", ObjectFields.ValueText(old) },
                    { "value", ObjectFields.ValueText(ObjectFields.Get(parent, last)) },
                };
                if (created) result["created"] = true;
                return result;
            });
        }

        // ---- objects.listadd / objects.listremove (request shape in ListEdit)

        public Dictionary<string, object> ListAdd(string guid, ListInsert insert)
        {
            return Modify("objects.listadd", guid, (parsed, meta) =>
            {
                var list = ListEdit.Find(Prop(_metaObjectIface, meta, "Object"), insert.Path);
                ListEdit.Insert(list, insert.At, insert.Fields);
                return ListResult(parsed, list);
            });
        }

        public Dictionary<string, object> ListRemove(string guid, string path, int index)
        {
            return Modify("objects.listremove", guid, (parsed, meta) =>
            {
                var list = ListEdit.Find(Prop(_metaObjectIface, meta, "Object"), path);
                ListEdit.RemoveAt(list, index);
                return ListResult(parsed, list);
            });
        }

        static Dictionary<string, object> ListResult(Guid parsed, System.Collections.IList list)
        {
            return new Dictionary<string, object>
            {
                { "guid", Id(parsed) },
                { "count", list.Count },
            };
        }

        // One field write: refused while online or denied, then edit + SetObject.
        Dictionary<string, object> Modify(string method, string guid, Func<Guid, object, Dictionary<string, object>> edit)
        {
            RefuseWhileOnline();
            RequirePermission(method);
            var parsed = ParseObjectGuid(guid);
            var meta = ObjectMeta(ProjectHandle(), parsed, "GetObjectToModify");
            var setObject = SetObjectMethod();
            try
            {
                var result = edit(parsed, meta);
                try { setObject.Invoke(_objectManager, new object[] { meta, true, null }); }
                catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "SetObject: " + Invocation.Cause(e).Message); }
                return result;
            }
            catch
            {
                try { setObject.Invoke(_objectManager, new object[] { meta, false, null }); }
                catch { /* the object was never committed; a release that fails cannot make it worse */ }
                throw;
            }
        }

        // What a write touches: the object itself, one of its meta properties,
        // or -- a property the object does not have yet -- one created here.
        // The IDE lets you set "Exclude from build" on any POU and adds the
        // BuildProperty then, so a write creates the property the same way;
        // the create stays inside SetField's try, so a later failure releases
        // the object uncommitted like any other write.
        object SourceForWrite(object meta, string prop, out bool created)
        {
            created = false;
            if (prop.Length == 0) return Prop(_metaObjectIface, meta, "Object");
            var found = Source(meta, prop, false);
            if (found != null) return found;
            var type = PropertyType.Find(prop, System.AppDomain.CurrentDomain.GetAssemblies());
            if (type == null)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "no property '" + prop + "' on this object and no loaded type named '" + prop + "' to create one from");
            object property;
            try { property = Activator.CreateInstance(type); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot create a '" + prop + "': " + Invocation.Cause(e).Message);
            }
            AddProperty(meta, property, prop);
            created = true;
            return property;
        }

        // IMetaObject.AddProperty(IObjectProperty), by name: the meta object is
        // reached through reflection with no reference to the vendor assembly.
        void AddProperty(object meta, object property, string prop)
        {
            foreach (var candidate in _metaObjectIface.GetMethods())
                if (candidate.Name == "AddProperty" && candidate.GetParameters().Length == 1)
                {
                    try { candidate.Invoke(meta, new[] { property }); }
                    catch (Exception e)
                    {
                        throw new ProtocolException(ErrorCodes.BadParams,
                            "cannot add the created '" + prop + "': " + Invocation.Cause(e).Message);
                    }
                    return;
                }
            throw new ProtocolException(ErrorCodes.Unavailable, "IMetaObject.AddProperty is not present in this IDE");
        }

        // What the fields belong to: the object itself, or one of its meta
        // properties by runtime type name ("BuildProperty", "SVFoldersProperty").
        // A read (and the probe before a write) wants the missing property named
        // as bad_params; SourceForWrite wants null so it can create it instead.
        object Source(object meta, string prop)
        {
            return Source(meta, prop, true);
        }

        object Source(object meta, string prop, bool missingIsError)
        {
            if (prop.Length == 0) return Prop(_metaObjectIface, meta, "Object");
            var properties = Prop(_metaObjectIface, meta, "Properties") as Array;
            if (properties != null)
                foreach (var candidate in properties)
                    if (candidate != null && candidate.GetType().Name == prop) return candidate;
            var names = new List<string>();
            if (properties != null)
                foreach (var candidate in properties) names.Add(candidate.GetType().Name);
            if (!missingIsError) return null;
            throw new ProtocolException(ErrorCodes.BadParams, "no property '" + prop + "' on this object"
                + (names.Count == 0 ? "; it has none" : "; properties: " + string.Join(", ", names.ToArray())));
        }
    }
}
