using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Fact]
        public void Raw_sends_json_values_and_writes_the_agent_result_as_json()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, parameters) =>
            {
                Assert.Equal("probe", method);
                Assert.Equal(42L, parameters["count"]);
                Assert.Equal(true, parameters["enabled"]);
                Assert.Equal("two words", parameters["name"]);
                return new Dictionary<string, object> { { "answer", "yes" } };
            });
            var (code, output, _) = Run(host, "raw", "probe", "--count", "42", "--enabled", "--name", "two words");
            Assert.Equal(0, code);
            Assert.Equal("{\"answer\":\"yes\"}\n", output);
        }

        [Fact]
        public void Raw_sends_a_guid_that_starts_like_a_number_as_a_string()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, parameters) =>
            {
                Assert.Equal("1e8859dc-c2d4-4495-98ad-353831d0a959", parameters["parent_guid"]);
                Assert.Equal("123e4567-e89b-12d3-a456-426614174000", parameters["guid"]);
                return new Dictionary<string, object>();
            });
            var (code, _, _) = Run(host, "raw", "objects.create", "--parent_guid", "1e8859dc-c2d4-4495-98ad-353831d0a959",
                "--guid", "123e4567-e89b-12d3-a456-426614174000");
            Assert.Equal(0, code);
        }

        [Fact]
        public void Raw_takes_the_short_name_the_guides_give()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, _) =>
            {
                Assert.Equal("project.devices", method);
                return new Dictionary<string, object> { { "result", new List<object>() } };
            });
            var (code, output, _) = Run(host, "raw", "list_devices");
            Assert.Equal(0, code);
            Assert.Equal("[]\n", output);
        }

        [Fact]
        public void Raw_without_a_method_asks_the_agent_for_its_methods()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, _) =>
            {
                Assert.Equal("methods", method);
                return new Dictionary<string, object> { { "result", new List<object> { "app.crc", "build" } } };
            });
            var (code, output, _) = Run(host, "raw");
            Assert.Equal(0, code);
            Assert.Equal("[\"app.crc\",\"build\"]\n", output);
        }
    }
}
