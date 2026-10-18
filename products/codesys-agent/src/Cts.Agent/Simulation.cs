// `project.simulation`: switch the device that holds the active application
// into or out of simulation (`cts project simulate on|off`) and save the
// project, so the next login uses it.  IDeviceObject4.SimulationMode is the
// switch the IDE's Online -> Simulation sets; like any edit it is refused
// while online, and its deny list key is `set_simulation_mode`.
using System;
using System.Collections.Generic;

namespace Cts.Agent
{
    internal sealed partial class Ide
    {
        public Dictionary<string, object> SetSimulation(bool enable)
        {
            var handle = Handle(OpenProject());
            var deviceIface = FindType("_3S.CoDeSys.DeviceObject.IDeviceObject4");
            var device = LoginDevice(handle, deviceIface);
            var before = SimulationOf(handle, device, deviceIface);
            Modify("project.simulation", Id(device), (guid, meta) =>
            {
                deviceIface.GetProperty("SimulationMode").SetValue(Prop(_metaObjectIface, meta, "Object"), enable, null);
                return null;
            });
            var answer = new Dictionary<string, object>
            {
                { "device", NameOf(ReadMeta(handle, device)) },
                { "simulation", enable },
                { "before", before },
                { "after", SimulationOf(handle, device, deviceIface) },
                { "saved", false },
            };
            try { SaveProject(); answer["saved"] = true; }
            catch (ProtocolException e) { answer["save_error"] = e.Message; }
            return answer;
        }

        // The first device above the active application: the one a login
        // with this application goes to.
        Guid LoginDevice(int handle, Type deviceIface)
        {
            var application = ActiveApplication();
            if (application == Guid.Empty)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "The project has no active application; set one in CODESYS (Set Active Application) on the device to simulate");
            for (var guid = ParentOf(ReadMeta(handle, application)); guid != Guid.Empty; guid = ParentOf(ReadMeta(handle, guid)))
                if (deviceIface.IsInstanceOfType(Prop(_metaObjectIface, ReadMeta(handle, guid), "Object"))) return guid;
            throw new ProtocolException(ErrorCodes.BadParams, "The active application is not under a device");
        }

        bool SimulationOf(int handle, Guid device, Type deviceIface)
        {
            return (bool)Prop(deviceIface, Prop(_metaObjectIface, ReadMeta(handle, device), "Object"), "SimulationMode");
        }
    }
}
