// `project.device_types {filter?}`: the device descriptions this IDE has
// installed (IDeviceRepository.GetAllDevices), each with the type, id and
// version `project.change_device` takes; `filter` keeps those whose name,
// vendor or id contains it, whatever its casing.  Read-only.
//
// `project.change_device {device?, type, id, version?}`: the IDE's Update
// Device on one device (default: the one above the active application) -- its
// batch command `device replace` with the arguments the device catalog gives
// it (project handle, type, id, version, device guid), so the device's
// parameters, its objects and libraries follow the new description as the
// menu command makes them.  No version: the highest one installed for the type
// and id.  Refused while online or denied, like every write.
using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        public Dictionary<string, object> DeviceTypes(string filter)
        {
            var found = new List<Dictionary<string, object>>();
            foreach (var description in InstalledDevices())
            {
                var entry = DescriptionEntry(description);
                if (filter.Length > 0 && !new[] { "name", "vendor", "id" }.Any(key =>
                    Convert.ToString(entry[key]).IndexOf(filter, StringComparison.OrdinalIgnoreCase) >= 0)) continue;
                found.Add(entry);
            }
            var sorted = found.OrderBy(entry => Convert.ToString(entry["name"]), StringComparer.OrdinalIgnoreCase)
                .ThenBy(entry => Convert.ToString(entry["version"]), StringComparer.Ordinal).Cast<object>().ToList();
            return new Dictionary<string, object> { { "devices", sorted }, { "count", sorted.Count } };
        }

        public Dictionary<string, object> ChangeDevice(string deviceName, int type, string id, string version)
        {
            RefuseWhileOnline();
            RequirePermission("project.change_device");
            var handle = ProjectHandle();
            var deviceIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject");
            var device = deviceName.Length == 0 ? LoginDevice(handle, deviceIface) : DeviceNamed(deviceName);
            var target = InstalledDevices().Select(DescriptionEntry)
                .Where(entry => (int)entry["type"] == type && string.Equals(Convert.ToString(entry["id"]), id, StringComparison.OrdinalIgnoreCase))
                .ToList();
            if (version.Length > 0) target = target.Where(entry => Convert.ToString(entry["version"]) == version).ToList();
            if (target.Count == 0)
                throw new ProtocolException(ErrorCodes.BadParams, "no installed device description has type " + type + ", id '" + id + "'"
                    + (version.Length > 0 ? ", version " + version : "") + "; cts project device-types lists the installed ones");
            var chosen = target.OrderBy(entry => VersionKey(Convert.ToString(entry["version"]))).Last();
            var before = IdentificationEntry(Prop(deviceIface, Prop(_metaObjectIface, ReadMeta(handle, device), "Object"), "DeviceIdentification"));
            RunBatchCommand("device replace", handle.ToString(), type.ToString(), Convert.ToString(chosen["id"]),
                Convert.ToString(chosen["version"]), Id(device));
            var after = IdentificationEntry(Prop(deviceIface, Prop(_metaObjectIface, ReadMeta(handle, device), "Object"), "DeviceIdentification"));
            return new Dictionary<string, object>
            {
                { "device", NameOf(ReadMeta(handle, device)) },
                { "guid", Id(device) },
                { "before", before },
                { "after", after },
                { "name", chosen["name"] },
            };
        }

        // Every installed description; the repository answers its own collection type.
        IEnumerable<object> InstalledDevices()
        {
            var repositoryIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceRepository");
            var all = NeedMethod(repositoryIface, "GetAllDevices", Type.EmptyTypes, "IDeviceRepository.GetAllDevices is not present in this IDE");
            var devices = all.Invoke(SystemInstance("_3S.CoDeSys.DeviceObject.IDeviceRepository"), null) as IEnumerable;
            return devices == null ? Enumerable.Empty<object>() : devices.Cast<object>().Where(device => device != null);
        }

        static Dictionary<string, object> DescriptionEntry(object description)
        {
            var descriptionIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceDescription");
            var info = Prop(descriptionIface, description, "DeviceInfo");
            var infoIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceInfo");
            var entry = IdentificationEntry(Prop(descriptionIface, description, "DeviceIdentification"));
            entry["name"] = Convert.ToString(Prop(infoIface, info, "Name"));
            entry["vendor"] = Convert.ToString(Prop(infoIface, info, "Vendor"));
            return entry;
        }

        static Dictionary<string, object> IdentificationEntry(object identification)
        {
            var iface = FindType("_3S.CoDeSys.Core.Device.IDeviceIdentification");
            return new Dictionary<string, object>
            {
                { "type", (int)Prop(iface, identification, "Type") },
                { "id", Convert.ToString(Prop(iface, identification, "Id")) },
                { "version", Convert.ToString(Prop(iface, identification, "Version")) },
            };
        }

        // A version's parts as numbers, so 4.11.0.0 sorts after 4.9.0.0; a part
        // that is no number sorts first.
        static string VersionKey(string version)
        {
            return string.Join(".", version.Split('.').Select(part => int.TryParse(part, out var number) ? number.ToString("D9") : "000000000"));
        }

        Guid DeviceNamed(string name)
        {
            var matches = ((IEnumerable)Devices(name)["devices"]).Cast<Dictionary<string, object>>()
                .Where(device => string.Equals(Convert.ToString(device["name"]), name, StringComparison.OrdinalIgnoreCase)).ToList();
            if (matches.Count != 1)
                throw new ProtocolException(ErrorCodes.BadParams, matches.Count == 0
                    ? "no device named '" + name + "'; cts project list-devices names them"
                    : "two devices are named '" + name + "'");
            return new Guid(Convert.ToString(matches[0]["guid"]));
        }
    }
}
