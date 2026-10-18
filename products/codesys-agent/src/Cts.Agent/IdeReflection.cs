using System;
using System.Linq;
using System.Reflection;

namespace Cts.Agent
{
    // Text parts, protocol errors and the reflection helpers every Ide half uses.
    internal sealed partial class Ide
    {
        // ---- text parts

        // The text of one part's TextDocument, or null when the part or its
        // TextDocument does not exist (graphical implementations have no text).
        static string PartText(object obj, string partName)
        {
            var doc = PartDocument(obj, partName);
            if (doc == null) return null;
            var textProp = FindProperty(doc.GetType(), "Text");
            var text = textProp == null ? null : Value(textProp, doc);
            return text == null ? null : Convert.ToString(text);
        }

        // One part's TextDocument, or null when the part or its TextDocument
        // does not exist.
        static object PartDocument(object obj, string partName)
        {
            var partProp = FindProperty(obj.GetType(), partName);
            var part = partProp == null ? null : Value(partProp, obj);
            if (part == null) return null;
            var docProp = FindProperty(part.GetType(), "TextDocument");
            return docProp == null ? null : Value(docProp, part);
        }

        static Tuple<PropertyInfo, object> WritableText(object obj, string partName)
        {
            var partProp = FindProperty(obj.GetType(), partName);
            var part = partProp == null ? null : Value(partProp, obj);
            if (part == null)
                throw new ProtocolException(ErrorCodes.BadParams, obj.GetType().Name + " has no " + partName + " part");
            var docProp = FindProperty(part.GetType(), "TextDocument");
            var doc = docProp == null ? null : Value(docProp, part);
            if (doc == null)
                throw new ProtocolException(ErrorCodes.BadParams, obj.GetType().Name + " " + partName + " has no text");
            var textProp = FindProperty(doc.GetType(), "Text");
            if (textProp == null || textProp.GetSetMethod(true) == null)
                throw new ProtocolException(ErrorCodes.BadParams, obj.GetType().Name + " " + partName + " text is not writable");
            return Tuple.Create(textProp, doc);
        }

        static void SetText(Tuple<PropertyInfo, object> text, string partName, string value)
        {
            try { text.Item1.SetValue(text.Item2, value, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, partName + " text: " + Invocation.Cause(e).Message); }
        }

        static long TimeStamp(object meta)
        {
            var prop = FindProperty(meta.GetType(), "TimeStamp");
            return prop == null ? 0L : Convert.ToInt64(Value(prop, meta));
        }

        // ---- errors

        static Guid ParseObjectGuid(string text)
        {
            Guid guid;
            if (!Guid.TryParse(text, out guid))
                throw new ProtocolException(ErrorCodes.BadParams, "guid must be a GUID: " + text);
            return guid;
        }

        static ProtocolException UnknownObject(Guid guid, Exception e)
        {
            var cause = e == null ? "" : ": " + Invocation.Cause(e).Message;
            return new ProtocolException(ErrorCodes.BadParams, "unknown object " + Id(guid) + cause);
        }

        // ---- reflection helpers

        public static Type FindType(string fullName)
        {
            return FindTypeOrNull(fullName) ?? throw new ProtocolException(ErrorCodes.Unavailable, "IDE type not loaded: " + fullName);
        }

        // An interface a version of the IDE may lack.
        static Type FindTypeOrNull(string fullName)
        {
            foreach (var asm in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type t;
                try { t = asm.GetType(fullName, false); } catch { continue; }
                if (t != null) return t;
            }
            return null;
        }

        // Any system instance, for `dev.reflect` root "system:<interface>".
        public static object SystemInstance(string iface)
        {
            var cm = FindType("_3S.CoDeSys.Core.Components.ComponentManager");
            var singleton = cm.GetProperty("Singleton", BindingFlags.Public | BindingFlags.Static).GetValue(null, null);
            var factory = singleton.GetType().GetProperty("InstanceFactory").GetValue(singleton, null);
            var method = factory.GetType().GetInterfaces().Concat(new[] { factory.GetType() })
                .Select(t => t.GetMethod("GetSystemInstance", new[] { typeof(string) }))
                .FirstOrDefault(x => x != null);
            if (method == null) throw new ProtocolException(ErrorCodes.Unavailable, "GetSystemInstance not found on the instance factory");
            var instance = method.Invoke(factory, new object[] { iface });
            if (instance == null) throw new ProtocolException(ErrorCodes.Unavailable, "no system instance for " + iface);
            return instance;
        }

        public static object Prop(Type iface, object target, string name)
        {
            var p = iface.GetProperty(name);
            if (p == null) throw new ProtocolException(ErrorCodes.Unavailable, iface.Name + "." + name + " not found");
            return p.GetValue(target, null);
        }

        // The named method, or an Unavailable naming it: the same binary runs
        // inside more than one IDE, so a missing member is a reply, not a crash.
        static MethodInfo NeedMethod(Type type, string name, Type[] signature, string missing)
        {
            var method = type.GetMethod(name, signature);
            if (method == null) throw new ProtocolException(ErrorCodes.Unavailable, missing);
            return method;
        }

        static PropertyInfo FindProperty(Type type, string name)
        {
            var prop = type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
            if (prop != null) return prop;
            foreach (var iface in type.GetInterfaces())
            {
                var via = iface.GetProperty(name);
                if (via != null && via.GetGetMethod() != null) return via;
            }
            return null;
        }

        static object Value(PropertyInfo prop, object target)
        {
            try { return prop.GetValue(target, null); }
            catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, prop.DeclaringType.Name + "." + prop.Name + ": " + Invocation.Cause(e).Message); }
        }
    }
}
