// The persisted field tree of one project object, for `objects.fields` and
// `objects.setfield`.
//
// Every project object implements IArchivable: SerializableValueNames names its
// persisted fields and GetSerializableValue/SetSerializableValue reach them --
// the tree the CompactXml archive carries, and the only way to see a task's
// priority, a text list's rows or a device's IO mapping, none of which are text.
// A read renders that tree as JSON; a write reaches one leaf by dotted path and
// keeps the type of the field it finds.
//
// The reflection is name-based like the rest of the agent -- members are looked
// up on the object the caller passes -- so this file is the IDE-free half and is
// unit-tested on Linux against plain stand-ins.
//
// A tree leaves out two kinds of member:
//   * the text (a POU's Interface/Implementation TextDocument, a visualization's
//     own TextDocument): that is the body, which the .st/.xml projections carry,
//     not a field an agent should walk;
//   * what CODESYS regenerates on every save (UniqueIdGenerator, the guid
//     init/reinit/exit members, LineInfoPersistence, LanguageModelData), because
//     two reads of an unchanged project would otherwise differ.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace Cts.Agent
{
    // One step of a dotted field path: a serializable value name, plus -- when
    // the step names a list item -- that item's index ("TextList[0]").
    public sealed class FieldStep
    {
        public FieldStep(string name, int index) { Name = name; Index = index; }

        public string Name { get; private set; }

        // -1 when the step names the field itself rather than one item of it.
        public int Index { get; private set; }

        public bool IsIndexed { get { return Index >= 0; } }
    }

    public static class ObjectFields
    {
        //: Members CODESYS regenerates, so they are never part of a tree.
        public static readonly string[] Volatile = {
            "UniqueIdGenerator", "LineInfoPersistence", "GuidInit", "GuidReInit",
            "GuidExitX", "LanguageModelData",
        };

        //: The deepest tree a request can ask for; a cyclic archive must not be
        //: able to recurse the IDE away.
        public const int MaxDepth = 32;

        // ---- paths

        // "Watchdog.Time.Time" and "TextList[0].LanguageTexts[0]" -> steps.  A
        // malformed path is bad_params before anything is read or written.
        public static List<FieldStep> ParsePath(string path)
        {
            if (string.IsNullOrEmpty(path))
                throw new ProtocolException(ErrorCodes.BadParams, "path is required");
            var steps = new List<FieldStep>();
            foreach (var part in path.Split('.')) steps.Add(ParseStep(part));
            return steps;
        }

        static FieldStep ParseStep(string part)
        {
            if (part.Length == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "path has an empty step");
            var open = part.IndexOf('[');
            if (open < 0) return new FieldStep(part, -1);
            if (part[part.Length - 1] != ']')
                throw new ProtocolException(ErrorCodes.BadParams, "path step '" + part + "' does not close its index");
            int index;
            var digits = part.Substring(open + 1, part.Length - open - 2);
            if (!int.TryParse(digits, NumberStyles.None, CultureInfo.InvariantCulture, out index))
                throw new ProtocolException(ErrorCodes.BadParams, "path step '" + part + "' does not name a list index");
            if (open == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "path step '" + part + "' has no field name");
            return new FieldStep(part.Substring(0, open), index);
        }

        // ---- reading

        // One step: the named serializable value, or -- with an index -- that
        // item of the list the name holds.  A name the object does not have is
        // bad_params and names the fields it does have.
        public static object Get(object target, FieldStep step)
        {
            if (target == null)
                throw new ProtocolException(ErrorCodes.BadParams, "the path leaves the object before its last step");
            if (!step.IsIndexed) return Value(target, step.Name);
            return ListOf(target, step)[step.Index];
        }

        // The dotted path from a root and down; an empty one is the root itself.
        public static object Walk(object target, IList<FieldStep> steps)
        {
            foreach (var step in steps) target = Get(target, step);
            return target;
        }

        static IList ListOf(object target, FieldStep step)
        {
            var list = Value(target, step.Name) as IList;
            if (list == null)
                throw new ProtocolException(ErrorCodes.BadParams, step.Name + " is not a list");
            if (step.Index >= list.Count)
                throw new ProtocolException(ErrorCodes.BadParams,
                    step.Name + " has " + list.Count + " items; there is no item " + step.Index);
            return list;
        }

        static object Value(object target, string name)
        {
            var get = Member(target, "GetSerializableValue", typeof(string));
            if (get == null)
                throw new ProtocolException(ErrorCodes.BadParams,
                    target.GetType().Name + " is not an archivable object");
            try { return get.Invoke(target, new object[] { name }); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot read field '" + name + "' on " + target.GetType().Name + ": " + Invocation.Cause(e).Message
                    + "; fields: " + string.Join(", ", Names(target)));
            }
        }

        // ---- the tree

        // The persisted fields of one archivable as JSON, `depth` levels deep; a
        // node at that limit is present but empty, the way project.tree answers.
        public static Dictionary<string, object> Tree(object archivable, int depth)
        {
            if (depth > MaxDepth) depth = MaxDepth;
            var fields = new Dictionary<string, object>();
            foreach (var name in Names(archivable))
            {
                if (IsVolatile(name)) continue;
                var value = Value(archivable, name);
                if (IsText(value)) continue;
                fields[name] = Describe(value, depth - 1);
            }
            return fields;
        }

        // A value as JSON: an archivable as an object of its fields, a hashtable
        // as {key: value}, any other collection as an array, and a scalar -- or
        // anything else, such as a vendor value with no shape of its own -- as
        // its text.
        public static object Describe(object value, int depth)
        {
            if (value == null) return null;
            if (IsArchivable(value))
            {
                if (depth <= 0) return new Dictionary<string, object>();
                return Tree(value, depth);
            }
            if (value is IDictionary)
            {
                if (depth <= 0) return new Dictionary<string, object>();
                return Map((IDictionary)value, depth);
            }
            if (value is IEnumerable && !(value is string))
            {
                if (depth <= 0) return new List<object>();
                return Items((IEnumerable)value, depth);
            }
            return ValueText(value);
        }

        static Dictionary<string, object> Map(IDictionary map, int depth)
        {
            var result = new Dictionary<string, object>();
            foreach (DictionaryEntry entry in map)
                result[ValueText(entry.Key) ?? ""] = Describe(entry.Value, depth - 1);
            return result;
        }

        static List<object> Items(IEnumerable list, int depth)
        {
            var result = new List<object>();
            foreach (var item in list) result.Add(Describe(item, depth - 1));
            return result;
        }

        // A scalar as the wire carries it: a string as it is, an enum by name
        // ("Cyclic"), everything else in the invariant spelling of its type.
        public static string ValueText(object value)
        {
            return value == null ? null : Convert.ToString(value, CultureInfo.InvariantCulture);
        }

        // ---- writing

        // One step of a write: the named serializable value, or the i-th item of
        // the list it names.  The value must already have the field's type.
        public static void Write(object target, FieldStep step, object value)
        {
            if (target == null)
                throw new ProtocolException(ErrorCodes.BadParams, "the path leaves the object before its last step");
            if (step.IsIndexed) { ListOf(target, step)[step.Index] = value; return; }
            var set = Member(target, "SetSerializableValue", typeof(string), typeof(object));
            if (set == null)
                throw new ProtocolException(ErrorCodes.BadParams,
                    target.GetType().Name + " is not an archivable object");
            try { set.Invoke(target, new object[] { step.Name, value }); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "cannot write field '" + step.Name + "' on " + target.GetType().Name + ": " + Invocation.Cause(e).Message);
            }
        }

        // ---- members

        public static string[] Names(object target)
        {
            if (target == null) throw new ProtocolException(ErrorCodes.BadParams, "the path names no object");
            var property = DevReflection.ResolveProperty(target.GetType(), false, "SerializableValueNames");
            try { return (string[])property.GetValue(target, null); }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    target.GetType().Name + " is not an archivable object: " + Invocation.Cause(e).Message);
            }
        }

        public static bool IsArchivable(object value)
        {
            return value != null && HasInterface(value, "IArchivable");
        }

        public static bool IsVolatile(string name)
        {
            foreach (var volatileName in Volatile)
                if (string.Equals(volatileName, name, StringComparison.Ordinal)) return true;
            return false;
        }

        // The body of a kind: a TextDocument itself, or -- a POU's Interface and
        // Implementation -- a container that holds nothing but one.
        static bool IsText(object value)
        {
            if (value == null) return false;
            if (HasInterface(value, "ITextDocument")) return true;
            if (!IsArchivable(value)) return false;
            try
            {
                var names = Names(value);
                if (names.Length == 0) return false;
                foreach (var name in names)
                    if (!HasInterface(Value(value, name), "ITextDocument")) return false;
                return true;
            }
            catch (ProtocolException) { return false; }
        }

        static bool HasInterface(object value, string name)
        {
            // An archivable may hold a null member (an unset visual element
            // colour); a null value is simply not a text document.
            if (value == null) return false;
            foreach (var iface in value.GetType().GetInterfaces())
                if (string.Equals(iface.Name, name, StringComparison.Ordinal)) return true;
            return false;
        }

        // The member of the given exact signature, on the runtime type or -- an
        // explicit implementation the runtime type hides -- on the interface
        // that declares it.  Never resolved by argument shape: an archivable's
        // own two members are the only ones this file may reach.
        static MethodInfo Member(object target, string name, params Type[] signature)
        {
            var type = target.GetType();
            var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            var method = type.GetMethod(name, flags, null, signature, null);
            if (method != null) return method;
            foreach (var iface in type.GetInterfaces())
            {
                method = iface.GetMethod(name, signature);
                if (method != null) return method;
            }
            return null;
        }
    }

    public static class FieldValue
    {
        // A written value, turned into the type of the field it replaces: a
        // string field takes the text as it is, an enum by name ("Cyclic"), a
        // Guid by its text, anything else in the invariant spelling of its type.
        // A text the type cannot hold is bad_params, and the caller -- which
        // reads the field before it writes -- has written nothing.
        public static object Convert(string text, object old)
        {
            if (old == null || old is string) return text;
            var type = old.GetType();
            try
            {
                if (type.IsEnum) return Enum.Parse(type, text, false);
                if (type == typeof(Guid)) return Guid.Parse(text);
                return System.Convert.ChangeType(text, type, CultureInfo.InvariantCulture);
            }
            catch (Exception e)
            {
                throw new ProtocolException(ErrorCodes.BadParams,
                    "'" + text + "' is not a value for a " + DevReflection.TypeName(type) + " field (" + e.GetType().Name + ")");
            }
        }
    }
}
