using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading;
using Cts.Cli;
using Xunit;

namespace Cts.Agent.Tests
{
    public partial class CliTests
    {
        // An agent behind a stream: each request line written gets the reply
        // the handler makes, read back as a line.
        sealed class FakeAgentStream : Stream
        {
            readonly Func<string, IDictionary<string, object>, object> _handle;
            readonly MemoryStream _replies = new MemoryStream();
            readonly StringBuilder _written = new StringBuilder();
            long _read;

            public FakeAgentStream(Func<string, IDictionary<string, object>, object> handle) { _handle = handle; }

            public List<string> Methods { get; } = new List<string>();

            public override void Write(byte[] buffer, int offset, int count)
            {
                _written.Append(Encoding.UTF8.GetString(buffer, offset, count));
                var text = _written.ToString();
                int end;
                while ((end = text.IndexOf('\n')) >= 0)
                {
                    var request = (IDictionary<string, object>)Json.Parse(text.Substring(0, end));
                    text = text.Substring(end + 1);
                    var method = (string)request["method"];
                    Methods.Add(method);
                    Dictionary<string, object> reply;
                    try
                    {
                        reply = new Dictionary<string, object> { { "id", request["id"] }, { "ok", true }, { "result", _handle(method, (IDictionary<string, object>)request["params"]) } };
                    }
                    catch (ProtocolException e)
                    {
                        reply = new Dictionary<string, object> { { "id", request["id"] }, { "ok", false }, { "error", new Dictionary<string, object> { { "code", e.Code }, { "message", e.Message }, { "data", e.Details } } } };
                    }
                    // An event first: a call must skip what is not its reply.
                    var bytes = Encoding.UTF8.GetBytes("{\"event\":\"x\",\"seq\":1}\n" + Json.Serialize(reply) + "\n");
                    _replies.Position = _replies.Length;
                    _replies.Write(bytes, 0, bytes.Length);
                }
                _written.Clear().Append(text);
            }

            public override int Read(byte[] buffer, int offset, int count)
            {
                _replies.Position = _read;
                var n = _replies.Read(buffer, offset, count);
                _read += n;
                return n;
            }

            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => true;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
        }

        // The agent's bytes a few at a time, as a pipe may hand over a large reply.
        sealed class TrickleStream : Stream
        {
            readonly Stream _inner;
            public TrickleStream(Stream inner) { _inner = inner; }
            public override int Read(byte[] buffer, int offset, int count) => _inner.Read(buffer, offset, Math.Min(count, 7));
            public override void Write(byte[] buffer, int offset, int count) => _inner.Write(buffer, offset, count);
            public override bool CanRead => true;
            public override bool CanSeek => false;
            public override bool CanWrite => true;
            public override long Length => throw new NotSupportedException();
            public override long Position { get => throw new NotSupportedException(); set => throw new NotSupportedException(); }
            public override void Flush() { }
            public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
            public override void SetLength(long value) => throw new NotSupportedException();
        }

        [Fact]
        public void A_reply_that_arrives_a_few_bytes_at_a_time_is_read_whole_and_the_next_one_too()
        {
            var text = new string('x', 5000) + "\u00e9";
            var stream = new TrickleStream(new FakeAgentStream((method, p) => new Dictionary<string, object> { { "method", method }, { "text", text } }));
            using (var conn = new AgentConnection(stream, "trickle"))
            {
                foreach (var method in new[] { "first", "second" })
                {
                    var reply = (IDictionary<string, object>)conn.Call(method, null, 5000);
                    Assert.Equal(method, reply["method"]);
                    Assert.Equal(text, reply["text"]);
                }
            }
        }

        sealed class FakeHost : IAgentHost
        {
            public readonly Dictionary<int, Func<string, IDictionary<string, object>, object>> Agents = new Dictionary<int, Func<string, IDictionary<string, object>, object>>();

            public IList<int> Pids() => Agents.Keys.OrderBy(p => p).ToList();

            public AgentConnection Open(int pid)
            {
                if (!Agents.TryGetValue(pid, out var handle)) throw new AgentException("transport", "no agent pipe for pid " + pid);
                return new AgentConnection(new FakeAgentStream(handle), "cts-agent-" + pid);
            }
        }

        static Func<string, IDictionary<string, object>, object> Agent(string projectPath, string syncFolder, Func<string, object> answer)
        {
            return Agent(projectPath, syncFolder, (method, p) => answer(method));
        }

        static Func<string, IDictionary<string, object>, object> Agent(string projectPath, string syncFolder, Func<string, IDictionary<string, object>, object> answer)
        {
            return (method, p) => method == "hello"
                ? new Dictionary<string, object>
                {
                    { "protocol", "1.0" },
                    { "project", projectPath == null ? null : new Dictionary<string, object> { { "path", projectPath }, { "sync_folder", syncFolder } } },
                    { "timeout_profile", new Dictionary<string, object>
                        {
                            { "timeouts", new Dictionary<string, object> { { "read_log", 10L } } },
                            { "default", 30L },
                        } },
                }
                : answer(method, p);
        }

