// The reflection half of `dev.reflect`: carry one path step out on a live
// object, and describe what is there. Only names and members are read, never a
// method body; the object graph is whatever the caller rooted us at.
//
// A member is looked up on the runtime type and, for each interface the type
// implements, on that interface -- that is how an explicit implementation
// (which the runtime type exposes only as a private `Iface.Member`) is still
// reachable: reflection through the interface's own PropertyInfo calls it.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Reflection;
using System.Text;

namespace Cts.Agent
{
    public static class DevReflection
    {
        //: Longest ToString kept in a description.
        public const int MaxText = 200;
        //: How many members one description lists before it says it truncated.
        public const int MaxMembers = 300;
        //: How many items an IEnumerable previews unless the caller asks for more.
        public const int DefaultItems = 20;
        //: The most items one preview lists, however many are asked for.
        public const int MaxItems = 2000;

        // A static root names a type, not an object; for an interface there is
        // nothing static to see, so its instance members are what is listed.
        public static BindingFlags Flags(Type type, bool isStatic, bool nonPublic)
        {
            var access = nonPublic
                ? BindingFlags.Public | BindingFlags.NonPublic
                : BindingFlags.Public;
            var scope = isStatic && !type.IsInterface ? BindingFlags.Static : BindingFlags.Instance;
            return access | scope;
        }

        // ---- lookup

        public static PropertyInfo ResolveProperty(Type type, bool isStatic, string name)
        {
            var flags = Flags(type, isStatic, true);

            var own = type.GetProperty(name, flags);
            if (own != null) return own;
            foreach (var iface in type.GetInterfaces())
            {
                var via = iface.GetProperty(name);
                if (via != null && via.GetGetMethod() != null) return via;
            }
            throw new ProtocolException(ErrorCodes.BadParams, Missing(type, name, isStatic));
        }

        public static MethodInfo ResolveMethod(Type type, bool isStatic, string name, IList<object> arguments)
        {
            var flags = Flags(type, isStatic, true);

            var want = arguments == null ? 0 : arguments.Count;
            var candidates = new List<MethodInfo>();
            candidates.AddRange(Filter(type.GetMethods(flags), name, want));
            foreach (var iface in type.GetInterfaces())
            {
                foreach (var m in iface.GetMethods())
                    if (m.Name == name && m.GetParameters().Length == want && !m.ContainsGenericParameters
                        && !candidates.Any(c => SameSignature(c, m)))
                        candidates.Add(m);
            }
            if (candidates.Count == 0)
                throw new ProtocolException(ErrorCodes.BadParams, Missing(type, name, isStatic));

            candidates.Sort((a, b) => MatchScore(b, arguments).CompareTo(MatchScore(a, arguments)));
            // A method with a ref/out parameter cannot be invoked with a plain value.
            return candidates.FirstOrDefault(c => !c.GetParameters().Any(p => p.ParameterType.IsByRef)) ?? candidates[0];
        }

        static IEnumerable<MethodInfo> Filter(MethodInfo[] methods, string name, int argc)
        {
            foreach (var m in methods)
                if (m.Name == name && m.GetParameters().Length == argc && !m.ContainsGenericParameters
                    && !m.IsSpecialName)
                    yield return m;
        }

        static bool SameSignature(MethodInfo a, MethodInfo b)
        {
            if (a.Name != b.Name || a.GetParameters().Length != b.GetParameters().Length) return false;
            var pa = a.GetParameters();
            var pb = b.GetParameters();
            for (var i = 0; i < pa.Length; i++)
                if (pa[i].ParameterType != pb[i].ParameterType) return false;
            return true;
        }

        // A parameter that can take an argument beats one that cannot: with a
        // Guid too many overloads take a string, this keeps the call honest.
        static int MatchScore(MethodInfo method, IList<object> arguments)
        {
            if (arguments == null) return 0;
            var parameters = method.GetParameters();
            var score = 0;
            for (var i = 0; i < parameters.Length && i < arguments.Count; i++)
            {
                var argument = arguments[i];
                if (argument == null) continue;
                var type = parameters[i].ParameterType;
                var value = argument.GetType();
                if (type == value) score += 3;
                else if (type.IsAssignableFrom(value)) score += 2;
                else if (type == typeof(object)) score += 1;
            }
            return score;
        }

        static string Missing(Type type, string name, bool isStatic)
        {
            var close = Suggest(type, name, isStatic);
            var suffix = close.Count == 0 ? "" : "; did you mean " + string.Join(", ", close);
            return "no member '" + name + "' on " + type.FullName + suffix;
        }

