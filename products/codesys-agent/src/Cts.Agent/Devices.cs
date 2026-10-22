// `project.devices {device?}`: the project's devices (`cts project
// list-devices`) as the Devices view shows them -- each with
// its path, its type, the description it is (type, id, version), whether it
// simulates, and the applications below it
// with whether they are logged in and in which state.  `device` keeps the
// devices whose name contains it, whatever its casing.  Read-only.
using System;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        public Dictionary<string, object> Devices(string filter)
        {
            var handle = ProjectHandle();
            var view = ReadStructuredView(handle);
            var nodeIface = FindType("_3S.CoDeSys.Core.Objects.ISVNode");
            Func<object, bool> isApplication = n => ((Type)Prop(nodeIface, n, "ObjectType")).GetInterfaces().Any(i => i.Name == "IApplicationObject");
            var simulating = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject4");
            var deviceIdentification = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject");
            var active = ActiveApplication();
            var devices = new List<object>();
            var stack = new Stack<KeyValuePair<object, string>>(view.Roots.AsEnumerable().Reverse().Select(n => new KeyValuePair<object, string>(n, "")));
            while (stack.Count > 0)
            {
                var item = stack.Pop();
                var path = item.Value + (item.Value == "" ? "" : "/") + view.Access.NameOf(item.Key);
                foreach (var child in view.Access.ChildrenOf(item.Key).Reverse())
                    stack.Push(new KeyValuePair<object, string>(child, path));
                if (!view.IsDevice(item.Key)) continue;
                var name = view.Access.NameOf(item.Key);
                if (!string.IsNullOrEmpty(filter) && name.IndexOf(filter, StringComparison.OrdinalIgnoreCase) < 0) continue;
                var guid = view.Access.ObjectOf(item.Key);
                var device = Prop(_metaObjectIface, ReadMeta(handle, guid), "Object");
                devices.Add(new Dictionary<string, object>
                {
                    { "guid", Id(guid) },
                    { "name", name },
                    { "path", path },
                    { "type", Id(view.Access.TypeOf(item.Key)) },
                    { "description", deviceIdentification.IsInstanceOfType(device) ? IdentificationEntry(Prop(deviceIdentification, device, "DeviceIdentification")) : null },
                    { "simulation", simulating.IsInstanceOfType(device) ? Prop(simulating, device, "SimulationMode") : null },
                    { "applications", ApplicationsBelow(item.Key, view, isApplication, active) },
                });
            }
            return new Dictionary<string, object> { { "devices", devices }, { "count", devices.Count } };
        }

        // The application's "Implicit boot application on download" (its
        // Properties, Boot application): IOnlineApplicationObject5's
        // BootApplicationSettings.CreateBootApplicationOnDownload; null when
        // this IDE has none.
        object BootOnDownload(Guid guid)
        {
            try
            {
                var application = Prop(_metaObjectIface, ReadMeta(ProjectHandle(), guid), "Object");
                var owner = FindTypeOrNull("_3S.CoDeSys.Core.Online.IOnlineApplicationObject5");
                if (application == null || owner == null || !owner.IsInstanceOfType(application)) return null;
                var settings = Prop(owner, application, "BootApplicationSettings");
                return settings == null ? null : Prop(FindType("_3S.CoDeSys.Core.Online.IBootApplicationSettings"), settings, "CreateBootApplicationOnDownload");
            }
            catch (Exception) { return null; }
        }

        // The applications in a device's own subtree, not in a device below it.
        List<object> ApplicationsBelow(object device, StructuredView view, Func<object, bool> isApplication, Guid active)
        {
            var found = new List<object>();
            var pending = new Stack<object>(view.Access.ChildrenOf(device).Reverse());
            while (pending.Count > 0)
            {
                var node = pending.Pop();
                if (view.IsDevice(node)) continue;
                foreach (var child in view.Access.ChildrenOf(node).Reverse()) pending.Push(child);
                if (!isApplication(node)) continue;
                var guid = view.Access.ObjectOf(node);
                var online = ApplicationOf(guid);
                var loggedIn = online != null && Equals(Prop(OnlineApplicationType, online, "IsLoggedIn"), true);
                var entry = new Dictionary<string, object>
                {
                    { "guid", Id(guid) },
                    { "name", view.Access.NameOf(node) },
                    { "active", guid == active },
                    { "online", loggedIn },
                };
                if (loggedIn) entry["application_state"] = Convert.ToString(Prop(OnlineApplicationType, online, "ApplicationState")).ToLowerInvariant();
                var boot = BootOnDownload(guid);
                if (boot != null) entry["boot_on_download"] = boot;
                found.Add(entry);
            }
            return found;
        }
    }
}
