using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Xunit;

namespace Cts.Agent.Tests
{
    public class SessionTests
    {
        static (Router, EventBus) Make()
        {
            var router = new Router();
            Session.RegisterBuiltIns(router);
            router.Register("ping", (req, s) => "pong");
            return (router, new EventBus());
        }

        static List<IDictionary<string, object>> Lines(string output)
        {
            return output.Split(new[] { '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(l => (IDictionary<string, object>)Json.Parse(l)).ToList();
        }

        [Fact]
        public void ServesRequestsInOrderAndEndsAtEof()
        {
            var (router, bus) = Make();
            var input = "{\"id\":1,\"method\":\"ping\"}\n\n{\"id\":2,\"method\":\"ping\"}\n{\"id\":3,\"method\":\"nope\"}\n";
            var output = new StringWriter();
            var session = new Session(new StringReader(input), output, router, bus);
            session.Run();
            var replies = Lines(output.ToString());
            Assert.Equal(new object[] { 1L, 2L, 3L }, replies.Select(r => r["id"]).ToArray());
            Assert.Equal(true, replies[0]["ok"]);
            Assert.Equal(false, replies[2]["ok"]);
            Assert.True(session.IsClosed);
            Assert.Equal(0, bus.SubscriberCount);
        }

        [Fact]
        public void RunsAfterReplyOnceAndOnlyAfterTheReplyWasWritten()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var ran = 0;
            var session = new Session(
                new StringReader("{\"id\":1,\"method\":\"ping\"}\n{\"id\":2,\"method\":\"ping\"}\n"),
                output, router, bus);
            session.AfterReply = () =>
            {
                // The reply is already on the wire when it runs, and it runs once.
                Assert.Contains("\"id\":1", output.ToString());
                ran++;
            };
            session.Run();
            Assert.Equal(1, ran);
            Assert.Null(session.AfterReply);
        }

        [Fact]
        public void AThrowingAfterReplyDoesNotEndTheSession()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var session = new Session(
                new StringReader("{\"id\":1,\"method\":\"ping\"}\n{\"id\":2,\"method\":\"ping\"}\n"),
                output, router, bus);
            session.AfterReply = () => { throw new InvalidOperationException("boom"); };
            session.Run();
            Assert.Equal(2, Lines(output.ToString()).Count);
        }

        [Fact]
        public void AMalformedLineDoesNotEndTheSession()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            new Session(new StringReader("garbage\n{\"id\":1,\"method\":\"ping\"}\n"), output, router, bus).Run();
            var replies = Lines(output.ToString());
            Assert.Equal(2, replies.Count);
            Assert.Equal(false, replies[0]["ok"]);
            Assert.Equal(true, replies[1]["ok"]);
        }

        [Theory]
        [InlineData("*", "online.state", true)]
        [InlineData("online.*", "online.state", true)]
        [InlineData("online.*", "online", false)]
        [InlineData("online.*", "ide.command", false)]
        [InlineData("online.state", "online.state", true)]
        [InlineData("online.state", "online.login", false)]
        public void PatternMatching(string pattern, string name, bool expected)
        {
            Assert.Equal(expected, Session.Matches(pattern, name));
        }

        // A reader that hands out scripted lines one at a time, so a test can publish
        // events between requests.
        sealed class ScriptedReader : TextReader
        {
            readonly Queue<Func<string>> _steps;
            public ScriptedReader(params Func<string>[] steps) { _steps = new Queue<Func<string>>(steps); }
            public override string ReadLine() { return _steps.Count == 0 ? null : _steps.Dequeue()(); }
        }

