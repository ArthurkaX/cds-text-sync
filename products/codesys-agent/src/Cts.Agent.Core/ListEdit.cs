// Row inserts and removals for `objects.listadd` and `objects.listremove`, the
// IDE-free half (the object-manager chain is in Fields.cs):
//
//   objects.listadd    {"guid", "path", "at", "fields": {"TextID": "213", ...}}
//   objects.listremove {"guid", "path", "index"}
//
// `path` is the dotted field path of a list ("TextList"); `fields` are paths
// relative to the new item.  A new item is a Clone() of the list's last one --
// CODESYS rows clone deep, so the copy keeps the source's own values and the
// caller sets every field it cares about -- or, for an empty list, a new
// instance of the list's item type, so a caller never names a CLR type.
using System;
using System.Collections;
using System.Collections.Generic;

namespace Cts.Agent
{
    public sealed class ListInsert
    {
        public string Path { get; private set; }
        public int At { get; private set; }
        public IDictionary<string, object> Fields { get; private set; }

        public static ListInsert From(Request req)
        {
            var at = req.Int("at", -1);
            if (at < 0) throw new ProtocolException(ErrorCodes.BadParams, "parameter 'at' is required and must not be negative");
            object raw;
            IDictionary<string, object> fields = new Dictionary<string, object>();
            if (req.Params.TryGetValue("fields", out raw) && raw != null)
            {
                fields = raw as IDictionary<string, object>;
                if (fields == null)
                    throw new ProtocolException(ErrorCodes.BadParams, "parameter 'fields' must be an object of path: text");
            }
            return new ListInsert { Path = ListEdit.ListPath(req), At = (int)at, Fields = fields };
        }
    }

    public static class ListEdit
    {
        // The list path itself, never an item of it: "TextList", not "TextList[0]".
        public static string ListPath(Request req)
        {
            var path = req.String("path", "");
            var steps = ObjectFields.ParsePath(path);
            if (steps[steps.Count - 1].IsIndexed)
                throw new ProtocolException(ErrorCodes.BadParams, "path '" + path + "' names a list item, not a list");
            return path;
        }

        public static IList Find(object root, string path)
        {
            var list = ObjectFields.Walk(root, ObjectFields.ParsePath(path)) as IList;
            if (list == null) throw new ProtocolException(ErrorCodes.BadParams, path + " is not a list");
            return list;
        }

        // Inserts a new item at `at` (0..Count) with `fields` set on it; the
        // list is untouched when a field cannot be set.
        public static object Insert(IList list, int at, IDictionary<string, object> fields)
        {
            if (at > list.Count)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "at " + at + " is past the end of a list of " + list.Count + " items");
            var item = NewItem(list);
            foreach (var field in fields)
            {
                var steps = ObjectFields.ParsePath(field.Key);
                var parent = ObjectFields.Walk(item, steps.GetRange(0, steps.Count - 1));
                var last = steps[steps.Count - 1];
                var text = field.Value == null ? "" : Convert.ToString(field.Value, System.Globalization.CultureInfo.InvariantCulture);
                ObjectFields.Write(parent, last, FieldValue.Convert(text, ObjectFields.Get(parent, last)));
            }
            list.Insert(at, item);
            return item;
        }

        public static void RemoveAt(IList list, int index)
        {
            if (index < 0 || index >= list.Count)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "index " + index + " is not an item of a list of " + list.Count + " items");
            list.RemoveAt(index);
        }

        static object NewItem(IList list)
        {
            if (list.Count > 0)
            {
                var source = list[list.Count - 1] as ICloneable;
                if (source == null)
                    throw new ProtocolException(ErrorCodes.BadParams, "the list's items cannot be copied (not ICloneable)");
                return source.Clone();
            }
            var type = ItemType(list.GetType());
            if (type == null || type == typeof(object) || type.IsAbstract || type.IsInterface)
                throw new ProtocolException(ErrorCodes.BadParams, "the list is empty and its type names no item type to create");
            try { return Activator.CreateInstance(type); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams, "cannot create a " + type.Name + ": " + e.Message);
            }
        }

        // T of the IList<T> the list implements, or the element type of an array.
        static Type ItemType(Type listType)
        {
            if (listType.IsArray) return listType.GetElementType();
            foreach (var iface in listType.GetInterfaces())
                if (iface.IsGenericType && iface.GetGenericTypeDefinition() == typeof(IList<>))
                    return iface.GetGenericArguments()[0];
            return null;
        }
    }
}
