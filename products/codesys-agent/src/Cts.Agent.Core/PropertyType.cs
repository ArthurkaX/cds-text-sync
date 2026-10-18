// Which loaded type a caller's `prop` names: the way `objects.setfield` turns
// "BuildProperty" into the property it has to create when the object lacks it.
//
// The lookup is by runtime type name plus the IObjectProperty interface, both
// public metadata, so the agent hardcodes neither a type name nor a type guid:
// the caller names the property the IDE itself shows.
using System;
using System.Collections.Generic;
using System.Reflection;

namespace Cts.Agent
{
    public static class PropertyType
    {
        //: Assemblies do not unload and a type name has one property type, so
        //: the answer is cached; a `cts import` sets several flags on the
        //: one created property and must not rescan every assembly each time.
        static readonly Dictionary<string, Type> Known = new Dictionary<string, Type>();

        // The first non-abstract type named `name` that implements
        // IObjectProperty, or null when none is loaded.  A type list that a
        // vendor assembly fails to load is skipped, not fatal.
        public static Type Find(string name, IEnumerable<Assembly> assemblies)
        {
            if (string.IsNullOrEmpty(name)) return null;
            lock (Known)
            {
                Type cached;
                if (Known.TryGetValue(name, out cached)) return cached;
            }
            foreach (var assembly in assemblies)
            {
                if (assembly == null) continue;
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException e) { types = e.Types; }
                catch (Exception) { continue; }
                foreach (var type in types)
                {
                    if (type == null || type.Name != name || type.IsAbstract || type.IsInterface) continue;
                    if (!HasInterface(type, "IObjectProperty")) continue;
                    lock (Known) { Known[name] = type; }
                    return type;
                }
            }
            return null;
        }

        static bool HasInterface(Type type, string name)
        {
            foreach (var iface in type.GetInterfaces())
                if (iface.Name == name) return true;
            return false;
        }
    }
}
