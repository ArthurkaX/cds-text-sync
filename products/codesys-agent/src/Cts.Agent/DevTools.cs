// `dev.*`: the tools used to discover the IDE's own API from a live process.
// They are registered only when the loader passes the `dev` option, so a
// production agent never exposes them.
//
//   dev.reflect  {root, path?, members?}   walk an object graph and describe it
//   dev.pin      {root, path?}             keep an object for later `pinned:<n>`
//   dev.listen   {root, path?, event}      subscribe to any event of any delegate type
//   dev.unlisten {id}
//   dev.types    {pattern}             loaded type names matching a regex, with their assembly
//
// Every IDE access goes through Ide.OnUi with a deadline; the event handler is
// expression-built and only snapshots the arguments (it never calls the IDE).
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Reflection;

namespace Cts.Agent
{
    internal sealed partial class DevTools
    {
        //: A single reflection step is cheap, but it walks the IDE's objects: keep
        //: a real deadline so a wedged property never holds the pipe forever.
        const int StepTimeoutMs = 30000;

        readonly Ide _ide;
        readonly EventBus _bus;
        readonly FileLog _log;
        readonly string _logPath;
        readonly string _options;
        readonly object _lock = new object();
        readonly Dictionary<int, object> _pins = new Dictionary<int, object>();
        readonly Dictionary<int, Listener> _listeners = new Dictionary<int, Listener>();
        int _nextId;

        public DevTools(Ide ide, EventBus bus, FileLog log, string logPath, string options)
        {
            _ide = ide;
            _bus = bus;
            _log = log;
            _logPath = logPath;
            _options = options;
        }

        public void Register(Router router)
        {
            router.Register("dev.reflect", (req, s) => Reflect(req));
            router.Register("dev.pin", (req, s) => Pin(req));
            router.Register("dev.listen", (req, s) => Listen(req));
            router.Register("dev.unlisten", (req, s) => Unlisten(req));
            router.Register("dev.reload", (req, s) => Reload(req, s));
            router.Register("dev.types", (req, s) => Types(req.String("pattern")));
        }

        // Removes every listener: called from AgentHost.Stop so a stopped agent
        // leaves no handler behind in the IDE.
        public void Stop()
        {
            List<Listener> listeners;
            lock (_lock)
            {
                listeners = new List<Listener>(_listeners.Values);
                _listeners.Clear();
            }
            foreach (var listener in listeners) Remove(listener);
        }

        // ---- dev.reflect

        Dictionary<string, object> Reflect(Request req)
        {
            var rootSpec = req.String("root");
            var steps = DevPath.Parse(req.Params);
            var members = req.Bool("members", false);
            var cap = (int)req.Int("max_members", 0);
            var itemCap = (int)req.Int("max_items", 0);
            // A login or a download can hold the UI thread for longer than a
            // reflection step; the caller may raise the deadline for those.
            var timeout = (int)Math.Max(1, Math.Min(600000, req.Int("timeout_ms", StepTimeoutMs)));

            var target = ResolveRoot(rootSpec);
            var result = new Dictionary<string, object>
            {
                { "root", rootSpec },
                { "path", PathText(steps) },
            };

            var trace = new List<object>();
            for (var i = 0; i < steps.Count; i++)
            {
                var step = steps[i];
                var here = target;
                var next = _ide.OnUi("dev.reflect " + step, timeout, () => Apply(here, step));
                if (next == null && i < steps.Count - 1)
                    throw new ProtocolException(ErrorCodes.Unavailable,
                        "path step '" + step + "' resolved to null and " + (steps.Count - i - 1) + " step(s) follow");
                trace.Add(new Dictionary<string, object>
                {
                    { "step", step.ToString() },
                    { "type", TypeName(next) },
                    { "to_string", DevReflection.Text(next) },
                });
                target = new DevTarget(next, false);
            }
            result["steps"] = trace;

            var described = _ide.OnUi("dev.reflect describe", timeout,
                () => DevReflection.Describe(target.Value, target.IsStatic, members, cap, itemCap));
            foreach (var kv in described) result[kv.Key] = kv.Value;
            return result;
        }

        // ---- dev.types

        //: More matches than this means the pattern is too wide to read.
        const int MaxTypes = 500;

