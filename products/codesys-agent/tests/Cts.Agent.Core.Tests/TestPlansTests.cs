using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // test.run against a fake agent: the plan's steps become the agent's own
    // calls, waits go to the caller's sleep, and the answer is what verify reads.
    public sealed class TestPlansTests : IDisposable
    {
        readonly string _folder = Path.Combine(Path.GetTempPath(), "cts-test-plans-" + Guid.NewGuid().ToString("N"));
        readonly List<string> _calls = new List<string>();
        readonly Dictionary<string, object> _plc = new Dictionary<string, object>();
        string _active = "App";
        bool _loggedIn = true;
        long _now;

        public TestPlansTests()
        {
            Directory.CreateDirectory(Path.Combine(_folder, TestPlans.Folder));
        }

        public void Dispose()
        {
            Directory.Delete(_folder, true);
        }

        void Plan(string name, string json)
        {
            File.WriteAllText(Path.Combine(_folder, TestPlans.Folder, name), json);
        }

        Dictionary<string, object> Run(string file = "")
        {
            return TestPlans.Run(_folder, file, Fake, ms => _now += ms, () => _now);
        }

        IDictionary<string, object> Fake(string method, Dictionary<string, object> parameters)
        {
            _calls.Add(method + " " + Json.Serialize(parameters));
            switch (method)
            {
                case "app.login": return new Dictionary<string, object> { { "application", _active }, { "state", "stop" } };
                case "app.start": return new Dictionary<string, object> { { "application_state", "run" } };
                case "app.reset": return new Dictionary<string, object> { { "application_state", "stop" } };
                case "vars.write":
                    foreach (var pair in (IDictionary<string, object>)parameters["values"]) _plc[pair.Key] = pair.Value;
                    return new Dictionary<string, object>
                    {
                        { "logged_in", _loggedIn },
                        { "results", new List<object> { new Dictionary<string, object> { { "ok", true } } } },
                    };
                case "vars.read":
                    var name = (string)((IList<object>)parameters["names"])[0];
                    object value;
                    var row = _plc.TryGetValue(name, out value)
                        ? new Dictionary<string, object> { { "ok", true }, { "value", value } }
                        : new Dictionary<string, object> { { "ok", false }, { "error", new Dictionary<string, object> { { "message", "not exported" } } } };
                    return new Dictionary<string, object> { { "logged_in", _loggedIn }, { "results", new List<object> { row } } };
            }
            throw new ProtocolException(ErrorCodes.UnknownMethod, method);
        }

        static IDictionary<string, object> Map(object value)
        {
            return (IDictionary<string, object>)value;
        }

        static IDictionary<string, object> Result(Dictionary<string, object> answer, int index = 0)
        {
            return Map(((IList<object>)answer["results"])[index]);
        }

        static IDictionary<string, object> TestOf(IDictionary<string, object> result, int index = 0)
        {
            return Map(((IList<object>)result["tests"])[index]);
        }

        [Fact]
        public void APassingPlanWritesWaitsReadsAndSaysSuccess()
        {
            _plc["MAIN.r"] = 13.0005;
            Plan("add.json", "{\"name\":\"add\",\"application\":\"App\",\"tests\":[{\"name\":\"sum\",\"steps\":["
                + "{\"action\":\"write\",\"variable\":\"MAIN.a\",\"value\":10},"
                + "{\"action\":\"write\",\"variable\":\"MAIN.x\",\"value\":true},"
                + "{\"action\":\"wait\",\"ms\":200},"
                + "{\"action\":\"read\",\"variable\":\"MAIN.r\",\"expected\":13,\"tolerance\":0.001}]}]}");

            var answer = Run();

            Assert.Equal("SUCCESS", answer["status"]);
            Assert.Equal(1L, Map(answer["summary"])["ok"]);
            Assert.Equal(0L, Map(answer["summary"])["not_ok"]);
            Assert.Equal(200L, _now);
            Assert.Equal(new[]
            {
                "app.login {}",
                "app.start {}",
                "vars.write {\"values\":{\"MAIN.a\":\"10\"}}",
                "vars.write {\"values\":{\"MAIN.x\":\"TRUE\"}}",
                "vars.read {\"names\":[\"MAIN.r\"]}",
            }, _calls);
            Assert.Equal("add.json", Map(((IList<object>)answer["files"])[0])["file"]);
        }

        [Fact]
        public void AWrongValueFailsItsTestAndStopsThePlan()
        {
            _plc["MAIN.r"] = 12L;
            Plan("p.json", "{\"application\":\"App\",\"tests\":["
                + "{\"name\":\"one\",\"steps\":[{\"action\":\"read\",\"variable\":\"MAIN.r\",\"expected\":13}]},"
                + "{\"name\":\"two\",\"steps\":[{\"action\":\"wait\",\"ms\":1}]}]}");

            var answer = Run();

            Assert.Equal("FAIL", answer["status"]);
            var result = Result(answer);
            Assert.Single((IList<object>)result["tests"]);
            Assert.Equal("read MAIN.r: expected 13, got 12", TestOf(result)["error"]);
        }

        [Fact]
        public void ContinueOnFailRunsTheNextTest()
        {
            _plc["MAIN.r"] = 12L;
            Plan("p.json", "{\"application\":\"App\",\"continue_on_fail\":true,\"tests\":["
                + "{\"name\":\"one\",\"steps\":[{\"action\":\"assert\",\"variable\":\"MAIN.r\",\"expected\":13}]},"
                + "{\"name\":\"two\",\"steps\":[{\"action\":\"read\",\"variable\":\"MAIN.r\",\"expected_min\":10,\"expected_max\":12}]}]}");

            var answer = Run();

            var summary = Map(answer["summary"]);
            Assert.Equal(1L, summary["ok"]);
            Assert.Equal(1L, summary["not_ok"]);
            Assert.Equal("PASS", TestOf(Result(answer), 1)["status"]);
        }

        [Fact]
        public void BoolsAndTextCompareAsTheIdeShowsThem()
        {
            _plc["MAIN.x"] = true;
            _plc["MAIN.e"] = "E_Mode.Run";
            Plan("p.json", "{\"application\":\"App\",\"tests\":[{\"steps\":["
                + "{\"action\":\"assert\",\"variable\":\"MAIN.x\",\"expected\":true},"
                + "{\"action\":\"assert\",\"variable\":\"MAIN.e\",\"expected\":\"e_mode.run\"}]}]}");

            Assert.Equal("SUCCESS", Run()["status"]);
        }

        [Fact]
        public void APlanForAnotherApplicationIsRefusedNotSwitchedTo()
        {
            _active = "Other";
            Plan("p.json", "{\"application\":\"App\",\"tests\":[{\"steps\":[{\"action\":\"wait\"}]}]}");

            var answer = Run();

            Assert.Equal("FAIL", answer["status"]);
            Assert.Contains("the active application is 'Other'", (string)Result(answer)["error"]);
            Assert.Equal(new[] { "app.login {}" }, _calls);
        }

        [Fact]
        public void ColdResetRunsOnceAndStartFalseLeavesTheApplication()
        {
            Plan("a.json", "{\"application\":\"App\",\"reset\":\"cold\",\"ip\":\"192.0.2.10\",\"tests\":[{\"steps\":[{\"action\":\"wait\"}]}]}");
            Plan("b.json", "{\"application\":\"App\",\"reset\":\"cold\",\"start\":false,\"tests\":[{\"steps\":[{\"action\":\"wait\"}]}]}");

            Run();

            Assert.Equal(new[]
            {
                "app.login {\"ip\":\"192.0.2.10\"}",
                "app.reset {\"kind\":\"cold\"}",
                "app.start {}",
                "app.login {}",
            }, _calls);
        }

        [Fact]
        public void TheTimeoutCutsAWaitAndFailsTheNextStep()
        {
            Plan("p.json", "{\"application\":\"App\",\"timeout\":1000,\"tests\":[{\"continue_on_fail\":true,\"steps\":["
                + "{\"action\":\"wait\",\"ms\":5000},{\"action\":\"wait\",\"ms\":1}]}]}");

            var answer = Run();

            Assert.Equal(1000L, _now);
            Assert.Equal("plan timeout exceeded", TestOf(Result(answer))["error"]);
        }

        [Fact]
        public void NoSessionSaysNotConnected()
        {
            _loggedIn = false;
            Plan("p.json", "{\"application\":\"App\",\"tests\":[{\"steps\":[{\"action\":\"read\",\"variable\":\"MAIN.r\"}]}]}");

            Assert.StartsWith("Not connected", (string)TestOf(Result(Run()))["error"]);
        }

        [Fact]
        public void ABrokenPlanFailsAloneAndTheOthersRun()
        {
            Plan("a.json", "{not json");
            Plan("b.json", "{\"application\":\"App\",\"tests\":[{\"steps\":[{\"action\":\"wait\"}]}]}");

            var answer = Run();

            var files = ((IList<object>)answer["files"]).Select(Map).ToList();
            Assert.Equal(new[] { "a.json", "b.json" }, files.Select(f => f["file"]));
            Assert.Equal(new object[] { false, true }, files.Select(f => f["ok"]));
            Assert.Equal(2L, Map(answer["summary"])["files"]);
        }

        [Fact]
        public void AnUnknownActionFailsItsStep()
        {
            Plan("p.json", "{\"application\":\"App\",\"tests\":[{\"steps\":[{\"action\":\"jump\"}]}]}");

            Assert.StartsWith("Unknown action: 'jump'", (string)TestOf(Result(Run()))["error"]);
        }

        [Fact]
        public void MissingPlansAreRefused()
        {
            Assert.Equal(ErrorCodes.BadParams, Assert.Throws<ProtocolException>(() => Run()).Code);
            Assert.Contains("Test plan not found", Assert.Throws<ProtocolException>(() => Run("none.json")).Message);
            Directory.Delete(Path.Combine(_folder, TestPlans.Folder));
            Assert.Contains("No .test folder", Assert.Throws<ProtocolException>(() => Run()).Message);
        }
    }
}