        // Names close enough to be what the caller meant: an edit distance of
        // three or less (half the query for a long one), or a name that
        // contains the query.
        public static List<string> Suggest(Type type, string name, bool isStatic)
        {
            var names = new List<string>();
            var flags = Flags(type, isStatic, true);
            foreach (var p in type.GetProperties(flags)) names.Add(p.Name);
            foreach (var m in type.GetMethods(flags)) if (!m.IsSpecialName) names.Add(m.Name);
            foreach (var e in type.GetEvents(flags)) names.Add(e.Name);
            foreach (var i in type.GetInterfaces())
            {
                foreach (var p in i.GetProperties()) names.Add(p.Name);
                foreach (var m in i.GetMethods()) if (!m.IsSpecialName) names.Add(m.Name);
                foreach (var e in i.GetEvents()) names.Add(e.Name);
            }
            return Closest(names, name).Take(8).ToList();
        }

        // The names closest to the query first, ignoring case; cts read uses it too.
        internal static IEnumerable<string> Closest(IEnumerable<string> names, string name)
        {
            var query = name.ToLowerInvariant();
            var scored = new List<KeyValuePair<int, string>>();
            foreach (var candidate in names.Distinct(StringComparer.OrdinalIgnoreCase))
            {
                var low = candidate.ToLowerInvariant();
                var distance = low.IndexOf(query, StringComparison.Ordinal) >= 0
                    ? 0
                    : Levenshtein(low, query);
                if (distance <= Math.Max(3, query.Length / 2))
                    scored.Add(new KeyValuePair<int, string>(distance, candidate));
            }
            scored.Sort((a, b) => a.Key != b.Key ? a.Key.CompareTo(b.Key) : string.CompareOrdinal(a.Value, b.Value));
            return scored.Select(kv => kv.Value);
        }

        static int Levenshtein(string a, string b)
        {
            var previous = new int[b.Length + 1];
            var current = new int[b.Length + 1];
            for (var j = 0; j <= b.Length; j++) previous[j] = j;
            for (var i = 1; i <= a.Length; i++)
            {
                current[0] = i;
                for (var j = 1; j <= b.Length; j++)
                {
                    var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                    current[j] = Math.Min(Math.Min(current[j - 1] + 1, previous[j] + 1), previous[j - 1] + cost);
                }
                var swap = previous; previous = current; current = swap;
            }
            return previous[b.Length];
        }

        // ---- describing

        // A text safe to put on the wire: never throws, never huge.
        public static string Text(object value)
        {
            if (value == null) return null;
            string text;
            try { text = Convert.ToString(value, CultureInfo.InvariantCulture); }
            catch (Exception e) { text = "<ToString threw " + e.GetType().Name + ">"; }
            if (text == null) return null;
            return text.Length > MaxText ? text.Substring(0, MaxText) + "..." : text;
        }

        // The value itself when it is a scalar the wire can carry, else null
        // (the caller reads to_string instead).
        public static object SimpleValue(object value)
        {
            if (value == null) return null;
            if (value is string || value is bool || value is DateTime || value is Enum) return value;
            if (value is double || value is float) return (double)Convert.ToDouble(value, CultureInfo.InvariantCulture);
            if (value is sbyte || value is byte || value is short || value is ushort
                || value is int || value is uint || value is long || value is ulong)
                return value;
            return null;
        }

        public static Dictionary<string, object> Describe(object target, bool isStatic, bool members, int memberCap, int itemCap)
        {
            if (target == null)
                return new Dictionary<string, object>
                {
                    { "type", null },
                    { "interfaces", new List<string>() },
                    { "to_string", null },
                };
            var type = isStatic ? (Type)target : target.GetType();
            var result = new Dictionary<string, object>
            {
                { "type", type.FullName },
                { "interfaces", InterfaceNames(type) },
                { "to_string", Text(target) },
            };
            var simple = SimpleValue(target);
            if (simple != null) result["value"] = simple;

            if (members) result["members"] = Members(type, isStatic, memberCap);

            var sequence = target as IEnumerable;
            if (sequence != null && !(target is string)) result["items"] = Preview(sequence, itemCap);
            return result;
        }

        public static List<string> InterfaceNames(Type type)
        {
            return type.GetInterfaces()
                .Select(i => i.FullName)
                .Where(n => n != null)
                .OrderBy(n => VendorRank(n))
                .ThenBy(n => n, StringComparer.Ordinal)
                .ToList();
        }

        public static List<object> Preview(IEnumerable sequence, int cap)
        {
            var limit = cap <= 0 ? DefaultItems : Math.Min(cap, MaxItems);
            var items = new List<object>();
            foreach (var item in sequence)
            {
                items.Add(new Dictionary<string, object>
                {
                    { "type", item == null ? null : item.GetType().FullName },
                    { "to_string", Text(item) },
                });
                if (items.Count >= limit) break;
            }
            return items;
        }