        // Where an API lives before there is an object to reflect on: every
        // loaded type whose full name matches, public or not.
        static Dictionary<string, object> Types(string pattern)
        {
            var regex = new System.Text.RegularExpressions.Regex(pattern);
            var names = new List<object>();
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type[] types;
                try { types = assembly.GetTypes(); }
                catch (ReflectionTypeLoadException e) { types = e.Types; }
                catch { continue; }
                foreach (var type in types)
                {
                    if (type == null || type.FullName == null || !regex.IsMatch(type.FullName)) continue;
                    names.Add(type.FullName + ", " + assembly.GetName().Name);
                    if (names.Count >= MaxTypes)
                        return new Dictionary<string, object> { { "types", names }, { "truncated", true } };
                }
            }
            return new Dictionary<string, object> { { "types", names }, { "truncated", false } };
        }

        // ---- dev.pin

        Dictionary<string, object> Pin(Request req)
        {
            var rootSpec = req.String("root");
            var steps = DevPath.Parse(req.Params);
            var target = Walk(rootSpec, steps);

            int id;
            lock (_lock)
            {
                _nextId++;
                id = _nextId;
                _pins[id] = target.Value;
            }
            return new Dictionary<string, object>
            {
                { "n", id },
                { "root", rootSpec },
                { "path", PathText(steps) },
                { "type", TypeName(target) },
                { "to_string", DevReflection.Text(target.Value) },
            };
        }

        // ---- roots and the walk

        sealed class DevTarget
        {
            public object Value;
            public bool IsStatic;
            public DevTarget(object value, bool isStatic) { Value = value; IsStatic = isStatic; }
        }

        sealed class Listener
        {
            public int Id;
            public EventInfo Info;
            public object Target;
            public Delegate Handler;
        }

        DevTarget ResolveRoot(string spec)
        {
            if (spec == "engine") return new DevTarget(_ide.Engine, false);
            if (spec == "online_manager") return new DevTarget(_ide.OnlineManager, false);
            if (spec.StartsWith("static:", StringComparison.Ordinal))
                return new DevTarget(Ide.FindType(spec.Substring("static:".Length)), true);
            if (spec.StartsWith("system:", StringComparison.Ordinal))
                return new DevTarget(Ide.SystemInstance(spec.Substring("system:".Length)), false);
            if (spec.StartsWith("pinned:", StringComparison.Ordinal))
            {
                int id;
                if (!int.TryParse(spec.Substring("pinned:".Length), out id))
                    throw new ProtocolException(ErrorCodes.BadParams, "pinned:<n> needs an integer: " + spec);
                return new DevTarget(LookupPin(id), false);
            }
            throw new ProtocolException(ErrorCodes.BadParams,
                "unknown root '" + spec + "': engine, online_manager, system:<interface>, static:<type>, pinned:<n>");
        }

        DevTarget Walk(string rootSpec, List<PathStep> steps)
        {
            var target = ResolveRoot(rootSpec);
            foreach (var step in steps)
            {
                var here = target;
                target = _ide.OnUi("dev.walk " + step, StepTimeoutMs, () =>
                {
                    var next = Apply(here, step);
                    return new DevTarget(next, false);
                });
                if (target.Value == null)
                    throw new ProtocolException(ErrorCodes.Unavailable,
                        "path step '" + step + "' resolved to null");
            }
            return target;
        }