        [Fact]
        public void DeliversOnlySubscribedEvents()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var reader = new ScriptedReader(
                () => "{\"id\":1,\"method\":\"subscribe\",\"params\":{\"events\":[\"online.*\"]}}",
                () =>
                {
                    bus.Publish("online.state", new Dictionary<string, object> { { "state", "run" } });
                    bus.Publish("ide.command", "ignored");
                    return "{\"id\":2,\"method\":\"ping\"}";
                });
            new Session(reader, output, router, bus).Run();
            var lines = Lines(output.ToString());
            Assert.Equal(3, lines.Count);
            // Events travel on their own thread, so they may follow later replies.
            var evt = Assert.Single(lines, l => l.ContainsKey("event"));
            Assert.Equal("online.state", evt["event"]);
            Assert.Equal("run", ((IDictionary<string, object>)evt["data"])["state"]);
            Assert.True(evt.ContainsKey("seq"));
            Assert.False(evt.ContainsKey("id"));
            Assert.Contains(lines, l => l.ContainsKey("id") && Equals(l["id"], 2L));
        }

        // Blocks every event line until released, like a client that stopped reading.
        sealed class StalledWriter : TextWriter
        {
            public readonly ManualResetEventSlim Release = new ManualResetEventSlim();
            readonly StringWriter _inner = new StringWriter();
            public override System.Text.Encoding Encoding { get { return System.Text.Encoding.UTF8; } }
            public override void Write(string value)
            {
                if (value != null && value.Contains("\"event\"")) Release.Wait();
                lock (_inner) { _inner.Write(value); }
            }
            public override void Write(char value) { lock (_inner) { _inner.Write(value); } }
            public string Text { get { lock (_inner) { return _inner.ToString(); } } }
        }

        [Fact]
        public void AStalledClientNeverBlocksThePublisherAndOldEventsAreDropped()
        {
            var (router, bus) = Make();
            var writer = new StalledWriter();
            var published = new Stopwatch();
            Session session = null;
            var reader = new ScriptedReader(
                () => "{\"id\":1,\"method\":\"subscribe\",\"params\":{\"events\":[\"*\"]}}",
                () =>
                {
                    published.Start();
                    for (var i = 0; i < 3 * Session.MaxQueuedEvents; i++) bus.Publish("e", i);
                    published.Stop();
                    // The reply below shares the write lock with the stalled event line, so the
                    // client "wakes up" from another thread.
                    Task.Run(() => { Thread.Sleep(200); writer.Release.Set(); });
                    return "{\"id\":2,\"method\":\"ping\"}";
                },
                () => null);
            session = new Session(reader, writer, router, bus);
            session.Run();
            Assert.True(published.ElapsedMilliseconds < 2000, "publishing blocked for " + published.ElapsedMilliseconds + " ms");
            // The most recent event survives; the dropped ones are the oldest. Event 0 was already
            // in the writer's hands when the queue filled up, so it is delivered as well.
            Assert.Contains("\"data\":" + (3 * Session.MaxQueuedEvents - 1), writer.Text);
            Assert.DoesNotContain("\"data\":1}", writer.Text);
        }

        [Fact]
        public void NothingIsDeliveredWithoutASubscription()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var reader = new ScriptedReader(() =>
            {
                bus.Publish("online.state", "x");
                return "{\"id\":1,\"method\":\"ping\"}";
            });
            new Session(reader, output, router, bus).Run();
            Assert.Single(Lines(output.ToString()));
        }

        [Fact]
        public void UnsubscribeStopsDelivery()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var reader = new ScriptedReader(
                () => "{\"id\":1,\"method\":\"subscribe\",\"params\":{\"events\":[\"*\"]}}",
                () => "{\"id\":2,\"method\":\"unsubscribe\",\"params\":{\"events\":[\"*\"]}}",
                () =>
                {
                    bus.Publish("online.state", "x");
                    return "{\"id\":3,\"method\":\"subscriptions\"}";
                });
            new Session(reader, output, router, bus).Run();
            var lines = Lines(output.ToString());
            Assert.Equal(3, lines.Count);
            Assert.Empty((IList<object>)((IDictionary<string, object>)lines[2]["result"])["subscriptions"]);
        }

        [Fact]
        public void SubscribeNeedsAnArrayOfStrings()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            var input = "{\"id\":1,\"method\":\"subscribe\"}\n{\"id\":2,\"method\":\"subscribe\",\"params\":{\"events\":\"x\"}}\n{\"id\":3,\"method\":\"subscribe\",\"params\":{\"events\":[1]}}\n";
            new Session(new StringReader(input), output, router, bus).Run();
            Assert.All(Lines(output.ToString()), l => Assert.Equal(false, l["ok"]));
        }

        sealed class BrokenWriter : TextWriter
        {
            public override System.Text.Encoding Encoding { get { return System.Text.Encoding.UTF8; } }
            public override void Write(char value) { throw new IOException("pipe closed"); }
            public override void Write(string value) { throw new IOException("pipe closed"); }
        }

        [Fact]
        public void BrokenConnectionEndsTheSessionQuietly()
        {
            var (router, bus) = Make();
            var input = "{\"id\":1,\"method\":\"ping\"}\n{\"id\":2,\"method\":\"ping\"}\n";
            var session = new Session(new StringReader(input), new BrokenWriter(), router, bus);
            session.Run();
            Assert.True(session.IsClosed);
            Assert.Equal(0, bus.SubscriberCount);
        }

        // What an overlapped pipe does to a pending read when the agent stops.
        sealed class CancelledReader : TextReader
        {
            public override string ReadLine() { throw new OperationCanceledException(); }
        }

        [Fact]
        public void ACancelledReadEndsTheSessionQuietly()
        {
            var (router, bus) = Make();
            var session = new Session(new CancelledReader(), new StringWriter(), router, bus);
            session.Run();
            Assert.True(session.IsClosed);
            Assert.Equal(0, bus.SubscriberCount);
        }

        [Fact]
        public async Task ConcurrentEventsAndRepliesNeverShareALine()
        {
            var (router, bus) = Make();
            var output = new StringWriter();
            const int Events = 400;
            var release = new ManualResetEventSlim();
            var reader = new ScriptedReader(
                () => "{\"id\":0,\"method\":\"subscribe\",\"params\":{\"events\":[\"*\"]}}",
                () => { release.Set(); return "{\"id\":1,\"method\":\"ping\"}"; },
                () => { Thread.Sleep(100); return null; });
            var pumps = Enumerable.Range(0, 4).Select(t => Task.Run(() =>
            {
                release.Wait();
                for (var i = 0; i < Events / 4; i++)
                    bus.Publish("e", new Dictionary<string, object> { { "t", t }, { "pad", new string('x', 50) } });
            })).ToArray();
            new Session(reader, output, router, bus).Run();
            await Task.WhenAll(pumps);
            // Every line must parse; an interleaved write would throw here.
            var lines = Lines(output.ToString());
            Assert.True(lines.Count >= 2);
            Assert.Contains(lines, l => l.ContainsKey("id") && (long)l["id"] == 1L);
        }

        [Fact]
        public void BusDropsAFailingSubscriberOnlyForThatDelivery()
        {
            var bus = new EventBus();
            var good = 0;
            Exception reported = null;
            bus.OnSubscriberError = e => reported = e;
            bus.Subscribe((n, l) => { throw new InvalidOperationException("bad"); });
            bus.Subscribe((n, l) => good++);
            bus.Publish("x", null);
            bus.Publish("x", null);
            Assert.Equal(2, good);
            Assert.IsType<InvalidOperationException>(reported);
        }

        [Fact]
        public void BusNumbersEventsAndStampsUtcTime()
        {
            var bus = new EventBus();
            var seen = new List<string>();
            bus.Subscribe((n, l) => seen.Add(l));
            bus.Publish("a", 1);
            bus.Publish("b", 2);
            var first = (IDictionary<string, object>)Json.Parse(seen[0]);
            var second = (IDictionary<string, object>)Json.Parse(seen[1]);
            Assert.Equal(1L, first["seq"]);
            Assert.Equal(2L, second["seq"]);
            Assert.EndsWith("Z", (string)first["time"]);
        }

        [Fact]
        public void DisposedSubscriptionReceivesNothing()
        {
            var bus = new EventBus();
            var n = 0;
            var sub = bus.Subscribe((name, line) => n++);
            bus.Publish("a", null);
            sub.Dispose();
            bus.Publish("a", null);
            Assert.Equal(1, n);
        }
    }
}
