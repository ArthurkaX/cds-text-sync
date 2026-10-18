// `app.login {ip?, gateway?}` (`cts connect`): log in to the active application
// and leave what the PLC runs as it is -- no online change, no download over
// it.  A PLC without the application gets it.
//
// The login is the IDE's own, OnlineCommandHelper.LoginWithParameters
// without LoginServiceFlags, with its two questions answered here instead of
// by dialogs:
//
//   OnlineChangeDialogHandlerDelegate -- the PLC runs other code than the IDE
//     generated: online change, download or login? -> PromptOnlineChangeResult.Login,
//     what the dialog's "Login without any change" does;
//   LoginDialogHandlerDelegate -- create the application the PLC lacks ->
//     Yes; every other question (download the changed program where an
//     online change cannot go, another device's application) -> the answer
//     that changes nothing: No, Cancel or Abort, OK for a plain notice.  No
//     to a download ends the login.
//
// Every question asked is in the answer's `prompts`, so a refused login says
// why.  `cts download` is the command that changes the PLC.
//
// With `ip` the device above the active application is pointed at that PLC
// first: the gateway (`gateway`, default Gateway-1) resolves the IP to its
// router address (IGateway2.BeginResolveBlockDriverAddress, the TCP block
// driver at port 11740), and ICommunicationSettings.Gateway/Address take it,
// with the name the PLC reports, as Scan Network sets them.
// That is a project edit, refused while online like any other.  The deny
// list key is `connect_to_device`.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Linq.Expressions;
using System.Net;
using System.Net.NetworkInformation;
using System.Net.Sockets;
using System.Threading;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        //: No LoginServiceFlags: Regular would also ask to download when the
        //: PLC runs the project's code but this IDE has no record of the
        //: download; without it the IDE asks only when the code differs.
        const int ConnectLoginFlags = 0;

        //: PromptOnlineChangeResult.Login: log in without changing the PLC.
        const int LoginWithoutChange = 2;

        //: The runtime's gateway port, where a TCP block driver address points.
        const int RuntimePort = 11740;

        //: How long the gateway may take to connect or to resolve an address.
        const int GatewayMs = 30000;

        public Dictionary<string, object> Login(string ip, string gatewayName, int startMs)
        {
            var answer = new Dictionary<string, object>();
            if (!string.IsNullOrEmpty(ip))
            {
                var address = IPAddress.Parse(ip.Trim());
                var gateway = OnUi("app.login", startMs, () => Gateway(string.IsNullOrEmpty(gatewayName) ? "Gateway-1" : gatewayName));
                var target = ResolveTarget(gateway, address, startMs);
                var resolved = Prop(TargetType, target, "Address");
                var device = Convert.ToString(Prop(TargetType, target, "Name"));
                OnUi<object>("app.login", startMs, () => { PointDevice(gateway, resolved, device); return null; });
                answer["gateway"] = Convert.ToString(Prop(GatewayType, gateway, "Name"));
                answer["address"] = Convert.ToString(resolved);
                answer["ip"] = address.ToString();
            }
            foreach (var item in OnUi("app.login", startMs, () => LoginOnUi()))
                answer[item.Key] = item.Value;
            // The runtime reports the application a moment after the login.
            var timer = Stopwatch.StartNew();
            while ((string)answer["state"] == NoApplication && timer.ElapsedMilliseconds < RunSettleMs)
            {
                Thread.Sleep(RunPollMs);
                answer["state"] = OnUi("app.login", startMs, () => ApplicationStateOf(ActiveApplication()));
            }
            return answer;
        }

        Dictionary<string, object> LoginOnUi()
        {
            RequireKey(DenyRules.Connect);
            var guid = ActiveApplication();
            if (guid == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams, "the project has no active application");
            var application = NameOf(ReadMeta(ProjectHandle(), guid));
            var reused = IsLoggedIn(guid);
            var prompts = new LoginPrompts();
            if (!reused)
            {
                var helper = FindType("_3S.CoDeSys.OnlineCommands.OnlineCommandHelper");
                var flags = FindType("_3S.CoDeSys.OnlineCommands.LoginServiceFlags");
                var onlineChange = FindType("_3S.CoDeSys.OnlineCommands.OnlineChangeDialogHandlerDelegate");
                var question = FindType("_3S.CoDeSys.OnlineCommands.LoginDialogHandlerDelegate");
                var login = NeedMethod(helper, "LoginWithParameters", new[] { typeof(Guid), flags, onlineChange, question, typeof(bool) },
                    "OnlineCommandHelper.LoginWithParameters is not present in this IDE");
                object done;
                try
                {
                    done = login.Invoke(null, new[] { guid, Enum.ToObject(flags, ConnectLoginFlags),
                        Handler(onlineChange, prompts, "OnlineChange", 0), Handler(question, prompts, "Question", 1), false });
                }
                catch (Exception e) { throw new ProtocolException(ErrorCodes.Internal, "Login to " + application + ": " + Invocation.Cause(e).Message); }
                if (!(done is bool) || !(bool)done || !IsLoggedIn(guid))
                    throw new ProtocolException(ErrorCodes.Internal, "Login to " + application + " failed; the PLC was not changed. "
                        + (prompts.Asked.Count > 0
                            ? "The IDE asked: " + string.Join(" | ", prompts.Asked.Select(p => p["prompt"] + " (" + p["text"] + ", " + p["choice"] + ") -> " + p["answer"])) + " -- `cts download` creates or replaces the application."
                            : "Check that the PLC is reachable and its gateway is running."));
            }
            return new Dictionary<string, object>
            {
                { "state", ApplicationStateOf(guid) },
                { "application", application },
                { "plc", PlcTarget() },
                { "reused_session", reused },
                { "app_created", prompts.Created },
                { "prompts", prompts.Asked.Cast<object>().ToList() },
            };
        }

        // The PLC a login of the active application reaches, as its device's
        // communication settings name it: the runtime's name, else its
        // address; "simulation" in simulation mode.
        string PlcTarget()
        {
            var handle = ProjectHandle();
            var deviceIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject");
            var device = LoginDevice(handle, deviceIface);
            if (SimulationOf(handle, device, FindType("_3S.CoDeSys.DeviceObject.IDeviceObject4"))) return "simulation";
            var settings = Prop(deviceIface, Prop(_metaObjectIface, ReadMeta(handle, device), "Object"), "CommunicationSettings");
            var named = FindTypeOrNull("_3S.CoDeSys.DeviceObject.ICommunicationSettings2");
            var name = named == null ? "" : Convert.ToString(named.GetProperty("Name").GetValue(settings, null));
            return name.Length > 0 ? name : Convert.ToString(Prop(FindType("_3S.CoDeSys.DeviceObject.ICommunicationSettings"), settings, "Address"));
        }

        static Type GatewayType
        {
            get { return FindType("_3S.CoDeSys.Core.Online.IGateway"); }
        }

        object Gateway(string name)
        {
            var gateway = NeedMethod(OnlineManagerType, "GetGateway", new[] { typeof(string) }, "IOnlineManager.GetGateway is not present in this IDE")
                .Invoke(OnlineManager, new object[] { name });
            if (gateway != null) return gateway;
            var names = ((Array)NeedMethod(OnlineManagerType, "GetGateways", Type.EmptyTypes, "IOnlineManager.GetGateways is not present in this IDE")
                .Invoke(OnlineManager, null)).Cast<object>().Select(g => Convert.ToString(Prop(GatewayType, g, "Name")));
            throw new ProtocolException(ErrorCodes.BadParams, "No gateway '" + name + "' in this IDE; it has: " + string.Join(", ", names) + ".");
        }

        static Type TargetType
        {
            get { return FindType("_3S.CoDeSys.Core.Online.ITargetDescription"); }
        }

        // `app.scan {gateway?}`: the PLCs the gateway finds on its networks, as
        // the device editor's Scan Network lists them (`cts connect --scan`).
        // Read-only: no login, the device keeps its address.
        public Dictionary<string, object> Scan(string gatewayName, int startMs)
        {
            var gateway = OnUi("app.scan", startMs, () => Gateway(string.IsNullOrEmpty(gatewayName) ? "Gateway-1" : gatewayName));
            ConnectGateway(gateway, "app.scan", startMs);
            var callbackType = FindType("_3S.CoDeSys.Core.Online.EnumDevicesCallback");
            var found = new LoginTargets();
            OnDevice("app.scan", startMs, GatewayMs, "scan the network",
                () => (IAsyncResult)GatewayType.GetMethod("BeginEnumDevices").Invoke(gateway, new object[] { Handler(callbackType, found, "Found", 0), null, null }),
                pending => Ended(() => GatewayType.GetMethod("EndEnumDevices").Invoke(gateway, new object[] { pending }),
                    "Gateway '" + Prop(GatewayType, gateway, "Name") + "' cannot scan: "));
            List<object> targets;
            lock (found.Targets) targets = found.Targets.ToList();
            var plcs = targets.Select(target =>
            {
                var entry = new Dictionary<string, object>
                {
                    { "name", Convert.ToString(Prop(TargetType, target, "Name")) },
                    { "type", Convert.ToString(Prop(TargetType, target, "TypeName")) },
                    { "address", Convert.ToString(Prop(TargetType, target, "Address")) },
                };
                var ips = NodeIps(Convert.ToString(entry["address"]));
                if (ips.Count == 1) entry["ip"] = ips[0];
                var properties = Prop(TargetType, target, "Properties") as System.Collections.IDictionary;
                if (properties != null)
                    foreach (System.Collections.DictionaryEntry property in properties)
                        entry["property " + property.Key] = Convert.ToString(property.Value);
                return (object)entry;
            }).ToList();
            return new Dictionary<string, object>
            {
                { "gateway", Convert.ToString(Prop(GatewayType, gateway, "Name")) },
                { "plcs", plcs },
                { "count", plcs.Count },
            };
        }

        // The IPs a UDP node address stands for on this PC's networks: the
        // address is the host part of the PLC's IP (0021 on a /24 is .33), so
        // each IPv4 network whose host part can hold it gives one.
        static List<string> NodeIps(string address)
        {
            if (address.Length == 0 || address.Length > 8 || !uint.TryParse(address, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var host) || host == 0)
                return new List<string>();
            return NetworkInterface.GetAllNetworkInterfaces()
                .Where(nic => nic.OperationalStatus == OperationalStatus.Up && nic.NetworkInterfaceType != NetworkInterfaceType.Loopback)
                .SelectMany(nic => nic.GetIPProperties().UnicastAddresses)
                .Where(unicast => unicast.Address.AddressFamily == AddressFamily.InterNetwork && unicast.IPv4Mask != null)
                .Select(unicast =>
                {
                    var mask = Word(unicast.IPv4Mask);
                    if ((host & mask) != 0) return null;
                    var ip = (Word(unicast.Address) & mask) | host;
                    return new IPAddress(new[] { (byte)(ip >> 24), (byte)(ip >> 16), (byte)(ip >> 8), (byte)ip }).ToString();
                })
                .Where(ip => ip != null).Distinct().ToList();
        }

        static uint Word(IPAddress address)
        {
            var bytes = address.GetAddressBytes();
            return (uint)bytes[0] << 24 | (uint)bytes[1] << 16 | (uint)bytes[2] << 8 | bytes[3];
        }

        void ConnectGateway(object gateway, string method, int startMs)
        {
            if (!(bool)Prop(GatewayType, gateway, "IsConnected"))
                OnDevice(method, startMs, GatewayMs, "connect its gateway",
                    () => (IAsyncResult)GatewayType.GetMethod("BeginConnect").Invoke(gateway, new object[] { null, null }),
                    pending => Ended(() => GatewayType.GetMethod("EndConnect").Invoke(gateway, new object[] { pending }),
                        "Cannot connect gateway '" + Prop(GatewayType, gateway, "Name") + "': "));
        }

        // The runtime the gateway reaches at `ip`: the first target its TCP
        // block driver resolution reports.
        object ResolveTarget(object gateway, IPAddress ip, int startMs)
        {
            ConnectGateway(gateway, "app.login", startMs);
            var resolver = FindType("_3S.CoDeSys.Core.Online.IGateway2");
            var driver = FindType("_3S.CoDeSys.Core.Online.GwClient.BlockDriverType");
            var callbackType = FindType("_3S.CoDeSys.Core.Online.EnumDevicesCallback");
            var found = new LoginTargets();
            var bytes = new[] { (byte)(RuntimePort >> 8), (byte)(RuntimePort & 0xff) }.Concat(ip.GetAddressBytes()).ToArray();
            OnDevice("app.login", startMs, GatewayMs, "resolve " + ip,
                () => (IAsyncResult)resolver.GetMethod("BeginResolveBlockDriverAddress").Invoke(gateway, new object[]
                {
                    Enum.Parse(driver, "CmpBlkDrvTcp"), (byte)0, (byte)(bytes.Length * 8), bytes,
                    Handler(callbackType, found, "Found", 0), null, null,
                }),
                pending => Ended(() => resolver.GetMethod("EndResolveBlockDriverAddress").Invoke(gateway, new object[] { pending }),
                    "Gateway '" + Prop(GatewayType, gateway, "Name") + "' cannot resolve " + ip + ": "));
            var target = found.Targets.FirstOrDefault();
            if (target == null)
                throw new ProtocolException(ErrorCodes.Unavailable, "No PLC answers at " + ip + " through gateway '"
                    + Prop(GatewayType, gateway, "Name") + "'. " + Reach(ip));
            return target;
        }

        // What this PC sees of `ip`, to tell a network that does not reach the
        // PLC from a runtime that is not running: a ping and a TCP connect to
        // the runtime port, a second each.
        static string Reach(IPAddress ip)
        {
            bool pinged;
            try { using (var ping = new Ping()) pinged = ping.Send(ip, 1000).Status == IPStatus.Success; }
            catch (PingException) { pinged = false; }
            bool listening;
            using (var client = new TcpClient())
            {
                try { listening = client.ConnectAsync(ip, RuntimePort).Wait(1000) && client.Connected; }
                catch (AggregateException) { listening = false; }
            }
            if (listening)
                return "From this PC the runtime port " + RuntimePort + " of " + ip + " answers: the gateway is the one that does not reach it "
                    + "(a gateway on another PC, or one that needs a restart).";
            if (pinged)
                return ip + " answers ping from this PC, but nothing answers on TCP " + RuntimePort + ": is the CODESYS runtime running there?";
            return "This PC gets no answer from " + ip + " (ping, TCP " + RuntimePort + "): the network does not reach it from here "
                + "(another subnet without a route, a firewall, the PLC off). The address the PLC has on this PC's network may be another one: cts scan lists the PLCs the gateway finds, with their IP.";
        }

        // The login device now goes to the gateway and address given.  The
        // device keeps the name of the PLC it was last pointed at, and a login
        // to a PLC of another name asks whether to go on (the connect answers
        // No), so the name follows the address.
        void PointDevice(object gateway, object address, string name)
        {
            var handle = Handle(OpenProject());
            var deviceIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject");
            var settingsIface = FindType("_3S.CoDeSys.DeviceObject.ICommunicationSettings");
            Modify("app.login", Id(LoginDevice(handle, deviceIface)), (guid, meta) =>
            {
                var settings = Prop(deviceIface, Prop(_metaObjectIface, meta, "Object"), "CommunicationSettings");
                settingsIface.GetProperty("Gateway").SetValue(settings, Prop(GatewayType, gateway, "GatewayGuid"), null);
                settingsIface.GetProperty("Address").SetValue(settings, address, null);
                var named = FindTypeOrNull("_3S.CoDeSys.DeviceObject.ICommunicationSettings2");
                if (named != null) named.GetProperty("Name").SetValue(settings, name, null);
                var scanned = FindTypeOrNull("_3S.CoDeSys.DeviceObject.ICommunicationSettings5");
                var scan = scanned == null ? null : scanned.GetProperty("ScanInformation").GetValue(settings, null);
                if (scan != null) FindType("_3S.CoDeSys.DeviceObject.IScanInformation").GetProperty("DeviceName").SetValue(scan, name, null);
                return null;
            });
        }

        // A delegate of the IDE's `delegateType` that calls `target.method`
        // with as many of its arguments as the method takes, from `skip` on,
        // enums as int; an enum result comes back from the int it returns.
        static Delegate Handler(Type delegateType, object target, string method, int skip)
        {
            var invoke = delegateType.GetMethod("Invoke");
            var parameters = invoke.GetParameters().Select(p => Expression.Parameter(p.ParameterType, p.Name)).ToArray();
            var called = target.GetType().GetMethod(method);
            var arguments = called.GetParameters().Select((p, i) => (Expression)Expression.Convert(parameters[skip + i], p.ParameterType));
            Expression body = Expression.Call(Expression.Constant(target), called, arguments);
            if (invoke.ReturnType != typeof(void)) body = Expression.Convert(body, invoke.ReturnType);
            return Expression.Lambda(delegateType, body, parameters).Compile();
        }

        // The questions a login asked, each answered so that the PLC stays as
        // it is.
        public sealed class LoginPrompts
        {
            //: PromptChoice -> PromptResult: OK -> OK, OKCancel -> Cancel,
            //: YesNo and YesNoCancel -> No, RetryCancel -> Cancel,
            //: AbortRetryIgnore -> Abort.
            static readonly int[] Unchanging = { 0, 1, 3, 3, 1, 5 };

            static readonly string[] Choices = { "OK", "OKCancel", "YesNo", "YesNoCancel", "RetryCancel", "AbortRetryIgnore" };
            static readonly string[] Results = { "OK", "Cancel", "Yes", "No", "Retry", "Abort", "Ignore" };

            //: PromptResult.Yes: create the application the PLC lacks.
            const int Yes = 2;

            public List<Dictionary<string, object>> Asked { get; } = new List<Dictionary<string, object>>();

            public bool Created { get; private set; }

            public int OnlineChange()
            {
                Asked.Add(new Dictionary<string, object>
                {
                    { "prompt", "online_change" },
                    { "answer", "login" },
                    { "text", "The PLC runs other code than the project; logged in without changing it." },
                });
                return LoginWithoutChange;
            }

            public int Question(int choice, object prompt, string[] texts)
            {
                var result = choice >= 0 && choice < Unchanging.Length ? Unchanging[choice] : 1;
                if (Convert.ToString(prompt).StartsWith("QueryCreateApplication", StringComparison.Ordinal))
                {
                    result = Yes;
                    Created = true;
                }
                Asked.Add(new Dictionary<string, object>
                {
                    { "prompt", Convert.ToString(prompt) },
                    { "choice", choice >= 0 && choice < Choices.Length ? Choices[choice] : Convert.ToString(choice) },
                    { "answer", Results[result] },
                    { "text", string.Join(" ", texts ?? new string[0]).Trim() },
                });
                return result;
            }
        }

        // The targets an address resolution reports.
        public sealed class LoginTargets
        {
            public List<object> Targets { get; } = new List<object>();

            public void Found(object target)
            {
                if (target != null) lock (Targets) Targets.Add(target);
            }
        }
    }
}