        static object Pong(string method)
        {
            Assert.Equal("ping", method);
            return new Dictionary<string, object> { { "pong", true }, { "uptime_s", 4365.8119846 } };
        }

        internal static (int code, string output, string error) RunLocal(params string[] args) => Run(new FakeHost(), args);

        static (int code, string output, string error) Run(FakeHost host, params string[] args)
        {
            var output = new StringWriter();
            var error = new StringWriter();
            var command = CliCommands.Find(args);
            var code = CliRun.Run(command, args, host, null, @"C:\work\plant", output, error);
            return (code, output.ToString().Replace("\r\n", "\n"), error.ToString());
        }

        [Fact]
        public void Cts_alone_lists_every_command_and_the_help_names_none_that_is_missing()
        {
            var (code, output, _) = RunLocal();
            Assert.Equal(0, code);
            Assert.Equal(output, RunLocal("--help").output);
            foreach (var command in CliCommands.All) Assert.Contains("  " + command.Words + " ", output);
            Assert.Contains("Rules:", output);
            Assert.Contains("\ngit:\n  branch ", output);
            Assert.DoesNotContain(CliRun.HelpGroups(), group => group.Key == "other commands");
            Assert.Equal(CliCommands.All.Count, CliRun.HelpGroups().Sum(group => group.Value.Count));
            Assert.True(output.IndexOf("Start here:", StringComparison.Ordinal) < output.IndexOf("IDE and its state:", StringComparison.Ordinal));
            var named = System.Text.RegularExpressions.Regex.Matches(output, @"`!?cts (?:--target \S+ --expect-project \S+ )?([a-z][a-z-]*)")
                .Cast<System.Text.RegularExpressions.Match>().Select(m => m.Groups[1].Value).Distinct().ToList();
            Assert.NotEmpty(named);
            Assert.All(named, name => Assert.Contains(CliCommands.All, c => c.Name == name));
        }

        [Fact]
        public void A_bare_word_where_one_flag_is_needed_is_its_value()
        {
            var open = CliCommands.All.Single(c => c.Words == "project open");
            Assert.Equal(@"C:\p\a.project", CliOptions.Parse(new[] { "project", "open", @"C:\p\a.project" }, null, open).Params["path"]);
            var (code, _, error) = RunLocal("ping", "Motor1");
            Assert.Equal(2, code);
            Assert.Contains("unrecognized argument Motor1", error);
            var twice = Assert.Throws<CliFailure>(() => CliOptions.Parse(new[] { "project", "open", "a.project", "b.project" }, null, open));
            Assert.Contains("unrecognized argument b.project", twice.Message);
        }

        [Fact]
        public void An_unknown_word_after_a_command_names_its_subcommands_but_not_after_a_subcommand()
        {
            var (code, _, error) = RunLocal("dialog", "list");

            Assert.Equal(2, code);
            Assert.Contains("unrecognized argument list; plain `cts dialog`: Read the modal IDE dialog, and answer it without a click; subcommands: `cts dialog answer`", error);
            var types = CliCommands.All.Single(c => c.Words == "project device-types");
            var sub = Assert.Throws<CliFailure>(() => CliOptions.Parse(new[] { "project", "device-types", "list" }, null, types));
            Assert.DoesNotContain("subcommands", sub.Message);
        }

        [Fact]
        public void Sync_accepts_the_import_save_option()
        {
            var command = CliCommands.All.Single(item => item.Name == "sync");
            var options = CliOptions.Parse(new[] { "sync", "--save" }, null, command);

            Assert.Equal(true, options.Params["save"]);
        }

        [Fact]
        public void Version_prints_the_release_and_an_unknown_word_is_refused_by_name()
        {
            var (code, output, _) = RunLocal("--version");
            Assert.Equal(0, code);
            Assert.Matches(@"^cts \d+\.\d+\.\d+(-[0-9A-Za-z.]+)? \(commit [0-9a-f]{8}\)\n$", output);
            var unknown = RunLocal("frobnicate");
            Assert.Equal(2, unknown.code);
            Assert.Equal("", unknown.output);
            Assert.Contains("unknown command 'frobnicate'", unknown.error);
            Assert.DoesNotContain("Did you mean", unknown.error);
            Assert.Contains("unknown command 'list-devices'. Did you mean `cts project list-devices`?", RunLocal("list-devices").error);
            Assert.Equal(2, RunLocal("--json").code);
        }

        [Fact]
        public void Every_command_has_its_help_and_a_command_group_lists_its_subcommands()
        {
            var broken = CliCommands.All.Where(command =>
            {
                var (code, output, _) = RunLocal(command.Words.Split(' ').Concat(new[] { "--help" }).ToArray());
                return code != 0 || !output.StartsWith("usage: cts " + command.Words, StringComparison.Ordinal);
            }).Select(command => command.Words).ToList();
            Assert.Empty(broken);
            var group = RunLocal("visu", "--help");
            Assert.Equal(0, group.code);
            Assert.StartsWith("usage: cts visu SUBCOMMAND [options]", group.output);
            Assert.Contains("\n  visu new ", group.output);
            Assert.Contains("\n  visu from-svg ", group.output);
            var unknown = RunLocal("visu", "frobnicate");
            Assert.Equal(2, unknown.code);
            Assert.StartsWith("[ERROR] unknown subcommand 'visu frobnicate'.", unknown.error);
            Assert.Contains("\n  visu lint ", unknown.error);
        }

