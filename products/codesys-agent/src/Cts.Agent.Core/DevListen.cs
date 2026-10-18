// `dev.listen` subscribes to an event of *any* delegate type. The handler is a
// real, emitted static method: a delegate whose Method is an ordinary
// RuntimeMethodInfo.
//
// It must be, because CODESYS stores event handlers in its own
// `_3S.CoDeSys.Utilities.WeakMulticastDelegate`, which raises an event by
// calling `handler.Method.Invoke(...)` reflectively. A delegate compiled from an
// Expression (System.Linq.Expressions) is backed by a DynamicMethod, whose
// MethodInfo is an RTDynamicMethod, and RTDynamicMethod.Invoke throws
// "MethodInfo must be a runtime MethodInfo object" -- inside the IDE's own event
// pump, on the UI thread, which crashed the IDE (seen live). So the
// handler is emitted into a dynamic assembly with Reflection.Emit and bound with
// Delegate.CreateDelegate: a plain static method, safe for the IDE to invoke.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using System.Threading;

namespace Cts.Agent
{
    public static class DevListen
    {
        //: How many properties of an event's arguments one event snapshots.
        public const int MaxArgProperties = 40;

        const string SinkField = "Sink";
        const string HandleMethod = "Handle";

        static readonly ModuleBuilder Module = CreateModule();
        static int _sinks;

        static ModuleBuilder CreateModule()
        {
            var assembly = AssemblyBuilder.DefineDynamicAssembly(
                new AssemblyName("Cts.Agent.EventSinks"), AssemblyBuilderAccess.Run);
            return assembly.DefineDynamicModule("sinks");
        }

        public static EventInfo ResolveEvent(Type type, bool isStatic, string name)
        {
            var flags = DevReflection.Flags(type, isStatic, true);

            var own = type.GetEvent(name, flags);
            if (own != null) return own;
            foreach (var iface in type.GetInterfaces())
            {
                var via = iface.GetEvent(name);
                if (via != null) return via;
            }
            var close = DevReflection.Suggest(type, name, isStatic);
            var suffix = close.Count == 0 ? "" : "; did you mean " + string.Join(", ", close);
            throw new ProtocolException(ErrorCodes.BadParams, "no event '" + name + "' on " + type.FullName + suffix);
        }

        // A delegate of `handlerType` that calls `sink` with the invocation's
        // arguments (sender first). Raises bad_request for a delegate shape we
        // cannot build.
        public static Delegate Build(Type handlerType, Action<object[]> sink)
        {
            if (handlerType == null || sink == null)
                throw new ProtocolException(ErrorCodes.BadParams, "the event has no handler type");
            var invoke = handlerType.GetMethod("Invoke");
            if (invoke == null)
                throw new ProtocolException(ErrorCodes.BadParams, handlerType.Name + " is not a delegate type");

            var parameters = invoke.GetParameters();
            if (parameters.Any(p => p.ParameterType.IsByRef))
                throw new ProtocolException(ErrorCodes.BadParams,
                    handlerType.Name + " has a ref/out parameter and cannot be listened to");

            var id = Interlocked.Increment(ref _sinks);
            Type type;
            MethodInfo handle;
            lock (Module)
            {
                var typeBuilder = Module.DefineType("Sink" + id.ToString(System.Globalization.CultureInfo.InvariantCulture),
                    TypeAttributes.Public | TypeAttributes.Sealed | TypeAttributes.Abstract);
                var field = typeBuilder.DefineField(SinkField, typeof(Action<object[]>),
                    FieldAttributes.Public | FieldAttributes.Static);
                var method = typeBuilder.DefineMethod(HandleMethod,
                    MethodAttributes.Public | MethodAttributes.Static | MethodAttributes.HideBySig,
                    invoke.ReturnType,
                    parameters.Select(p => p.ParameterType).ToArray());

                var il = method.GetILGenerator();
                il.Emit(OpCodes.Ldsfld, field);
                il.Emit(OpCodes.Ldc_I4, parameters.Length);
                il.Emit(OpCodes.Newarr, typeof(object));
                for (var i = 0; i < parameters.Length; i++)
                {
                    il.Emit(OpCodes.Dup);
                    il.Emit(OpCodes.Ldc_I4, i);
                    EmitLdarg(il, i);
                    if (parameters[i].ParameterType.IsValueType)
                        il.Emit(OpCodes.Box, parameters[i].ParameterType);
                    il.Emit(OpCodes.Stelem_Ref);
                }
                il.Emit(OpCodes.Callvirt, typeof(Action<object[]>).GetMethod("Invoke"));
                if (invoke.ReturnType != typeof(void))
                    EmitDefault(il, invoke.ReturnType);
                il.Emit(OpCodes.Ret);

                // CreateTypeInfo, not CreateType: the latter is not in the
                // netstandard2.0 facade, the former is on every target we build.
                type = typeBuilder.CreateTypeInfo();
                handle = type.GetMethod(HandleMethod);
            }
            type.GetField(SinkField).SetValue(null, sink);
            return Delegate.CreateDelegate(handlerType, handle);
        }

