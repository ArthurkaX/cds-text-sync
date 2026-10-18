using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class VarValueTests
    {
        // ---- read shaping

        static object Json(object value, out string type, out bool isScalar)
        {
            return VarValue.ToJson(value, out type, out isScalar);
        }

        [Fact]
        public void AnUnsignedWordReadsAsAnIntegerWithItsDotNetType()
        {
            string type; bool scalar;
            var json = Json((uint)98406, out type, out scalar);
            Assert.Equal(98406L, json);
            Assert.Equal("System.UInt32", type);
            Assert.True(scalar);
        }

        [Fact]
        public void ARealReadsAsAJsonNumber()
        {
            string type; bool scalar;
            Assert.Equal(13.5, Json(13.5f, out type, out scalar));
            Assert.Equal("System.Single", type);
            Assert.True(scalar);
        }

        [Fact]
        public void BooleansAndStringsStayTyped()
        {
            string type;
            Assert.Equal(true, Json(true, out type, out _));
            Assert.Equal("System.Boolean", type);
            Assert.Equal("hello", Json("hello", out type, out _));
            Assert.Equal("System.String", type);
        }

        [Fact]
        public void AnEnumeratorReadsAsItsName()
        {
            string type; bool scalar;
            Assert.Equal("green", Json(Colour.green, out type, out scalar));
            Assert.EndsWith("Colour", type);
            Assert.True(scalar);
        }

        [Fact]
        public void AnythingElseReadsAsTextAndIsNotAScalar()
        {
            string type; bool scalar;
            var json = Json(new int[] { 1, 2, 3 }, out type, out scalar);
            Assert.Equal("System.Int32[]", type);
            Assert.False(scalar);
            Assert.Equal("System.Int32[]", json);   // ToString of the array type
        }

        enum Colour { red, green }

        // ---- write conversion

        static string Code(Action a) { return Assert.Throws<ProtocolException>(a).Code; }

        [Fact]
        public void AJsonIntegerBecomesTheVariablesIntegerType()
        {
            Assert.Equal((uint)1234, VarValue.FromJson(1234L, typeof(uint), "X"));
            Assert.Equal((ushort)5678, VarValue.FromJson(5678L, typeof(ushort), "X"));
            Assert.Equal((short)-1, VarValue.FromJson(-1L, typeof(short), "X"));
        }

        [Fact]
        public void AValueOutOfRangeIsRefusedNotWrapped()
        {
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(70000L, typeof(ushort), "X")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(-1L, typeof(uint), "X")));
        }

        [Fact]
        public void ARealIsAcceptedByARealTargetAndRefusedByAnIntegerOne()
        {
            Assert.Equal(1.5, VarValue.FromJson(1.5, typeof(double), "X"));
            Assert.Equal(1.5f, VarValue.FromJson(1.5, typeof(float), "X"));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(1.5, typeof(int), "X")));
        }

        [Fact]
        public void AShapeTheTargetCannotHoldIsRefused()
        {
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(true, typeof(uint), "X")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(12L, typeof(bool), "X")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(true, typeof(string), "X")));
        }

        [Fact]
        public void AStringGoesToTheIdeAsTheLiteralItIs()
        {
            Assert.Equal("12", VarValue.FromJson("12", typeof(int), "X"));
            Assert.Equal("WORD#5", VarValue.FromJson("WORD#5", typeof(ushort), "X"));
            Assert.Equal("E_Mode.Run", VarValue.FromJson("E_Mode.Run", typeof(string), "X"));
        }

        [Fact]
        public void WithoutAKnownTypeTheNaturalClrScalarIsPassedThrough()
        {
            Assert.Equal(1234L, VarValue.FromJson(1234L, null, "X"));
            Assert.Equal(true, VarValue.FromJson(true, null, "X"));
            Assert.Equal("hi", VarValue.FromJson("hi", null, "X"));
        }

        [Fact]
        public void NullArrayAndObjectValuesAreRefusedBeforeTheIdeIsTouched()
        {
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(null, typeof(int), "X")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(new List<object> { 1L }, null, "X")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => VarValue.FromJson(new Dictionary<string, object>(), null, "X")));
            Assert.False(VarValue.IsWritableShape(null));
            Assert.False(VarValue.IsWritableShape(new List<object>()));
        }
    }

    public class VarCacheTests
    {
        [Fact]
        public void TheFactoryRunsOnceAndTheValueIsReused()
        {
            var cache = new VarCache();
            var calls = 0;
            Func<object> factory = () => { calls++; return new object(); };
            var key = VarCache.Key("app", "GVL.n");
            var first = cache.GetOrAdd(key, factory);
            var second = cache.GetOrAdd(key, factory);
            Assert.Same(first, second);
            Assert.Equal(1, calls);
        }

        [Fact]
        public void DifferentApplicationsDoNotShareAWatch()
        {
            var cache = new VarCache();
            Assert.NotEqual(VarCache.Key("a", "GVL.n"), VarCache.Key("b", "GVL.n"));
            var a = cache.GetOrAdd(VarCache.Key("a", "GVL.n"), () => "A");
            var b = cache.GetOrAdd(VarCache.Key("b", "GVL.n"), () => "B");
            Assert.Equal("A", a);
            Assert.Equal("B", b);
        }

        [Fact]
        public void TheOldestEntryGoesWhenTheCapacityIsReached()
        {
            var cache = new VarCache(2);
            cache.GetOrAdd("k1", () => 1);
            cache.GetOrAdd("k2", () => 2);
            cache.GetOrAdd("k3", () => 3);
            object v;
            Assert.False(cache.TryGet("k1", out v));
            Assert.True(cache.TryGet("k3", out v));
            Assert.Equal(2, cache.Count);
        }

        [Fact]
        public void ClearForgetsEverything()
        {
            var cache = new VarCache();
            cache.GetOrAdd("k", () => 1);
            cache.Clear();
            object v;
            Assert.False(cache.TryGet("k", out v));
            Assert.Equal(0, cache.Count);
        }
    }

    public class VarWatchPolicyTests
    {
        [Theory]
        [InlineData("online.application_login")]
        [InlineData("online.application_logout")]
        [InlineData("online.device_login")]
        [InlineData("online.device_logout")]
        [InlineData("online.before_download")]
        [InlineData("online.after_download")]
        public void ALoginLogoutOrDownloadMakesTheWatchesStale(string name)
        {
            Assert.True(VarWatchPolicy.WatchesAreStale(name));
        }

        [Theory]
        [InlineData("online.operating_state")]
        [InlineData("online.application_state")]
        [InlineData("dev.event")]
        [InlineData(null)]
        public void ARunStopStateChangeDoesNot(string name)
        {
            Assert.False(VarWatchPolicy.WatchesAreStale(name));
        }

        [Fact]
        public void AStaleEventClearsTheCacheAndCountsTheInvalidation()
        {
            var cache = new VarCache();
            cache.GetOrAdd("k", () => 1);
            var policy = new VarWatchPolicy(cache);

            policy.OnOnlineEvent("online.operating_state");
            Assert.Equal(1, cache.Count);
            Assert.Equal(0, policy.Invalidations);

            policy.OnOnlineEvent("online.application_login");
            Assert.Equal(0, cache.Count);
            Assert.Equal(1, policy.Invalidations);
        }

        [Fact]
        public void ADifferentApplicationDropsTheWatches()
        {
            var cache = new VarCache();
            var policy = new VarWatchPolicy(cache);
            cache.GetOrAdd("k", () => 1);
            policy.OnApplication("app-a");
            Assert.Equal(0, cache.Count);      // first call fixes the subject

            cache.GetOrAdd("k", () => 1);
            policy.OnApplication("app-a");     // same application: nothing dropped
            Assert.Equal(1, cache.Count);

            policy.OnApplication("app-b");
            Assert.Equal(0, cache.Count);
        }
    }

    public class VarReadPolicyTests
    {
        static Dictionary<string, object> Envelope(bool loggedIn, params object[] results)
        {
            return Vars.ReadEnvelope(true, loggedIn, "app", new List<object>(results));
        }

        static Dictionary<string, object> Failed(string code)
        {
            return Vars.FailedResult("GVL.x", code, "boom", null);
        }

        [Fact]
        public void RetriesNotLoggedInWhileTheApplicationIsLoggedIn()
        {
            Assert.True(VarReadPolicy.ShouldRetry(Envelope(true, Failed(Vars.Codes.NotLoggedIn))));
        }

        [Fact]
        public void RetriesWhenOneOfSeveralNamesHasNoValueYet()
        {
            var ok = Vars.ReadResult("GVL.y", true, "System.Boolean", "Good", "BOOL", null);
            Assert.True(VarReadPolicy.ShouldRetry(Envelope(true, ok, Failed(Vars.Codes.NotLoggedIn))));
        }

        [Fact]
        public void DoesNotRetryWhenReallyLoggedOut()
        {
            Assert.False(VarReadPolicy.ShouldRetry(Envelope(false, Failed(Vars.Codes.NotLoggedIn))));
        }

        [Fact]
        public void DoesNotRetryOtherErrorsOrSuccess()
        {
            Assert.False(VarReadPolicy.ShouldRetry(Envelope(true, Failed(Vars.Codes.NotExported))));
            Assert.False(VarReadPolicy.ShouldRetry(Envelope(true,
                Vars.ReadResult("GVL.y", true, "System.Boolean", "Good", "BOOL", null))));
            Assert.False(VarReadPolicy.ShouldRetry(null));
        }
    }

    public class VarsParamsTests
    {
        static Request Req(string paramsJson)
        {
            return Request.Parse("{\"id\":1,\"method\":\"vars.read\",\"params\":" + paramsJson + "}");
        }

        static string Code(Action a) { return Assert.Throws<ProtocolException>(a).Code; }

        [Fact]
        public void NamesAreReadInOrderDuplicatesKept()
        {
            var names = Vars.Names(Req("{\"names\":[\"A\",\"B\",\"A\"]}"));
            Assert.Equal(new[] { "A", "B", "A" }, names);
        }

        [Theory]
        [InlineData("{}")]
        [InlineData("{\"names\":[]}")]
        [InlineData("{\"names\":\"A\"}")]
        [InlineData("{\"names\":[\"A\",\"\"]}")]
        [InlineData("{\"names\":[\"A\",3]}")]
        public void BadNamesAreRefused(string paramsJson)
        {
            Assert.Equal(ErrorCodes.BadParams, Code(() => Vars.Names(Req(paramsJson))));
        }

        [Fact]
        public void ValuesComeBackAsNameValuePairs()
        {
            var pairs = Vars.Values(Req("{\"values\":{\"A\":1,\"B\":2.5,\"C\":true}}"));
            Assert.Equal(3, pairs.Count);
            var map = new Dictionary<string, object>();
            foreach (var p in pairs) map[p.Key] = p.Value;
            Assert.Equal(1L, map["A"]);
            Assert.Equal(2.5, map["B"]);
            Assert.Equal(true, map["C"]);
        }

        [Theory]
        [InlineData("{}")]
        [InlineData("{\"values\":[]}")]
        [InlineData("{\"values\":{}}")]
        public void BadValuesAreRefused(string paramsJson)
        {
            Assert.Equal(ErrorCodes.BadParams, Code(() => Vars.Values(Req(paramsJson))));
        }

        [Fact]
        public void AppIsOptionalAndEmptyMeansDefault()
        {
            Assert.Null(Vars.Application(Req("{\"names\":[\"A\"]}")));
            Assert.Equal("MyApp", Vars.Application(Req("{\"names\":[\"A\"],\"app\":\"MyApp\"}")));
        }

        [Fact]
        public void StartTimeoutDefaultsAndIsBounded()
        {
            Assert.Equal(StartTimeout.DefaultMs, StartTimeout.Parse(Req("{}")));
            Assert.Equal(250, StartTimeout.Parse(Req("{\"start_timeout_ms\":250}")));
            Assert.Equal(ErrorCodes.BadParams, Code(() => StartTimeout.Parse(Req("{\"start_timeout_ms\":0}"))));
            Assert.Equal(ErrorCodes.BadParams, Code(() => StartTimeout.Parse(Req("{\"start_timeout_ms\":2147483648}"))));
        }

        [Fact]
        public void WriteEnvelopeCountsWhatWasWritten()
        {
            var results = new List<object>
            {
                Vars.WrittenResult("A", 1L, "WORD#1"),
                Vars.FailedResult("B", Vars.Codes.WriteFailed, "no", null),
            };
            var envelope = Vars.WriteEnvelope(true, true, "g", results);
            Assert.Equal(1, envelope["written"]);
            Assert.Equal(2, ((List<object>)envelope["results"]).Count);
            Assert.Equal(true, envelope["logged_in"]);
        }

        [Fact]
        public void AReadEnvelopeCarriesTheOnlineFlags()
        {
            var envelope = Vars.ReadEnvelope(false, false, null, new List<object>());
            Assert.Equal(false, envelope["online"]);
            Assert.Equal(false, envelope["logged_in"]);
            Assert.Null(envelope["application"]);
        }
    }
}
