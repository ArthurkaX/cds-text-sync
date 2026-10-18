using System.Collections.Generic;
using System.IO;
using Cts.Agent;

namespace Cts.Cli
{
    internal static class RawCommand
    {
        // The short names the guides and the agent's own hints give
        // (`cts raw list_devices`), for the agent's methods.
        static readonly Dictionary<string, string> Names = new Dictionary<string, string>
        {
            ["agent_ping"] = "ping",
            ["build"] = "app.build",
            ["list_devices"] = "project.devices",
            ["project_close"] = "project.close",
            ["project_list"] = "project.list",
            ["project_open"] = "project.open",
            ["plc_crc"] = "app.crc",
            ["plc_log"] = "plc.log",
            ["plc_loggers"] = "plc.loggers",
            ["run_tests"] = "test.run",
            ["set_credentials"] = "project.credentials",
            ["set_simulation_mode"] = "project.simulation",
            ["set_sync_folder"] = "project.syncfolder",
            ["status"] = "project.status",
        };

        internal static IDictionary<string, object> Execute(CliCall call)
        {
            var parameters = call.Options.Params.TryGetValue("raw_params", out var value)
                ? value as IDictionary<string, object> : new Dictionary<string, object>();
            foreach (var key in new[] { "input", "output", "out", "src" })
                if (parameters.TryGetValue(key, out value) && value is string path && path.Length > 0 && !Path.IsPathRooted(path))
                    parameters[key] = Path.GetFullPath(path);
            var method = call.Options.Arguments.Count == 0 ? "methods" : call.Options.Arguments[0];
            var result = Result(call.Call(Names.TryGetValue(method, out var agentMethod) ? agentMethod : method, parameters));
            return new Dictionary<string, object> { { "raw_body", Json.Serialize(result) } };
        }

        static object Result(IDictionary<string, object> answer)
            => answer.Count == 1 && answer.TryGetValue("result", out var value) ? value : answer;

        internal static Answer Build(IDictionary<string, object> data) => data.ContainsKey("raw_body") ? new Answer() : new Answer().Add("result", data);
    }
}