        object Apply(DevTarget target, PathStep step)
        {
            var isStatic = target.IsStatic;
            var type = isStatic ? (Type)target.Value : target.Value.GetType();
            switch (step.Kind)
            {
                case PathStep.StepKind.Property:
                {
                    var property = DevReflection.ResolveProperty(type, isStatic, step.Name);
                    return Read(property, isStatic ? null : target.Value);
                }
                case PathStep.StepKind.Set:
                {
                    var property = DevReflection.ResolveProperty(type, isStatic, step.Name);
                    if (property.GetSetMethod() == null)
                        throw new ProtocolException(ErrorCodes.BadParams, step.Name + " has no setter");
                    Write(property, isStatic ? null : target.Value,
                        Materialize(property.PropertyType, step.Arguments[0], step.Name),
                        step.ToString());
                    // Setting a property is a side effect; the walk stays on the
                    // object it set it on, so a further step can read it back.
                    return target.Value;
                }
                case PathStep.StepKind.Method:
                {
                    var method = DevReflection.ResolveMethod(type, isStatic, step.Name, step.Arguments);
                    var parameters = method.GetParameters();
                    var arguments = new object[parameters.Length];
                    for (var i = 0; i < parameters.Length; i++)
                        arguments[i] = Materialize(parameters[i].ParameterType, step.Arguments[i],
                            method.Name + " parameter " + parameters[i].Name);
                    return Invoke(method, isStatic ? null : target.Value, arguments, step.ToString());
                }
                default:
                {
                    var sequence = target.Value as IEnumerable;
                    if (sequence == null)
                        throw new ProtocolException(ErrorCodes.BadParams,
                            "[" + step.Index + "] needs an IEnumerable, " + type.FullName + " is not one");
                    var index = 0;
                    foreach (var item in sequence)
                    {
                        if (index == step.Index) return item;
                        index++;
                    }
                    throw new ProtocolException(ErrorCodes.BadParams,
                        "index [" + step.Index + "] is past the end (" + index + " item(s))");
                }
            }
        }

        // Reflection wraps whatever the IDE threw; the inner exception is the
        // only thing worth reporting, so unwrap it into a readable code/message.
        static ProtocolException Unwrap(Exception e, string what)
        {
            var protocol = e as ProtocolException;
            if (protocol != null) return protocol;
            var cause = Invocation.Cause(e);
            return new ProtocolException(ErrorCodes.Internal, what + ": " + cause.GetType().FullName + ": " + cause.Message);
        }

        static object Read(PropertyInfo property, object target)
        {
            try { return property.GetValue(target, null); }
            catch (Exception e) { throw Unwrap(e, property.Name); }
        }

        static void Write(PropertyInfo property, object target, object value, string what)
        {
            try { property.SetValue(target, value, null); }
            catch (Exception e) { throw Unwrap(e, what); }
        }

        static object Invoke(MethodInfo method, object target, object[] arguments, string what)
        {
            try { return method.Invoke(target, arguments); }
            catch (Exception e) { throw Unwrap(e, what); }
        }

        // A parsed argument as the parameter wants it: a pinned object is looked
        // up, an array is built element by element, a scalar is coerced.
        object Materialize(Type parameter, object argument, string what)
        {
            var pinned = argument as PinnedRef;
            if (pinned != null) argument = LookupPin(pinned.Id);

            var list = argument as IList<object>;
            if (list != null)
            {
                if (!parameter.IsArray)
                    throw new ProtocolException(ErrorCodes.BadParams, what + " is not an array");
                var element = parameter.GetElementType();
                var array = Array.CreateInstance(element, list.Count);
                for (var i = 0; i < list.Count; i++)
                    array.SetValue(Materialize(element, list[i], what + "[" + i + "]"), i);
                return array;
            }

            var value = Coerce(parameter, argument);
            if (value != null && !parameter.IsInstanceOfType(value))
                throw new ProtocolException(ErrorCodes.BadParams,
                    what + " needs a " + parameter.FullName + ", not " + argument.GetType().Name);
            return value;
        }

        object LookupPin(int id)
        {
            lock (_lock)
            {
                object pinned;
                if (!_pins.TryGetValue(id, out pinned))
                    throw new ProtocolException(ErrorCodes.BadParams, "no pinned object " + id);
                return pinned;
            }
        }

        static string TypeName(object value)
        {
            return value == null ? null : value.GetType().FullName;
        }

        // The type a target really is: for a `static:` root that is the named
        // type itself, not the Type object reflecting it.
        static string TypeName(DevTarget target)
        {
            if (target == null || target.Value == null) return null;
            return target.IsStatic ? ((Type)target.Value).FullName : target.Value.GetType().FullName;
        }

        static object Coerce(Type parameter, object value)
        {
            if (value == null) return null;
            var target = Nullable.GetUnderlyingType(parameter) ?? parameter;
            if (target.IsInstanceOfType(value)) return value;
            try { return Convert.ChangeType(value, target, CultureInfo.InvariantCulture); }
            catch (Exception) { return value; }
        }

        static List<object> PathText(List<PathStep> steps)
        {
            var text = new List<object>();
            foreach (var step in steps) text.Add(step.ToString());
            return text;
        }
    }
}
