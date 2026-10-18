using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ActivityLogTests
    {
        static IDictionary<string, object> Params(params object[] pairs)
        {
            var d = new Dictionary<string, object>();
            for (var i = 0; i < pairs.Length; i += 2) d[(string)pairs[i]] = pairs[i + 1];
            return d;
        }

        [Fact]
        public void FormatsAnOkCreateWithKindAndName()
        {
            var line = ActivityLog.Format("objects.create", Params("kind", "pou", "name", "FB_X", "parent_guid", "g"), true, null);
            Assert.Equal("agent objects.create pou FB_X ok", line);
        }

        [Fact]
        public void FormatsARefusalWithTheErrorCode()
        {
            var line = ActivityLog.Format("objects.delete", Params("guid", "0a1b"), false, "forbidden");
            Assert.Equal("agent objects.delete 0a1b forbidden", line);
        }

        [Fact]
        public void FallsBackToNameThenPathThenGuid()
        {
            Assert.Equal("agent m NAME ok", ActivityLog.Format("m", Params("name", "NAME", "guid", "g"), true, null));
            Assert.Equal("agent m P ok", ActivityLog.Format("m", Params("path", "P"), true, null));
            Assert.Equal("agent m g ok", ActivityLog.Format("m", Params("guid", "g"), true, null));
        }

        [Fact]
        public void FormatsALineWithoutATarget()
        {
            Assert.Equal("agent app.logout ok", ActivityLog.Format("app.logout", null, true, null));
            Assert.Equal("agent dialog.answer bad_params", ActivityLog.Format("dialog.answer", null, false, "bad_params"));
        }

        [Fact]
        public void UnknownErrorCodeIsSpelledError()
        {
            Assert.Equal("agent objects.delete X error", ActivityLog.Format("objects.delete", Params("guid", "X"), false, null));
        }

        [Fact]
        public void ANewlineInAValueDoesNotSplitTheLine()
        {
            var line = ActivityLog.Format("objects.settext", Params("guid", "a\nb\rc"), true, null);
            Assert.Equal("agent objects.settext a b c ok", line);
            Assert.DoesNotContain("\n", line);
        }

        [Fact]
        public void SkipsPollAndReadMethods()
        {
            foreach (var method in new[] { "ping", "hello", "state", "methods", "subscribe",
                                           "unsubscribe", "subscriptions", "dialog.probe", "project.status",
                                           "project.tree", "objects.find", "objects.text",
                                           "objects.texts", "objects.fields", "project.export", "vars.read" })
                Assert.True(ActivityLog.IsSkipped(method), method);
        }

        [Fact]
        public void ASlowSkippedRequestIsShownWithItsTime()
        {
            Assert.False(ActivityLog.IsReported("project.export", ActivityLog.SlowMs - 1));
            Assert.True(ActivityLog.IsReported("project.export", ActivityLog.SlowMs));
            Assert.Equal("agent project.export ok 2.4 s", ActivityLog.Format("project.export", null, true, null, 2400));
            Assert.Equal("agent app.build ok", ActivityLog.Format("app.build", null, true, null, 999));
        }

        [Fact]
        public void ShowsWritesAndStateChanges()
        {
            foreach (var method in new[] { "objects.create", "objects.delete", "objects.settext", "objects.setfield",
                                           "objects.listadd", "objects.listremove",
                                           "vars.write", "dialog.answer", "test.run" })
                Assert.False(ActivityLog.IsSkipped(method), method);
        }

    }

    public class RouterActivityTests
    {
        [Fact]
        public void AShowableRequestProducesOneActivityLine()
        {
            var router = new Router();
            router.Register("objects.create", (req, s) => "done");
            var seen = new List<string>();
            router.OnActivity = seen.Add;

            var reply = (IDictionary<string, object>)Json.Parse(
                router.Handle("{\"id\":1,\"method\":\"objects.create\",\"params\":{\"kind\":\"gvl\",\"name\":\"G\"}}", null));

            Assert.Equal(true, reply["ok"]);
            Assert.Equal(new[] { "agent objects.create gvl G ok" }, seen);
        }

        [Fact]
        public void ARefusedRequestReportsTheErrorCode()
        {
            var router = new Router();
            router.Register("objects.delete", (req, s) => { throw new ProtocolException("forbidden", "no"); });
            var seen = new List<string>();
            router.OnActivity = seen.Add;

            router.Handle("{\"id\":1,\"method\":\"objects.delete\",\"params\":{\"guid\":\"g\"}}", null);

            Assert.Equal(new[] { "agent objects.delete g forbidden" }, seen);
        }

        [Fact]
        public void ASkippedRequestProducesNoLine()
        {
            var router = new Router();
            router.Register("ping", (req, s) => "pong");
            var seen = new List<string>();
            router.OnActivity = seen.Add;

            router.Handle("{\"id\":1,\"method\":\"ping\"}", null);

            Assert.Empty(seen);
        }

        [Fact]
        public void ARequestBeingAnsweredIsListedUntilItEnds()
        {
            var router = new Router();
            var inside = new System.Threading.ManualResetEventSlim();
            var release = new System.Threading.ManualResetEventSlim();
            router.Register("app.build", (req, s) => { inside.Set(); release.Wait(); return "done"; });

            var call = System.Threading.Tasks.Task.Run(() => router.Handle("{\"id\":1,\"method\":\"app.build\"}", null));
            inside.Wait();
            Assert.Equal(new[] { "app.build" }, router.Running().ConvertAll(run => run.Key));
            release.Set();
            call.Wait();
            Assert.Empty(router.Running());
        }

        [Fact]
        public void AnActivitySinkThatThrowsDoesNotBreakTheReply()
        {
            var router = new Router();
            router.Register("objects.create", (req, s) => "done");
            router.OnActivity = line => { throw new Exception("sink down"); };

            var reply = (IDictionary<string, object>)Json.Parse(
                router.Handle("{\"id\":1,\"method\":\"objects.create\"}", null));

            Assert.Equal(true, reply["ok"]);
        }
    }
}