        // `ldarg` takes a two-byte operand; the one-int overload of Emit would
        // write four. Use the short forms, which is also what a C# compiler does.
        static void EmitLdarg(ILGenerator il, int index)
        {
            switch (index)
            {
                case 0: il.Emit(OpCodes.Ldarg_0); break;
                case 1: il.Emit(OpCodes.Ldarg_1); break;
                case 2: il.Emit(OpCodes.Ldarg_2); break;
                case 3: il.Emit(OpCodes.Ldarg_3); break;
                default:
                    if (index <= byte.MaxValue) il.Emit(OpCodes.Ldarg_S, (byte)index);
                    else il.Emit(OpCodes.Ldarg, (short)index);
                    break;
            }
        }

        static void EmitDefault(ILGenerator il, Type type)
        {
            if (type.IsValueType)
            {
                var local = il.DeclareLocal(type);
                il.Emit(OpCodes.Ldloca, local);
                il.Emit(OpCodes.Initobj, type);
                il.Emit(OpCodes.Ldloc, local);
                return;
            }
            il.Emit(OpCodes.Ldnull);
        }

        // The first-level public property values of an event's argument object,
        // as text: what a listener wants to see without a second IDE call.
        public static Dictionary<string, object> Snapshot(object args)
        {
            var result = new Dictionary<string, object>
            {
                { "type", args == null ? null : args.GetType().FullName },
            };
            var properties = new Dictionary<string, object>();
            result["properties"] = properties;
            if (args == null) return result;

            PropertyInfo[] found;
            try { found = args.GetType().GetProperties(BindingFlags.Public | BindingFlags.Instance); }
            catch (Exception) { return result; }

            var count = 0;
            foreach (var property in found)
            {
                if (count >= MaxArgProperties) break;
                if (property.GetIndexParameters().Length != 0) continue;
                var getter = property.GetGetMethod();
                if (getter == null) continue;
                object value;
                try { value = getter.Invoke(args, null); }
                catch (Exception e)
                {
                    properties[property.Name] = "<" + e.GetType().Name + ">";
                    count++;
                    continue;
                }
                properties[property.Name] = Readable(value);
                count++;
            }
            return result;
        }

        // A value as text, cheaply: a sequence becomes its count and preview.
        static string Readable(object value)
        {
            if (value == null) return null;
            var text = value as string;
            if (text != null) return DevReflection.Text(text);
            var sequence = value as IEnumerable;
            if (sequence != null)
            {
                var items = DevReflection.Preview(sequence, 0);
                return "[" + items.Count + " item(s)] " + string.Join(", ",
                    items.Take(5).Select(i => Convert.ToString(i is IDictionary<string, object> d ? d["to_string"] : i)));
            }
            return DevReflection.Text(value);
        }
    }
}
