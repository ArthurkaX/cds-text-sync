using System.Collections.Generic;

namespace Cts.Cli
{
    public static class CompareCommand
    {
        public static IDictionary<string, object> Execute(CliCall call) => ComparePlanner.Plan(call);
        public static Answer Build(IDictionary<string, object> data) => ComparePlanner.Build(data);
    }
}