        [Theory]
        [InlineData(true, "true")]
        [InlineData(12.5, "12.5")]
        [InlineData(4365.8119846, "4365.81")]
        [InlineData(0.00001, "1e-05")]
        [InlineData(42L, "42")]
        [InlineData("plain", "plain")]
        [InlineData("two words", "\"two words\"")]
        [InlineData("a=b", "\"a=b\"")]
        [InlineData("say \"hi\"\nnow", "\"say \\\"hi\\\"\\nnow\"")]
        [InlineData("", "\"\"")]
        public void A_value_on_the_line_is_bare_or_quoted(object value, string expected)
        {
            Assert.Equal(expected, Verdict.Quote(value));
        }

        [Fact]
        public void A_pair_without_a_value_is_left_off_the_line()
        {
            Assert.Equal("ok permissions denied=0",
                Verdict.Line("ok", "permissions", new[] { Verdict.Pair("denied", 0L), Verdict.Pair("poll_ms", null) }));
        }

        [Fact]
        public void The_command_is_the_first_word_that_is_not_a_global_flag_or_its_value()
        {
            Assert.Equal("ping", CliOptions.CommandOf(new[] { "--target", "ide-1", "--json", "ping", "--timeout", "5" }));
            Assert.Equal("status", CliOptions.CommandOf(new[] { "--output", "json", "status" }));
            Assert.Null(CliOptions.CommandOf(new[] { "--help" }));
        }

        [Fact]
        public void Ping_answers_with_its_line_and_the_ide_it_ran_against()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(@"P:\work\.project\plant.project", @"P:\work", Pong);

            var (code, output, _) = Run(host, "ping");

            Assert.Equal(0, code);
            Assert.Equal("ok ping pong=true uptime_s=4365.81\nide-7144 · plant\n", output);
        }

        [Fact]
        public void A_failure_no_command_foresaw_ends_in_the_error_line_not_a_crash()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(@"P:\work\.project\plant.project", @"P:\work", method => throw new InvalidOperationException("fatal: the repository broke"));

            var (code, output, error) = Run(host, "ping");