        public static Dictionary<string, object> Members(Type type, bool isStatic, int cap)
        {
            // Public only: the IDE's implementation types carry private,
            // compiler-generated members with names like "\u0001", and the
            // interesting surface is the public one (explicit implementations
            // are listed through their interface anyway).
            var flags = Flags(type, isStatic, false);

            var all = new List<KeyValuePair<int, string>>();
            // The runtime type first, then every interface.
            var types = new List<Type> { type };
            types.AddRange(type.GetInterfaces());

            foreach (var owner in types)
            {
                // An enumeration's members are its literals -- static fields --
                // and they are the whole point of asking about an enum, so they
                // are listed by name and value.  Any other type lists its public
                // fields as well, which the properties/methods/events sweep misses.
                if (owner.IsEnum)
                {
                    foreach (var name in Enum.GetNames(owner))
                        all.Add(Entry(owner, name + " = " + EnumValue(owner, name)));
                }
                else
                {
                    foreach (var f in owner.GetFields(flags))
                        all.Add(Entry(owner, f.Name + " : " + TypeName(f.FieldType)));
                }
                foreach (var p in owner.GetProperties(flags))
                    all.Add(Entry(owner, p.Name + " : " + TypeName(p.PropertyType) + Accessors(p)));
                foreach (var m in owner.GetMethods(flags))
                    if (!m.IsSpecialName) all.Add(Entry(owner, Signature(m)));
                foreach (var e in owner.GetEvents(flags))
                    all.Add(Entry(owner, e.Name + "(" + TypeName(e.EventHandlerType) + ")"));
            }

            var ordered = all
                .OrderBy(kv => kv.Key)
                .ThenBy(kv => kv.Value, StringComparer.Ordinal)
                .Select(kv => kv.Value)
                .Distinct()
                .ToList();

            var limit = cap <= 0 ? MaxMembers : Math.Min(cap, MaxMembers);
            var result = new Dictionary<string, object>
            {
                { "count", ordered.Count },
                { "listed", Math.Min(limit, ordered.Count) },
                { "truncated", ordered.Count > limit },
            };
            var names = new List<object>();
            for (var i = 0; i < ordered.Count && i < limit; i++) names.Add(ordered[i]);
            result["signatures"] = names;
            return result;
        }

        static KeyValuePair<int, string> Entry(Type owner, string signature)
        {
            var prefix = owner.Name + ".";
            return new KeyValuePair<int, string>(VendorRank(owner.FullName ?? owner.Name), prefix + signature);
        }

        static string EnumValue(Type type, string name)
        {
            var value = Enum.Parse(type, name);
            return Convert.ToInt64(value, CultureInfo.InvariantCulture)
                .ToString(CultureInfo.InvariantCulture);
        }

        public static string Signature(MethodInfo method)
        {
            var text = new StringBuilder(method.Name);
            text.Append('(');
            var parameters = method.GetParameters();
            for (var i = 0; i < parameters.Length; i++)
            {
                if (i > 0) text.Append(", ");
                text.Append(TypeName(parameters[i].ParameterType)).Append(' ').Append(parameters[i].Name);
            }
            text.Append(") -> ").Append(TypeName(method.ReturnType));
            return text.ToString();
        }

        static string Accessors(PropertyInfo property)
        {
            var get = property.GetGetMethod(true) != null ? "get" : "";
            var set = property.GetSetMethod(true) != null ? "set" : "";
            if (get.Length == 0 && set.Length == 0) return "";
            return " {" + get + (get.Length > 0 && set.Length > 0 ? "; " : "") + set + "}";
        }

        // CODESYS's own namespaces first, everyone else after.
        public static int VendorRank(string fullName)
        {
            if (fullName == null) return 2;
            return fullName.StartsWith("_3S.", StringComparison.Ordinal)
                || fullName.StartsWith("CODESYS.", StringComparison.Ordinal) ? 0 : 1;
        }

        public static string TypeName(Type type)
        {
            if (type == null) return "?";
            try
            {
                if (type.IsArray) return TypeName(type.GetElementType()) + "[]";
                if (!type.IsGenericType) return type.Name;
                var name = type.Name;
                var backtick = name.IndexOf('`');
                if (backtick >= 0) name = name.Substring(0, backtick);
                return name + "<" + string.Join(", ", type.GetGenericArguments().Select(TypeName)) + ">";
            }
            catch { return type.Name; }
        }
    }
}
