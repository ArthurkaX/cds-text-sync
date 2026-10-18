using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class RouterTests
    {
        static IDictionary<string, object> Reply(string line)
        {
            return (IDictionary<string, object>)Json.Parse(line);
        }

        static string Code(IDictionary<string, object> reply)
        {
            return (string)((IDictionary<string, object>)reply["error"])["code"];
        }

        static Router Make()
        {
            var r = new Router();
            r.Register("echo", (req, s) => req.Params);
            r.Register("add", (req, s) => req.Int("a") + req.Int("b"));
            r.Register("boom", (req, s) => { throw new InvalidOperationException("kaput"); });
            r.Register("denied", (req, s) => { throw new ProtocolException(ErrorCodes.Busy, "agent busy"); });
            r.Register("opaque", (req, s) => new object());
            return r;
        }

        [Fact]
        public void AnswersAndEchoesStringId()
        {
            var reply = Reply(Make().Handle("{\"id\":\"r1\",\"method\":\"add\",\"params\":{\"a\":2,\"b\":3}}", null));
            Assert.Equal("r1", reply["id"]);
            Assert.Equal(true, reply["ok"]);
            Assert.Equal(5L, reply["result"]);
        }

        [Fact]
        public void EchoesNumericId()
        {
            var reply = Reply(Make().Handle("{\"id\":7,\"method\":\"echo\"}", null));
            Assert.Equal(7L, reply["id"]);
        }

        [Fact]
        public void MissingIdIsAllowedAndEchoedAsNull()
        {
            var reply = Reply(Make().Handle("{\"method\":\"echo\"}", null));
            Assert.Null(reply["id"]);
            Assert.Equal(true, reply["ok"]);
        }

        [Fact]
        public void BadJsonIsAnErrorReply()
        {
            var reply = Reply(Make().Handle("{not json", null));
            Assert.Equal(false, reply["ok"]);
            Assert.Equal(ErrorCodes.BadJson, Code(reply));
        }

        [Theory]
        [InlineData("[1,2]")]
        [InlineData("{\"id\":\"x\"}")]
        [InlineData("{\"id\":\"x\",\"method\":\"\"}")]
        [InlineData("{\"id\":true,\"method\":\"echo\"}")]
        public void BadShapeIsBadRequest(string line)
        {
            var reply = Reply(Make().Handle(line, null));
            Assert.Equal(ErrorCodes.BadRequest, Code(reply));
        }

        [Fact]
        public void BadRequestKeepsTheClientsId()
        {
            var reply = Reply(Make().Handle("{\"id\":\"keep\"}", null));
            Assert.Equal("keep", reply["id"]);
        }

        [Fact]
        public void ParamsMustBeAnObject()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"echo\",\"params\":[1]}", null));
            Assert.Equal(ErrorCodes.BadParams, Code(reply));
        }

        [Fact]
        public void UnknownMethodNamesTheMethod()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"nope\"}", null));
            Assert.Equal(ErrorCodes.UnknownMethod, Code(reply));
            Assert.Contains("nope", (string)((IDictionary<string, object>)reply["error"])["message"]);
        }

        [Fact]
        public void MissingParameterIsBadParams()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"add\",\"params\":{\"a\":1}}", null));
            Assert.Equal(ErrorCodes.BadParams, Code(reply));
            Assert.Contains("'b'", (string)((IDictionary<string, object>)reply["error"])["message"]);
        }

        [Fact]
        public void WrongParameterTypeIsBadParams()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"add\",\"params\":{\"a\":\"x\",\"b\":1}}", null));
            Assert.Equal(ErrorCodes.BadParams, Code(reply));
        }

        [Fact]
        public void HandlerProtocolExceptionKeepsItsCode()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"denied\"}", null));
            Assert.Equal(ErrorCodes.Busy, Code(reply));
        }

        [Fact]
        public void HandlerFaultBecomesInternalAndIsReported()
        {
            var router = Make();
            string seenMethod = null;
            Exception seen = null;
            router.OnHandlerFault = (m, e) => { seenMethod = m; seen = e; };
            var reply = Reply(router.Handle("{\"id\":1,\"method\":\"boom\"}", null));
            Assert.Equal(ErrorCodes.Internal, Code(reply));
            Assert.Contains("kaput", (string)((IDictionary<string, object>)reply["error"])["message"]);
            Assert.Equal("boom", seenMethod);
            Assert.IsType<InvalidOperationException>(seen);
        }

        [Fact]
        public void UnserializableResultBecomesInternal()
        {
            var reply = Reply(Make().Handle("{\"id\":1,\"method\":\"opaque\"}", null));
            Assert.Equal(ErrorCodes.Internal, Code(reply));
        }

        [Fact]
        public void FaultReporterThatThrowsDoesNotBreakTheReply()
        {
            var router = Make();
            router.OnHandlerFault = (m, e) => { throw new Exception("logger down"); };
            var reply = Reply(router.Handle("{\"id\":1,\"method\":\"boom\"}", null));
            Assert.Equal(ErrorCodes.Internal, Code(reply));
        }

        [Fact]
        public void OverlongLineIsRejectedWithoutParsing()
        {
            var line = "{\"id\":1,\"method\":\"echo\",\"params\":{\"x\":\"" + new string('a', Protocol.MaxLineLength) + "\"}}";
            var reply = Reply(Make().Handle(line, null));
            Assert.Equal(ErrorCodes.BadRequest, Code(reply));
        }

        [Fact]
        public void DuplicateRegistrationIsRejected()
        {
            var router = Make();
            Assert.Throws<InvalidOperationException>(() => router.Register("echo", (r, s) => null));
        }

        [Fact]
        public void MethodsAreListedSorted()
        {
            Assert.Equal(new[] { "add", "boom", "denied", "echo", "opaque" }, new List<string>(Make().Methods));
        }

        [Fact]
        public void TypedAccessorsUseFallbacks()
        {
            var req = Request.Parse("{\"method\":\"m\",\"params\":{\"s\":\"v\",\"n\":3,\"b\":true}}");
            Assert.Equal("v", req.String("s"));
            Assert.Equal("d", req.String("missing", "d"));
            Assert.Equal(3L, req.Int("n"));
            Assert.Equal(9L, req.Int("missing", 9));
            Assert.True(req.Bool("b"));
            Assert.False(req.Bool("missing", false));
            Assert.Throws<ProtocolException>(() => req.Bool("n"));
            Assert.Throws<ProtocolException>(() => req.String("n"));
        }

        [Fact]
        public void AGateRefusesWithoutRunningTheHandler()
        {
            var router = Make();
            var ran = false;
            router.Register("gated", (req, s) => { ran = true; return 1; });
            router.Gate = req => req.Method == "gated"
                ? new ProtocolException(ErrorCodes.DialogBlocked, "blocked",
                    new Dictionary<string, object> { { "dialogs", new List<object>() } })
                : null;

            var reply = Reply(router.Handle("{\"id\":1,\"method\":\"gated\"}", null));

            Assert.Equal(false, reply["ok"]);
            Assert.Equal(ErrorCodes.DialogBlocked, Code(reply));
            Assert.True(((IDictionary<string, object>)reply["error"]).ContainsKey("data"));
            Assert.False(ran, "a gated method must not run");
        }

        [Fact]
        public void AGateThatReturnsNullLetsTheHandlerRun()
        {
            var router = Make();
            router.Gate = req => null;
            var reply = Reply(router.Handle("{\"id\":1,\"method\":\"add\",\"params\":{\"a\":1,\"b\":1}}", null));
            Assert.Equal(true, reply["ok"]);
            Assert.Equal(2L, reply["result"]);
        }
    }
}