            Assert.Equal(1, code);
            Assert.Equal("error ping cause=internal\n", output);
            Assert.StartsWith("[ERROR] fatal: the repository broke (InvalidOperationException ", error);
            // ping writes nothing to the project, so nothing can be left part way.
            Assert.DoesNotContain("part way", error);
        }

        [Fact]
        public void AQuestionThatStaysWhileACallRunsEndsTheWaitWithTheLineThatAnswersIt()
        {
            using (var release = new ManualResetEventSlim())
            {
                var host = new FakeHost();
                host.Agents[7144] = Agent(null, null, (method, parameters) =>
                {
                    if (method == "app.build") { release.Wait(); return new Dictionary<string, object>(); }
                    if (method == "dialog.probe") return new Dictionary<string, object> { ["dialogs"] = new List<object> { LoginDialog("3f9a1c02") } };
                    return new Dictionary<string, object>();
                });

                (int code, string output, string error) result;
                try { result = Run(host, "build"); }
                finally { release.Set(); }

                Assert.Equal(3, result.code);
                Assert.Equal("error build cause=dialog_opened\nNext: cts dialog answer --id 3f9a1c02 --choose \"Login with online change\" --press \"OK\"\n", result.output);
                Assert.Contains("app.build is still running inside the IDE", result.error);
                Assert.Contains(LoginLine, result.error);
            }
        }

        [Fact]
        public void A_command_stopped_by_a_dialog_prints_the_answer_and_dialog_once()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, method => throw new ProtocolException("dialog_blocked",
                "blocked by a dialog [id 3f9a1c02]: CODESYS - The application changed since last download",
                new Dictionary<string, object> { ["dialogs"] = new List<object> { LoginDialog("3f9a1c02") } }));

            var (code, output, error) = Run(host, "build");

            Assert.Equal(3, code);
            Assert.Equal("error build cause=dialog_blocked\nNext: cts dialog answer --id 3f9a1c02 --choose \"Login with online change\" --press \"OK\"\n", output);
            Assert.Equal("[ERROR] build did not run: a dialog is open in the IDE; answer it, then run the command again\n" + LoginLine + "\n", error);
            Assert.Equal(1, error.Split(new[] { LoginLine }, StringSplitOptions.None).Length - 1);
        }

        [Fact]
        public void A_command_stopped_by_a_dialog_that_came_and_went_names_it_and_repeats()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, method => throw ModalErrors.CameAndWent(new[] { ModalWindow.FromData(LoginDialog("3f9a1c02")) }));

            var (code, output, error) = Run(host, "build");

            Assert.Equal(3, code);
            Assert.Equal("error build cause=dialog_blocked\nNext: cts build\n", output);
            Assert.StartsWith("[ERROR] build did not run: a dialog opened and closed while the command waited: [id 3f9a1c02]", error);
            Assert.Contains("nothing is open now, so run the command again", error);
        }

        // A call over the pipe: the agent's refusal is Declined, a reply that
        // says the call never ran (busy, a dialog) is not.
        [Theory]
        [InlineData("ide_error", true)]
        [InlineData("unknown_method", true)]
        [InlineData("busy", false)]
        [InlineData("dialog_blocked", false)]
        public void A_refusal_over_the_pipe_is_declined_and_a_call_that_did_not_run_is_not(string code, bool declined)
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, method => throw new ProtocolException(code, "refused"));
            var command = CliCommands.All.Single(item => item.Name == "build");
            var options = CliOptions.Parse(new[] { "build" }, null, command);
            using (var conn = host.Open(7144))
            {
                var call = new CliCall(conn, host, command, options, new Hello(7144, new Dictionary<string, object>()), 30);
                var failure = Assert.Throws<CliFailure>(() => call.Call("project.build", null));
                Assert.Equal(declined, failure.Declined);
            }
        }

        // Each call names the project its command began with; the agent that
        // has another open by then refuses it, and the command ends there.
        [Fact]
        public void A_call_names_its_project_and_a_switched_project_ends_the_command()
        {
            var host = new FakeHost();
            var sent = new List<object>();
            host.Agents[7144] = Agent(@"C:\work\plant\A.project", null, (method, p) =>
            {
                sent.Add(p.TryGetValue("project_path", out var path) ? path : null);
                throw new ProtocolException(ErrorCodes.ProjectChanged, "the IDE has B.project open now");
            });
            var command = CliCommands.All.Single(item => item.Name == "build");
            var options = CliOptions.Parse(new[] { "build" }, null, command);
            using (var conn = host.Open(7144))
            {
                var hello = new Hello(7144, (IDictionary<string, object>)host.Agents[7144]("hello", new Dictionary<string, object>()));
                var call = new CliCall(conn, host, command, options, hello, 30);
                var failure = Assert.Throws<CliFailure>(() => call.Call("project.build", null));
                Assert.False(failure.Declined);
                Assert.Equal("IDE ide-7144 opened another project while the command ran", failure.Cause);
            }
            Assert.Equal(new object[] { @"C:\work\plant\A.project" }, sent);
        }

        [Fact]
        public void A_command_stopped_by_a_dialog_without_details_keeps_the_dialog_command()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, method => throw new ProtocolException("dialog_blocked", "blocked by a dialog"));

            var (code, output, error) = Run(host, "build");

            Assert.Equal(3, code);
            Assert.Equal("error build cause=dialog_blocked\nNext: cts dialog\n", output);
            Assert.Equal("[ERROR] build did not run: a dialog is open in the IDE; answer it, then run the command again\n", error);
        }

        [Fact]
        public void AProgressWindowDoesNotEndTheWait()
        {
            var host = new FakeHost();
            var probes = 0;
            host.Agents[7144] = Agent(null, null, (method, parameters) =>
            {
                if (method == "app.build")
                {
                    while (Volatile.Read(ref probes) < 4) Thread.Sleep(50);
                    return new Dictionary<string, object> { ["errors"] = 0L, ["warnings"] = 0L };
                }
                if (method == "dialog.probe")
                {
                    Interlocked.Increment(ref probes);
                    var progress = new ModalWindow { Id = 4, Title = "Build", Text = "Compiling...", Buttons = new[] { "Cancel" } }.ToData();
                    return new Dictionary<string, object> { ["dialogs"] = new List<object> { progress } };
                }
                return new Dictionary<string, object>();
            });

            var (code, _, error) = Run(host, "build");

            Assert.Equal(0, code);
            Assert.DoesNotContain("dialog", error);
        }

        [Fact]
        public void Json_prints_the_payload_with_the_instance_and_nothing_else()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(@"P:\work\.project\plant.project", @"P:\work", Pong);

            var (_, output, _) = Run(host, "ping", "--json");

            var payload = (IDictionary<string, object>)Json.Parse(output);
            Assert.Equal(true, payload["pong"]);
            var instance = (IDictionary<string, object>)payload["instance"];
            Assert.Equal("ide-7144", instance["id"]);
            Assert.Equal("plant", ((IDictionary<string, object>)instance["project"])["name"]);
        }

        [Fact]
        public void Agent_list_discovers_every_agent_without_picking_one()
        {
            var host = new FakeHost();
            host.Agents[7144] = (method, p) => new Dictionary<string, object>
            {
                { "protocol", "1.0" }, { "agent_version", "0.1.0" }, { "product", "CODESYS" },
                { "product_version", "3.5.22" }, { "project", new Dictionary<string, object> { { "path", @"C:\plant.project" } } },
            };
            host.Agents[7145] = (method, p) => throw new AgentException("transport", "pipe closed");

            var (code, output, _) = Run(host, "agent", "list");

            Assert.Equal(0, code);
            Assert.StartsWith("ok agent-list agents=2 answered=1\n", output);
            Assert.Contains("ide-7144  CODESYS 3.5.22  agent 0.1.0  protocol 1.0  C:\\plant.project\n", output);
            Assert.Contains("ide-7145  unreachable: transport: pipe closed\n", output);
        }

        [Fact]
        public void Agent_list_json_is_the_raw_sorted_discovery_list()
        {
            var host = new FakeHost();
            host.Agents[7144] = (method, p) => new Dictionary<string, object>
            {
                { "protocol", "1.0" }, { "product", "CODESYS" },
            };

            var (code, output, _) = Run(host, "agent", "list", "--json");

            Assert.Equal(0, code);
            Assert.StartsWith("[\n  {\n    \"pid\": 7144,\n    \"product\": \"CODESYS\",\n    \"protocol\": \"1.0\"\n  }\n]\n", output);
        }

        [Fact]
        public void Agent_list_reports_empty_and_all_unreachable_with_their_exit_codes()
        {
            var (emptyCode, emptyOutput, emptyError) = Run(new FakeHost(), "agent", "list");
            Assert.Equal(2, emptyCode);
            Assert.Empty(emptyOutput);
            Assert.Contains("No in-IDE agent found", emptyError);

            var host = new FakeHost();
            host.Agents[7144] = (method, p) => throw new AgentException("transport", "pipe closed");
            var (failedCode, failedOutput, _) = Run(host, "agent", "list");
            Assert.Equal(1, failedCode);
            Assert.StartsWith("error agent-list agents=1 answered=0\n", failedOutput);
        }

        [Fact]
        public void Pretty_prints_the_payload_readably()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, Pong);

            var (_, output, _) = Run(host, "-p", "ping");

            Assert.Equal("── ping ──\npong: true\nuptime_s: 4365.8119846\nide-7144 · no project\n", output);
        }

        [Fact]
        public void Permissions_counts_the_deny_list_and_takes_the_agents_timeout()
        {
            var host = new FakeHost();
            host.Agents[7144] = Agent(null, null, method =>
            {
                Assert.Equal("project.permissions", method);
                return new Dictionary<string, object> { { "deny", new List<object> { "delete_pou", "download" } } };
            });

            var (code, output, _) = Run(host, "permissions");

            Assert.Equal(0, code);
            Assert.StartsWith("ok permissions denied=2\n", output);
        }

        [Fact]
        public void No_agent_is_a_verdict_line_with_the_way_out_and_exit_2()
        {
            var (code, output, error) = Run(new FakeHost(), "ping");

            Assert.Equal(2, code);
            Assert.Equal("error ping cause=\"no in-IDE agent answers\"\nNext: cts project open --path <p> --launch\n", output);
            Assert.StartsWith("[ERROR] No in-IDE agent is running", error);
        }

        [Fact]
        public void No_agent_with_json_is_a_json_failure()
        {
            var (_, output, _) = Run(new FakeHost(), "ping", "--json");

            var payload = (IDictionary<string, object>)Json.Parse(output);
            Assert.Equal(false, payload["ok"]);
            Assert.Equal("ping", payload["command"]);
            Assert.Equal("no in-IDE agent answers", payload["error"]);
        }

        [Fact]
        public void With_several_agents_the_one_whose_sync_folder_holds_the_work_folder_answers()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(@"C:\work\lib\.project\lib.project", @"C:\work\lib", Pong);
            host.Agents[2] = Agent(@"C:\work\plant\.project\plant.project", @"C:\work\plant", Pong);

            var (code, output, _) = Run(host, "ping");

            Assert.Equal(0, code);
            Assert.EndsWith("ide-2 · plant\n", output);
        }

        [Fact]
        public void Several_agents_and_none_for_this_folder_name_them_all()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(@"C:\a\.project\a.project", @"C:\a", Pong);
            host.Agents[2] = Agent(@"C:\b\.project\b.project", null, Pong);

            var (code, output, error) = Run(host, "ping");

            Assert.Equal(2, code);
            Assert.StartsWith("error ping cause=\"several agents, none for this folder\"", output);
            Assert.Contains(@"ide-1 (C:\a), ide-2 (no sync folder)", error);
        }

        [Fact]
        public void Target_picks_the_ide_and_an_unknown_one_is_not_reachable()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(@"C:\a\.project\a.project", @"C:\a", Pong);
            host.Agents[2] = Agent(@"C:\b\.project\b.project", @"C:\b", Pong);

            Assert.EndsWith("ide-1 · a\n", Run(host, "ping", "--target", "ide-1").output);
            var (code, output, _) = Run(host, "--target", "9", "ping");
            Assert.Equal(1, code);
            Assert.StartsWith("error ping cause=\"agent ide-9 is not reachable\"", output);
        }

        [Fact]
        public void Expect_project_refuses_another_project()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(@"C:\a\.project\plant.project", @"C:\a", Pong);

            Assert.Equal(0, Run(host, "ping", "--expect-project", "PLANT").code);
            Assert.Equal(0, Run(host, "ping", "--expect-project", "plant.project").code);
            var (code, output, _) = Run(host, "ping", "--expect-project", "other");
            Assert.Equal(2, code);
            Assert.StartsWith("error ping cause=\"project mismatch\"", output);
        }

        [Fact]
        public void A_call_the_ide_refuses_names_why_and_exits_1()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => throw new ProtocolException("busy", "the UI thread did not start it in 30 s"));

            var (code, output, error) = Run(host, "permissions");

            Assert.Equal(1, code);
            Assert.StartsWith("error permissions cause=\"IDE ide-1 is busy and did not start project.permissions\"", output);
            Assert.Contains("the UI thread did not start it", error);
        }

        [Fact]
        public void The_agent_waits_for_the_ide_as_long_as_the_profile_sizes_the_command()
        {
            var seen = new List<IDictionary<string, object>>();
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => { seen.Add(p); return new Dictionary<string, object> { { "count", 0L } }; });

            Run(host, "read-log");
            Run(host, "save");
            Run(host, "save", "--timeout", "2.5");

            Assert.Equal(new object[] { 10000L, 30000L, 2500L }, seen.Select(p => p["start_timeout_ms"]).ToArray());
        }

        [Fact]
        public void A_commands_options_become_the_agents_parameters()
        {
            IDictionary<string, object> seen = null;
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                Assert.Equal("app.reset", method);
                seen = p;
                return new Dictionary<string, object> { { "state", "reset" }, { "kind", p.TryGetValue("kind", out var kind) ? kind : "warm" }, { "application", "App" }, { "application_state", "stop" } };
            });

            var (code, output, _) = Run(host, "reset", "--kind", "origin", "--force");

            Assert.Equal(0, code);
            Assert.Equal("origin", seen["kind"]);
            Assert.Equal(true, seen["force"]);
            Assert.StartsWith("ok reset state=reset kind=origin application=App application_state=stop\n", output);
            Assert.DoesNotContain("force", Run(host, "reset").output);
        }

        [Fact]
        public void A_value_an_option_does_not_take_is_a_usage_error()
        {
            var (code, output, error) = Run(new FakeHost(), "reset", "--kind", "hot");

            Assert.Equal(2, code);
            Assert.Equal("error reset cause=usage\nNext: cts reset --help\n", output);
            Assert.Contains("--kind takes warm, cold, origin, not hot", error);
            Assert.Contains("--last takes a whole number", Run(new FakeHost(), "read-log", "--last", "x").error);
        }

        [Fact]
        public void Disconnect_without_a_session_says_so_under_its_line()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => new Dictionary<string, object>
            {
                { "state", "disconnected" }, { "was_connected", false }, { "online_after", false },
                { "note", "No live online session was found: nothing to disconnect. The IDE was already offline." },
            });

            var (_, output, _) = Run(host, "disconnect");

            Assert.Equal("ok disconnect state=disconnected was_connected=false\n"
                + "No live online session was found: nothing to disconnect. The IDE was already offline.\nide-1 · no project\n", output);
        }

        [Fact]
        public void Read_log_lists_the_messages_and_keeps_the_newest_twenty_lines()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => new Dictionary<string, object>
            {
                { "category", "Build" },
                { "count", 25L },
                { "messages", Enumerable.Range(1, 25).Select(i => (object)("line " + i)).ToList() },
            });

            var lines = Run(host, "read-log").output.Split('\n');

            Assert.Equal("ok read-log category=Build messages=25", lines[0]);
            Assert.Equal("line 20", lines[20]);
            Assert.Equal("... and 5 more", lines[21]);
        }

        [Fact]
        public void Project_tree_lists_the_objects_that_hold_others_by_their_own_names()
        {
            var host = new FakeHost();
            IDictionary<string, object> Node(string name, string objectName, params IDictionary<string, object>[] children)
            {
                var node = new Dictionary<string, object> { { "name", name }, { "children", children.Cast<object>().ToList() } };
                if (objectName != null) node["object_name"] = objectName;
                return node;
            }
            host.Agents[1] = Agent(null, null, method => Node("plant", null,
                Node("PLC", null, Node("PLC Logic", "Plc Logic", Node("Application", null, Node("MAIN", null), Node("GVL", null)))),
                Node("GlobalTextList", null)));

            var output = Run(host, "project-tree").output;

            Assert.StartsWith("ok project-tree children=2 name=plant\nPLC  (4 objects)\nPLC/Plc Logic  (3 objects)\nPLC/Plc Logic/Application  (2 objects)\n", output);
        }

        [Fact]
        public void A_refusal_of_the_agent_is_the_cause_with_the_way_out()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => throw new ProtocolException("bad_params", "No project is open in this IDE.\nmore"));

            var (code, output, _) = Run(host, "project-tree");

            Assert.Equal(1, code);
            Assert.Equal("error project-tree cause=\"No project is open in this IDE.\"\nNext: cts project open --path <p>\n", output);
        }

        static Dictionary<string, object> LoginDialog(string fingerprint)
        {
            var data = new ModalWindow
            {
                Id = 3,
                Title = "CODESYS",
                Text = "The application changed since last download. What do you want to do?",
                Options = new[] { new ModalOption("Login with online change", ModalOptionKind.Radio, true), new ModalOption("Update boot application", ModalOptionKind.Check, false) },
                Buttons = new[] { "&OK", "Cancel" },
            }.ToData();
            data["fingerprint"] = fingerprint;
            return data;
        }

        const string LoginLine = "blocked by a dialog [id 3f9a1c02]: CODESYS - The application changed since last download. "
            + "What do you want to do? - options: (*) Login with online change, [ ] Update boot application - buttons: [OK] [Cancel]";

        [Fact]
        public void Dialog_names_the_dialog_with_the_line_a_refusal_ends_with()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method =>
            {
                Assert.Equal("dialog.probe", method);
                return new Dictionary<string, object> { { "dialogs", new List<object> { LoginDialog("3f9a1c02") } } };
            });

            var (code, output, _) = Run(host, "dialog");

            Assert.Equal(0, code);
            Assert.Equal("ok dialog dialogs=1 id=3f9a1c02 title=CODESYS\n" + LoginLine + "\nide-1 · no project\n", output);
        }

        [Fact]
        public void Dialog_answer_sends_the_choices_and_a_dialog_still_open_is_partial()
        {
            IDictionary<string, object> seen = null;
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                Assert.Equal("dialog.answer", method);
                seen = p;
                return new Dictionary<string, object>
                {
                    { "id", "3f9a1c02" }, { "pressed", "OK" }, { "via", "click" }, { "closed", false }, { "closed_after_s", 5.0 },
                    { "chosen", new List<object> { "Login with online change" } },
                    { "next", new List<object> { LoginDialog("3f9a1c02") } },
                };
            });

            var (code, output, _) = Run(host, "dialog", "answer", "--choose", "Login with online change", "--choose", "Update boot application", "--press", "OK");

            Assert.Equal(1, code);
            Assert.Equal(new object[] { "Login with online change", "Update boot application" }, ((IList<object>)seen["choose"]).ToArray());
            Assert.Equal("OK", seen["press"]);
            var lines = output.Split('\n');
            Assert.Equal("partial dialog-answer closed=false pressed=OK id=3f9a1c02", lines[0]);
            Assert.Equal("answered [id 3f9a1c02]  pressed [OK] (click)  chose: Login with online change  the dialog is STILL OPEN after 5 s", lines[1]);
            Assert.StartsWith("the dialog did not close", lines[2]);
            Assert.Equal(LoginLine, lines[3]);
        }

        [Fact]
        public void An_answer_that_opens_a_dialog_on_top_says_to_answer_that_one_first()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) => new Dictionary<string, object>
            {
                { "id", "9f22cd06" }, { "pressed", "Set All to Newest" }, { "via", "winforms" }, { "closed", false },
                { "closed_after_s", 0.5 }, { "covered", true },
                { "next", new List<object> { LoginDialog("3f9a1c02") } },
            });

            var (code, output, _) = Run(host, "dialog", "answer", "--press", "Set All to Newest");

            Assert.Equal(1, code);
            var lines = output.Split('\n');
            Assert.EndsWith("another dialog opened on top after 0.5 s", lines[1]);
            Assert.StartsWith("the press opened another dialog on top of this one", lines[2]);
            Assert.Equal(LoginLine, lines[3]);
        }

        [Fact]
        public void A_refused_answer_shows_the_dialog_as_it_is_now()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => throw new ProtocolException("bad_params", "no option 'Download' in the dialog",
                new Dictionary<string, object> { { "dialogs", new List<object> { LoginDialog("3f9a1c02") } } }));

            var (code, output, error) = Run(host, "dialog", "answer", "--choose", "Download", "--press", "OK");

            Assert.Equal(1, code);
            Assert.StartsWith("error dialog-answer cause=\"no option 'Download' in the dialog\"", output);
            Assert.Contains(LoginLine, error);
        }

        [Fact]
        public void Dialog_answer_needs_a_button()
        {
            var (code, output, error) = Run(new FakeHost(), "dialog", "answer", "--choose", "x");

            Assert.Equal(2, code);
            Assert.Equal("error dialog-answer cause=usage\nNext: cts dialog answer --help\n", output);
            Assert.Contains("--press is required", error);
            Assert.StartsWith("usage: cts dialog answer [--choose OPTION] [--uncheck OPTION] --press BUTTON [--id FINGERPRINT]",
                Run(new FakeHost(), "dialog", "answer", "--help").output);
        }

        [Fact]
        public void Connect_says_when_it_created_the_application_and_what_the_ide_asked()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, (method, p) =>
            {
                Assert.Equal("app.login", method);
                Assert.Equal("10.0.0.5", p["ip"]);
                return new Dictionary<string, object>
                {
                    { "state", "stop" }, { "application", "App" }, { "ip", "10.0.0.5" }, { "plc", "plc-7" }, { "app_created", true }, { "reused_session", false },
                    { "prompts", new List<object> { new Dictionary<string, object> { { "prompt", "online_change" }, { "text", "The PLC runs other code." } } } },
                };
            });

            var (_, output, _) = Run(host, "connect", "--ip", "10.0.0.5");

            Assert.StartsWith("ok connect state=stop application=App plc=plc-7 ip=10.0.0.5 app_created=true\nthe PLC had no such application; login created it\nThe PLC runs other code.\n", output);
            var json = (IDictionary<string, object>)Json.Parse(Run(host, "connect", "--ip", "10.0.0.5", "--json").output);
            Assert.Equal(true, json["app_created"]);
            Assert.False(json.ContainsKey("created"));
        }

        [Fact]
        public void An_edit_the_online_ide_refuses_names_disconnect_and_the_command_to_repeat()
        {
            var host = new FakeHost();
            host.Agents[1] = Agent(null, null, method => throw new ProtocolException("bad_params", "refused: the project is online"));

            var (_, output, _) = Run(host, "connect", "--ip", "10.0.0.5");

            Assert.Equal("error connect cause=\"The IDE is online with the PLC; editing the project while online is not supported. "
                + "Run `cts disconnect`, then repeat `cts connect`.\"\nNext: cts disconnect\n", output);
        }

        [Fact]
        public void An_unknown_option_is_a_usage_error()
        {
            var (code, output, _) = Run(new FakeHost(), "ping", "--bogus");

            Assert.Equal(2, code);
            Assert.Equal("error ping cause=usage\nNext: cts ping --help\n", output);
        }

        [Fact]
        public void Help_needs_no_agent()
        {
            var (code, output, _) = Run(new FakeHost(), "ping", "--help");

            Assert.Equal(0, code);
            Assert.StartsWith("usage: cts ping", output);
            var reset = Run(new FakeHost(), "reset", "-h").output;
            Assert.StartsWith("usage: cts reset [--kind {warm,cold,origin}] [--force] [--timeout SECONDS]\n", reset);
            Assert.Contains("\n  --force", reset);
            Assert.Contains("Confirm an origin reset", reset);
            var analyze = Run(new FakeHost(), "analyze", "--help").output;
            Assert.StartsWith("usage: cts analyze [--workspace DIR]", analyze);
            Assert.DoesNotContain("--timeout", analyze);
            Assert.Contains("--timeout SECONDS", Run(new FakeHost(), "agent", "list", "--help").output);
            var answer = Run(new FakeHost(), "dialog", "answer", "--help").output.Split('\n');
            Assert.All(answer.Where(l => !l.StartsWith("usage:")), l => Assert.True(l.Length <= 100, l));
            Assert.Contains("  cts dialog answer --choose \"Login without any change\" --press OK", answer);
        }

        [Fact]
        public void The_footer_names_a_project_the_ide_opened_while_the_command_ran()
        {
            var hellos = 0;
            var host = new FakeHost();
            var opened = Agent(@"C:\work\plant.project", null, Pong);
            host.Agents[3] = (method, p) => method == "hello" && hellos++ == 0 ? Agent(null, null, Pong)(method, p) : opened(method, p);

            var (code, output, _) = Run(host, "ping");

            Assert.Equal(0, code);
            Assert.EndsWith("ide-3 · plant\n", output);
        }

        [Fact]
        public void The_footer_does_not_call_a_busy_ide_projectless()
        {
            var host = new FakeHost();
            host.Agents[4] = (method, _) => method == "hello"
                ? new Dictionary<string, object> { { "protocol", "1.0" }, { "project", null }, { "ui_busy", true } }
                : Pong(method);

            Assert.EndsWith("ide-4 · project not read: the IDE was busy\n", Run(host, "ping").output);
        }

        [Fact]
        public void A_command_tells_once_what_the_user_changed_in_the_ide_outside_cts()
        {
            var taken = 0;
            var host = new FakeHost();
            host.Agents[1] = (method, _) =>
            {
                if (method == "hello")
                    return new Dictionary<string, object> { { "protocol", "1.0" }, { "user_changes", taken == 0 ? 2L : 0L } };
                if (method != "journal.take") return Pong(method);
                taken++;
                return new Dictionary<string, object>
                {
                    { "changes", new List<object>
                        {
                            new Dictionary<string, object> { { "guid", "g1" }, { "name", "PLC_PRG" }, { "kinds", new List<object> { "modified" } } },
                            new Dictionary<string, object> { { "guid", "g2" }, { "kinds", new List<object> { "added", "renamed" } } },
                        } },
                };
            };
            var (code, _, error) = Run(host, "ping");
            Assert.Equal(0, code);
            Assert.Contains("[INFO] The IDE changed outside cts since the last cts command: PLC_PRG (modified), g2 (added/renamed).", error);
            Assert.DoesNotContain("[INFO]", Run(host, "ping").error);
            Assert.Equal(1, taken);
        }

        [Fact]
        public void An_agent_of_another_build_is_named_beside_the_answer()
        {
            var build = "1.0";
            var host = new FakeHost();
            host.Agents[1] = (method, _) => method == "hello"
                ? new Dictionary<string, object> { { "protocol", "1.0" }, { "agent_version", build } }
                : Pong(method);

            var (code, _, error) = Run(host, "ping");
            Assert.Equal(0, code);
            Assert.Contains("[WARN] The IDE's agent is 1.0, this cts is " + CliRun.Build() + ":", error);
            build = CliRun.Build();
            Assert.DoesNotContain("[WARN]", Run(host, "ping").error);
        }
    }
}
