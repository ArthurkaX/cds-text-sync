using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Cts.Trend;
using Xunit;

namespace Cts.Agent.Tests
{
    // What trace.set takes, and the table cts trace pull makes of the
    // samples trace.samples answers.
    public sealed class TraceTests
    {
        static TraceRequest Parse(params (string key, object value)[] parameters) =>
            TraceRequest.Parse(new Request(1, "trace.set", parameters.ToDictionary(pair => pair.key, pair => pair.value)));

        static string Refused(params (string key, object value)[] parameters)
        {
            var error = Assert.Throws<ProtocolException>(() => Parse(parameters));
            Assert.Equal(ErrorCodes.BadParams, error.Code);
            return error.Message;
        }

        [Fact]
        public void ASettingLeftOutStaysAsTheTraceHasIt()
        {
            var request = Parse();
            Assert.Null(request.Variables);
            Assert.Null(request.Task);
            Assert.Null(request.Edge);
            Assert.Null(request.Condition);
            Assert.Null(request.Post);
            Assert.False(request.NoTrigger);
        }

        [Fact]
        public void TheEdgeIsTheIdesAndAnEmptyConditionClearsIt()
        {
            var request = Parse(("variables", new List<object> { "GVL_IO.rLevel", "PLC_PRG.fbPump.xRun" }), ("trigger", "GVL_IO.xAlarm"),
                ("edge", "falling"), ("level", " 15 "), ("post", 0L), ("condition", ""));

            Assert.Equal(new[] { "GVL_IO.rLevel", "PLC_PRG.fbPump.xRun" }, request.Variables);
            Assert.Equal("Negative", request.Edge);
            Assert.Equal("15", request.Level);
            Assert.Equal(0, request.Post);
            Assert.Equal("", request.Condition);
            Assert.Equal("falling", TraceRequest.EdgeName("Negative"));
            Assert.Equal("none", TraceRequest.EdgeName("None"));
        }

        [Fact]
        public void ANameWithoutItsPouOrGvlIsNoVariable()
        {
            Assert.Contains("'rLevel' is no variable", Refused(("variables", new List<object> { "rLevel" })));
            Assert.Contains("needs a variable", Refused(("variables", new List<object>())));
            Assert.Contains("no variable to trigger on", Refused(("trigger", "x AND y")));
            Assert.Contains("give one of them", Refused(("trigger", "GVL_IO.xAlarm"), ("no_trigger", true)));
            Assert.Contains("edge takes rising, falling, both", Refused(("edge", "up")));
            Assert.Contains("'every' takes 1 or more", Refused(("every", 0L)));
            Assert.Contains("'task' is empty", Refused(("task", " ")));
        }

        static Dictionary<string, object> Column(string name, string type, long[] times, params object[] values) => new Dictionary<string, object>
        {
            { "name", name }, { "type", type }, { "t", times.Cast<object>().ToList() }, { "v", values.ToList() },
        };

        [Fact]
        public void TheTableHasARowPerTimeAndAColumnPerVariable()
        {
            var table = TraceTable.Of(new Dictionary<string, object>
            {
                { "variables", new List<object>
                    {
                        Column("GVL_IO.rLevel", "real", new long[] { 0, 10, 20 }, 1.5, 2.0, 2.0),
                        Column("GVL_IO.sName", "string", new long[] { 10, 20 }, "a,b", "c"),
                    } },
            });

            Assert.Equal("ms", table.Unit);
            Assert.Equal(20, table.Span);
            var file = Path.Combine(Path.GetTempPath(), "cts-trace-" + Guid.NewGuid().ToString("N") + ".csv");
            try
            {
                table.Write(file);
                Assert.Equal("t_ms,GVL_IO.rLevel,GVL_IO.sName\n0,1.5,\n10,2,\"a,b\"\n20,2,c\n", File.ReadAllText(file));
            }
            finally { File.Delete(file); }
            Assert.Equal(new[]
            {
                "GVL_IO.rLevel  REAL  first 1.5 last 2 min 1.5 max 2 changes 1: 10 ms 1.5->2",
                "GVL_IO.sName  STRING  first \"a,b\" last c changes 1: 20 ms \"a,b\"->c",
            }, table.Summary());
        }

        [Fact]
        public void AVariableThatChangesOftenHasOnlyItsCountAndOneWithoutSamplesSaysSo()
        {
            var times = Enumerable.Range(0, TraceTable.ListedChanges + 2).Select(at => (long)at).ToArray();
            var table = TraceTable.Of(new Dictionary<string, object>
            {
                { "microseconds", true },
                { "variables", new List<object>
                    {
                        Column("GVL_IO.nCount", "udint", times, times.Cast<object>().ToArray()),
                        Column("GVL_IO.xRun", "bool", new long[0]),
                    } },
            });

            Assert.Equal("us", table.Unit);
            Assert.Equal(new[]
            {
                "GVL_IO.nCount  UDINT  first 0 last 11 min 0 max 11 changes 11",
                "GVL_IO.xRun  BOOL  no samples",
            }, table.Summary());
        }
    }
}
