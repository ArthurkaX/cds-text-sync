using System;
using System.Collections.Generic;
using System.Linq;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        [Theory]
        [InlineData("3.4.0+8fa64f5d12345678", "3.4.0 (commit 8fa64f5d)")]
        [InlineData("4.0.0-beta.1+8fa64f5d12345678", "4.0.0-beta.1 (commit 8fa64f5d)")]
        [InlineData("3.4.0", "3.4.0")]
        public void Version_includes_short_commit_when_present(string informationalVersion, string expected)
        {
            Assert.Equal(expected, CliRun.FormatVersion(informationalVersion));
        }

        static Dictionary<string, object> Read(string value) => new Dictionary<string, object> { { "name", "x" }, { "value", value } };

        static Dictionary<string, object> Results(params Dictionary<string, object>[] rows) =>
            new Dictionary<string, object> { { "logged_in", true }, { "results", rows.Cast<object>().ToList() } };

        static Dictionary<string, object> Ok(string name, string text) =>
            new Dictionary<string, object> { { "ok", true }, { "name", name }, { "text", text } };

        static Dictionary<string, object> Bad(string name, string code, string message) => new Dictionary<string, object>
        {
            { "ok", false }, { "name", name }, { "error", new Dictionary<string, object> { { "code", code }, { "message", message } } },
        };

        // An agent that writes and answers each read with the next value the
        // variable shows; the calls it got, in order.
        static FakeHost VarsAgent(List<string> calls, Func<IDictionary<string, object>, object> write, Func<string, string> show)
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                if (method == "vars.write")
                {
                    calls.Add("write " + Json.Serialize(p["values"]));
                    return write(p);
                }
                Assert.Equal("vars.read", method);
                var name = (string)((List<object>)p["names"])[0];
                calls.Add("read " + name);
                var value = show(name);
                return value == null ? Results(Bad(name, "not_exported", "no")) : Results(Ok(name, value));
            });
            return host;
        }

        [Theory]
        [InlineData("42", "42", true)]
        [InlineData("FALSE", "false", true)]
        [InlineData("1.0", "1", true)]
        [InlineData("abc", " abc ", true)]
        [InlineData("FALSE", "TRUE", false)]
        [InlineData("TRUE", null, false)]
        [InlineData("TRUE", "1", false)]
        [InlineData("0", "INT#0", true)]
        [InlineData("1.5", "REAL#1.5", true)]
        [InlineData("INT#0", "INT#0", true)]
        [InlineData("0", "INT#1", false)]
        [InlineData("hello", "'hello'", false)]
        [InlineData("Run", "E_BenchMode.Run", true)]
        [InlineData("'it's'", "'it$'s'", true)]
        [InlineData("'x$41'", "'x$42'", false)]
        [InlineData("'a$$bA'", "'a$$b$41'", true)]
        [InlineData("'line$N'", "'line$l'", true)]
        [InlineData("\"x$0041\"", "\"xA\"", true)]
        [InlineData("'it's'", "'its'", false)]
        [InlineData("'Ab'", "'ab'", false)]
        public void The_value_comparison_does_not_guess(string written, string read, bool agree)
        {
            Assert.Equal(agree, WriteCommand.Agree(written, read));
        }

        [Fact]
        public void The_read_back_polls_until_the_plc_shows_the_value()
        {
            var clock = new FakeClock();
            var shown = new Queue<string>(new[] { "TRUE", "TRUE", "FALSE" });

            var result = WriteCommand.Confirm("X", "FALSE", "FALSE", name => Read(shown.Dequeue()), () => clock.Now, clock.Sleep);

            Assert.Equal(true, result["confirmed"]);
            Assert.Empty(shown);
            Assert.False(result.ContainsKey("written_as"));
        }

        [Fact]
        public void A_number_written_to_an_enum_is_confirmed_by_the_members_value()
        {
            var clock = new FakeClock();
            var reads = new List<string>();
            var values = new Dictionary<string, string> { { "GVL.eMode", "E_BenchMode.Run" }, { "E_BenchMode.Run", "INT#1" } };

            var result = WriteCommand.Confirm("GVL.eMode", "1", "1", name => { reads.Add(name); return Read(values[name]); }, () => clock.Now, clock.Sleep);

            Assert.Equal(true, result["confirmed"]);
            Assert.Equal(new[] { "GVL.eMode", "E_BenchMode.Run" }, reads);
        }

        [Fact]
        public void A_write_that_never_shows_is_not_confirmed_and_an_unreadable_one_is_not_polled()
        {
            var clock = new FakeClock();
            var reads = 0;

            var stale = WriteCommand.Confirm("X", "FALSE", "FALSE", name => Read("TRUE"), () => clock.Now, clock.Sleep);
            var unreadable = WriteCommand.Confirm("X", "1", "1", name =>
            {
                reads++;
                return new Dictionary<string, object> { { "unavailable", "boom" } };
            }, () => clock.Now, clock.Sleep);

            Assert.Equal(false, stale["confirmed"]);
            Assert.StartsWith("the PLC still reports 'TRUE' after writing 'FALSE' and waiting 2s;", (string)stale["note"]);
            Assert.Equal(false, unreadable["confirmed"]);
            Assert.False(unreadable.ContainsKey("note"));
            Assert.Equal(1, reads);
        }

        [Fact]
        public void One_pair_is_written_and_read_back_in_the_ides_spelling()
        {
            var calls = new List<string>();
            var host = VarsAgent(calls, p => Results(Ok("GVL.sName", "'hello'")), name => "'hello'");

            var (code, output, _) = Run(host, "write", "GVL.sName", "hello");
            var json = JsonOf(Run(host, "write", "GVL.sName", "hello", "--json").output);

            Assert.Equal(0, code);
            Assert.Equal("ok write name=GVL.sName value='hello' confirmed=true written_as='hello'\nide-1 · no project\n", output);
            Assert.Equal(new[] { "write {\"GVL.sName\":\"hello\"}", "read GVL.sName" }, calls.Take(2));
            Assert.Equal(true, json["confirmed"]);
            Assert.Equal("'hello'", ((IDictionary<string, object>)json["read_back"])["value"]);
        }

        [Fact]
        public void Several_pairs_are_one_write_each_read_back_and_a_negative_number_is_a_value()
        {
            var calls = new List<string>();
            var host = VarsAgent(calls, p => Results(Ok("GVL.a", "INT#-5"), Ok("GVL.b", "TRUE")),
                name => name == "GVL.a" ? "INT#-5" : "TRUE");

            var (code, output, _) = Run(host, "write", "GVL.a", "-5", "GVL.b", "true");

            Assert.Equal(0, code);
            Assert.Equal("ok write count=2 confirmed=2\nGVL.a = INT#-5\nGVL.b = TRUE\nide-1 · no project\n", output);
            Assert.Equal(new[] { "write {\"GVL.a\":\"-5\",\"GVL.b\":\"true\"}", "read GVL.a", "read GVL.b" }, calls);
        }

        [Fact]
        public void A_pair_the_ide_refuses_writes_none_and_names_it()
        {
            var host = VarsAgent(new List<string>(), p => Results(
                Bad("GVL.a", "not_written", "not written: GVL.b could not be written with it"),
                Bad("GVL.b", "bad_value", "'x' is not a value for GVL.b (BOOL)")), name => throw new InvalidOperationException());

            var (code, output, error) = Run(host, "write", "GVL.a", "5", "GVL.b", "x");

            Assert.Equal(1, code);
            Assert.Contains("nothing written; GVL.b: 'x' is not a value for GVL.b (BOOL)", output);
            Assert.DoesNotContain("GVL.a:", output + error);
        }

        [Fact]
        public void A_write_without_a_session_or_a_value_is_refused()
        {
            var host = VarsAgent(new List<string>(), p => new Dictionary<string, object> { { "logged_in", false } }, name => null);

            var (code, output, _) = Run(host, "write", "GVL.a", "5");
            var odd = Run(host, "write", "GVL.a", "5", "GVL.b");
            var twice = Run(host, "write", "GVL.a", "5", "GVL.a", "6");

            Assert.Equal(1, code);
            Assert.StartsWith("error write cause=\"Not connected: the PLC session is not logged in.", output);
            Assert.Contains("\nNext: cts connect\n", output);
            Assert.Equal(2, odd.code);
            Assert.Contains("GVL.b has no value", odd.error);
            Assert.Equal(2, twice.code);
            Assert.Contains("a name is written twice", twice.error);
        }

        [Fact]
        public void An_unreadable_read_back_says_why()
        {
            var host = VarsAgent(new List<string>(), p => Results(Ok("GVL.a", "5")), name => null);

            var (_, output, _) = Run(host, "write", "GVL.a", "5");

            Assert.Equal("ok write name=GVL.a value=unreadable confirmed=false\nRead variable error: 'GVL.a' is not exported to the "
                + "online application. It may be misspelled, not declared as a symbol, or not compiled into the PLC.\nide-1 · no project\n", output);
        }

        [Fact]
        public void A_command_without_arguments_refuses_a_word()
        {
            var (code, _, error) = Run(new FakeHost(), "ping", "extra");

            Assert.Equal(2, code);
            Assert.Contains("unrecognized argument extra", error);
            Assert.StartsWith("usage: cts write NAME VALUE [NAME VALUE ...] [--timeout SECONDS]", Run(new FakeHost(), "write", "-h").output);
        }
    }
}
