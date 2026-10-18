// `plc.info` (`cts plc info`): what the PLC the active application's device
// points at is -- runtime, device, node name -- and the applications it holds,
// each with its state and the project it was downloaded from, all read
// without a login (IOnlineDevice6/8/11/17). The deny list key is `plc_files`.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        internal Dictionary<string, object> PlcInfo(int startMs)
        {
            return Connected(DenyRules.PlcFiles, "plc.info", startMs, online =>
            {
                Func<string, Type> Iface = name => FindType("_3S.CoDeSys.Core.Online." + name);
                var ident = new object[] { null, null, null };
                NeedMethod(Iface("IOnlineDevice11"), "GetTargetIdent", new[] { typeof(string).MakeByRefType(), typeof(string).MakeByRefType(), typeof(string).MakeByRefType() },
                    "IOnlineDevice11.GetTargetIdent is not present in this IDE").Invoke(online, ident);
                var stateArgs = new object[] { null, null };
                NeedMethod(Iface("IOnlineDevice6"), "ReadApplicationList", new[] { typeof(string[]).MakeByRefType(), Iface("ApplicationState").MakeArrayType().MakeByRefType() },
                    "IOnlineDevice6.ReadApplicationList is not present in this IDE").Invoke(online, stateArgs);
                var infoIface = Iface("IOnlineApplicationInfo");
                var infoArgs = new object[] { null, null };
                NeedMethod(Iface("IOnlineDevice8"), "ReadApplicationList2", new[] { typeof(string[]).MakeByRefType(), infoIface.MakeArrayType().MakeByRefType() },
                    "IOnlineDevice8.ReadApplicationList2 is not present in this IDE").Invoke(online, infoArgs);
                var states = ((string[])stateArgs[0] ?? new string[0]).Zip(((Array)stateArgs[1]).Cast<object>(), (name, state) => new { name, state })
                    .ToDictionary(a => a.name, a => Convert.ToString(a.state, CultureInfo.InvariantCulture), StringComparer.Ordinal);
                var infos = (Array)infoArgs[1];
                var compiler = FindTypeOrNull("_3S.CoDeSys.Core.Online.IOnlineApplicationInfo2");
                var applications = ((string[])infoArgs[0] ?? new string[0]).Select((name, i) =>
                {
                    var info = infos.GetValue(i);
                    var application = new Dictionary<string, object> { { "name", name }, { "state", states.TryGetValue(name, out var state) ? state : "unknown" } };
                    if (info == null) return application;
                    application["project"] = Prop(infoIface, info, "ProjectName");
                    application["last_change"] = ((DateTime)Prop(infoIface, info, "LastModification")).ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture);
                    application["profile"] = Prop(infoIface, info, "Profile");
                    if (compiler != null && compiler.IsInstanceOfType(info)) application["compiler"] = Prop(compiler, info, "CompilerVersion");
                    return application;
                }).Cast<object>().ToList();
                return new Dictionary<string, object>
                {
                    { "runtime", Convert.ToString(Prop(Iface("IOnlineDevice17"), online, "RuntimeSystemVersion"), CultureInfo.InvariantCulture) },
                    { "device", ident[0] },
                    { "vendor", ident[1] },
                    { "node", ident[2] },
                    { "applications", applications },
                };
            });
        }
    }
}
