// `dev.reflect` / `dev.listen` logic, exercised against ordinary .NET objects:
// no IDE, no CODESYS names. They pin the path grammar, the member lookup
// (explicit interface implementations included), the description shape and the
// expression-built event handler.
using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public delegate void ThingHandler(object sender, ThingArgs e);

    public sealed class ThingArgs : EventArgs
    {
        public ThingArgs(int value, string note) { Value = value; Note = note; }
        public int Value { get; private set; }
        public string Note { get; private set; }
    }

    public interface IThing
    {
        string Label { get; }
        int Twice(int n);
    }

    public enum Colour
    {
        Red = 1,
        Green = 2,
        Blue = 4,
    }

    public sealed class Thing : IThing
    {
        public string Label { get { return "a-thing"; } }
        int IThing.Twice(int n) { return n * 2; }

        public int Count { get { return 5; } }
        public string Ping() { return "pong"; }
        public string Pick(string text) { return "string:" + text; }
        public string Pick(Guid id) { return "guid:" + id; }
        public ThingArgs Knob { get { return new ThingArgs(7, "note"); } }
        public List<string> Names { get { return new List<string> { "a", "b", "c" }; } }
        public event ThingHandler Changed;
        public void Fire() { if (Changed != null) Changed(this, new ThingArgs(1, "fired")); }

        public override string ToString() { return "the-thing"; }
    }

    public sealed class Fielder
    {
        public string Name;
    }

    public class DevPathTests
    {
        static PathStep Step(string text) { return DevPath.ParseStep(text); }

        [Fact]
        public void APlainNameIsAProperty()
        {
            var step = Step("Projects");
            Assert.Equal(PathStep.StepKind.Property, step.Kind);
            Assert.Equal("Projects", step.Name);
            Assert.Equal("Projects", step.ToString());
        }

        [Fact]
        public void ANameWithEmptyParenthesesIsAZeroArgumentMethod()
        {
            var step = Step("Ping()");
            Assert.Equal(PathStep.StepKind.Method, step.Kind);
            Assert.Empty(step.Arguments);
            Assert.Equal("Ping()", step.ToString());
        }

        [Fact]
        public void AQuotedArgumentIsAString()
        {
            var step = Step("Method(\"a\\\"b\")");
            Assert.Equal(PathStep.StepKind.Method, step.Kind);
            Assert.Equal("a\"b", step.Arguments[0]);
            Assert.Equal("Method(\"a\\\"b\")", step.ToString());
        }

        [Fact]
        public void AnAngleBracketArgumentIsAGuidAnIntegerOrABoolean()
        {
            var guid = Guid.NewGuid();
            var byGuid = Step("GetApplication(<" + guid + ">)");
            Assert.Equal(guid, byGuid.Arguments[0]);
            var byInt = Step("GetApplication(<42>)");
            Assert.Equal(42L, byInt.Arguments[0]);
            Assert.Equal("GetApplication(<42>)", byInt.ToString());
            Assert.Equal(true, Step("Login(<true>)").Arguments[0]);
            Assert.Equal(false, Step("Login(<false>)").Arguments[0]);
            var byNull = Step("SetObject(pinned:1, <true>, <null>)");
            Assert.Null(byNull.Arguments[2]);
            Assert.Equal("SetObject(pinned:1, <true>, <null>)", byNull.ToString());
        }

        [Fact]
        public void APinnedArgumentNamesAnObjectKeptByDevPin()
        {
            var step = Step("CreateWatch(pinned:3)");
            var pinned = Assert.IsType<PinnedRef>(step.Arguments[0]);
            Assert.Equal(3, pinned.Id);
            Assert.Equal("CreateWatch(pinned:3)", step.ToString());
        }

        [Fact]
        public void SeveralArgumentsAndAnArrayAreSeparateValues()
        {
            var step = Step("WriteVariables([pinned:1, pinned:2])");
            var array = Assert.IsAssignableFrom<IList<object>>(step.Arguments[0]);
            Assert.Equal(2, array.Count);
            Assert.IsType<PinnedRef>(array[0]);

            var two = Step("Method(\"a\", <2>)");
            Assert.Equal(2, two.Arguments.Count);
            Assert.Equal("a", two.Arguments[0]);
            Assert.Equal(2L, two.Arguments[1]);
        }

        [Fact]
        public void AnEqualsSignIsAPropertyWrite()
        {
            var step = Step("PreparedValue = <123>");
            Assert.Equal(PathStep.StepKind.Set, step.Kind);
            Assert.Equal("PreparedValue", step.Name);
            Assert.Equal(123L, step.Arguments[0]);
            Assert.Equal("PreparedValue = <123>", step.ToString());
        }

        [Fact]
        public void ANumberInBracketsIsAnIndex()
        {
            var step = Step("[2]");
            Assert.Equal(PathStep.StepKind.Index, step.Kind);
            Assert.Equal(2, step.Index);
            Assert.Equal("[2]", step.ToString());
        }

        [Theory]
        [InlineData("")]
        [InlineData("Method(")]
        [InlineData("Method(1)")]
        [InlineData("Method(<nope>)")]
        [InlineData("[]")]
        [InlineData("[-1]")]
        [InlineData("[a]")]
        [InlineData("= 3")]
        [InlineData("Count =")]
        [InlineData("M(pinned:x)")]
        public void MalformedStepsAreRefused(string text)
        {
            Assert.Equal(ErrorCodes.BadParams,
                Assert.Throws<ProtocolException>(() => Step(text)).Code);
        }

        [Fact]
        public void APathParameterMustBeAnArrayOfStrings()
        {
            Assert.Empty(DevPath.Parse(new Dictionary<string, object>()));
            Assert.Empty(DevPath.Parse(null));

            var steps = DevPath.Parse(new Dictionary<string, object>
            {
                { "path", new List<object> { "GetApplication()", "[0]" } },
            });
            Assert.Equal(2, steps.Count);

            var bad = new Dictionary<string, object> { { "path", new List<object> { 3 } } };
            Assert.Equal(ErrorCodes.BadParams,
                Assert.Throws<ProtocolException>(() => DevPath.Parse(bad)).Code);
        }
    }

    public class DevReflectionTests
    {
        [Fact]
        public void APropertyIsFoundOnTheRuntimeType()
        {
            var property = DevReflection.ResolveProperty(typeof(Thing), false, "Count");
            Assert.Equal(5, property.GetValue(new Thing(), null));
        }

        [Fact]
        public void APropertyIsFoundThroughAnInterfaceEvenWhenImplementedExplicitly()
        {
            var property = DevReflection.ResolveProperty(typeof(Thing), false, "Label");
            Assert.Equal("a-thing", property.GetValue(new Thing(), null));
        }

        [Fact]
        public void AMethodIsFoundThroughAnExplicitInterfaceImplementation()
        {
            var method = DevReflection.ResolveMethod(typeof(Thing), false, "Twice", new List<object> { 21L });
            Assert.Equal(42, method.Invoke(new Thing(), new object[] { 21 }));
        }

        [Fact]
        public void AnOverloadIsChosenByTheArgumentType()
        {
            var byString = DevReflection.ResolveMethod(typeof(Thing), false, "Pick", new List<object> { "x" });
            Assert.Equal("string:x", byString.Invoke(new Thing(), new object[] { "x" }));

            var guid = Guid.NewGuid();
            var byGuid = DevReflection.ResolveMethod(typeof(Thing), false, "Pick", new List<object> { guid });
            Assert.Equal("guid:" + guid, byGuid.Invoke(new Thing(), new object[] { guid }));
        }

        [Fact]
        public void AZeroArgumentMethodNeedsNoArgument()
        {
            var method = DevReflection.ResolveMethod(typeof(Thing), false, "Ping", new List<object>());
            Assert.Equal("pong", method.Invoke(new Thing(), null));
        }

        [Fact]
        public void AMissingMemberNamesItselfAndSuggestsCloseNames()
        {
            var message = Assert.Throws<ProtocolException>(
                () => DevReflection.ResolveProperty(typeof(Thing), false, "Coutn")).Message;
            Assert.Contains("Coutn", message);
            Assert.Contains("Count", message);

            var eventMessage = Assert.Throws<ProtocolException>(
                () => DevListen.ResolveEvent(typeof(Thing), false, "Change")).Message;
            Assert.Contains("Changed", eventMessage);
        }

        [Fact]
        public void ADescriptionCarriesTypeInterfacesToStringAndValue()
        {
            var described = DevReflection.Describe(new Thing(), false, false, 0, 0);
            Assert.Equal(typeof(Thing).FullName, described["type"]);
            Assert.Contains(typeof(IThing).FullName, (List<string>)described["interfaces"]);
            Assert.Equal("the-thing", described["to_string"]);
            Assert.False(described.ContainsKey("value"));
            Assert.False(described.ContainsKey("members"));
        }

        [Fact]
        public void AScalarCarriesItsValueAndALongToStringIsTrimmed()
        {
            var described = DevReflection.Describe(new string('x', 500), false, false, 0, 0);
            Assert.Equal(200 + 3, ((string)described["to_string"]).Length);
            Assert.EndsWith("...", (string)described["to_string"]);

            var number = DevReflection.Describe(7, false, false, 0, 0);
            Assert.Equal(7, number["value"]);
        }

        [Fact]
        public void NullIsDescribedWithoutFailing()
        {
            var described = DevReflection.Describe(null, false, true, 0, 0);
            Assert.Null(described["type"]);
            Assert.Null(described["to_string"]);
            Assert.Empty((List<string>)described["interfaces"]);
            Assert.False(described.ContainsKey("members"));
        }

        [Fact]
        public void AnEnumerableIsPreviewedByItsFirstItems()
        {
            var described = DevReflection.Describe(new Thing().Names, false, false, 0, 0);
            var items = (List<object>)described["items"];
            Assert.Equal(3, items.Count);
            var first = (IDictionary<string, object>)items[0];
            Assert.Equal("a", first["to_string"]);
            Assert.Equal("System.String", first["type"]);
        }

        [Fact]
        public void APreviewShowsTwentyItemsUnlessMoreAreAskedFor()
        {
            var many = Enumerable.Range(0, 3000).ToList();
            Assert.Equal(DevReflection.DefaultItems, ((List<object>)DevReflection.Describe(many, false, false, 0, 0)["items"]).Count);
            Assert.Equal(500, ((List<object>)DevReflection.Describe(many, false, false, 0, 500)["items"]).Count);
            Assert.Equal(DevReflection.MaxItems, ((List<object>)DevReflection.Describe(many, false, false, 0, 5000)["items"]).Count);
        }

        [Fact]
        public void MembersListSignaturesOfTheTypeAndItsInterfaces()
        {
            var members = DevReflection.Members(typeof(Thing), false, 0);
            var signatures = ((List<object>)members["signatures"]).Cast<string>().ToList();
            Assert.Contains(signatures, s => s.Contains("Twice(Int32 n) -> Int32"));
            Assert.Contains(signatures, s => s.Contains("Pick(String text) -> String"));
            Assert.Contains(signatures, s => s.Contains("Changed(ThingHandler)"));
            Assert.False((bool)members["truncated"]);
        }

        [Fact]
        public void AMemberCapTruncatesAndSaysSo()
        {
            var members = DevReflection.Members(typeof(Thing), false, 2);
            Assert.Equal(2, (int)members["listed"]);
            Assert.True((bool)members["truncated"]);
        }

        [Fact]
        public void AnEnumerationsMembersAreItsLiterals()
        {
            // The IDE's prompts take enums (PromptResult/PromptChoice); before
            // this they listed nothing, because a literal is a static field and
            // the sweep only walked properties, methods and events.
            var members = DevReflection.Members(typeof(Colour), true, 0);
            var signatures = ((List<object>)members["signatures"]).Cast<string>().ToList();
            Assert.Contains("Colour.Red = 1", signatures);
            Assert.Contains("Colour.Green = 2", signatures);
            Assert.Contains("Colour.Blue = 4", signatures);
            Assert.Equal(3, (int)members["count"]);
        }

        [Fact]
        public void AnEnumValueListsItsLiteralsWithoutStaticRoot()
        {
            // Reached as a return value (Colour.Green), not as a static root:
            // the literals are static, so the listing must not depend on that.
            var members = DevReflection.Members(Colour.Green.GetType(), false, 0);
            var signatures = ((List<object>)members["signatures"]).Cast<string>().ToList();
            Assert.Contains("Colour.Red = 1", signatures);
        }

        [Fact]
        public void APublicFieldIsListedAsAMember()
        {
            var members = DevReflection.Members(typeof(Fielder), false, 0);
            var signatures = ((List<object>)members["signatures"]).Cast<string>().ToList();
            Assert.Contains("Fielder.Name : String", signatures);
        }

        [Fact]
        public void AStaticRootOfAnInterfaceListsItsInstanceMembers()
        {
            // `static:_3S...IEditorView` names an interface: nothing there is
            // static, so the useful listing is the instance members.
            var members = DevReflection.Members(typeof(IThing), true, 0);
            var signatures = ((List<object>)members["signatures"]).Cast<string>().ToList();
            Assert.Contains(signatures, s => s.Contains("Twice(Int32 n) -> Int32"));
            Assert.NotNull(DevReflection.ResolveProperty(typeof(IThing), true, "Label"));
        }

        [Fact]
        public void VendorNamespacesSortFirst()
        {
            Assert.Equal(0, DevReflection.VendorRank("_3S.CoDeSys.Core.Online.IOnlineApplication"));
            Assert.Equal(0, DevReflection.VendorRank("CODESYS.Online.IFoo"));
            Assert.Equal(1, DevReflection.VendorRank("System.String"));
            Assert.Equal(2, DevReflection.VendorRank(null));
        }
    }

    public class DevListenTests
    {
        [Fact]
        public void AnEventOfACustomDelegateTypeIsBuiltAndRaised()
        {
            var thing = new Thing();
            var seen = new List<object[]>();
            var handler = DevListen.Build(typeof(ThingHandler), seen.Add);

            thing.Changed += (ThingHandler)handler;
            thing.Fire();

            Assert.Single(seen);
            Assert.Same(thing, seen[0][0]);
            Assert.IsType<ThingArgs>(seen[0][1]);
        }

        [Fact]
        public void TheHandlerIsARealMethodTheIdeCanInvokeReflectively()
        {
            // CODESYS raises an event inside its own WeakMulticastDelegate by
            // calling handler.Method.Invoke(...). A delegate compiled from an
            // Expression is backed by a DynamicMethod, whose MethodInfo is an
            // RTDynamicMethod, and that call throws ArgumentException inside the
            // IDE's event pump (it crashed the IDE live in t53). The handler must
            // therefore be an ordinary method.
            var seen = new List<object[]>();
            var handler = DevListen.Build(typeof(ThingHandler), seen.Add);

            Assert.DoesNotContain("Dynamic", handler.Method.GetType().Name);
            handler.Method.Invoke(null, new object[] { "sender", new ThingArgs(1, "x") });

            Assert.Single(seen);
            Assert.Equal("sender", seen[0][0]);
        }

        [Fact]
        public void AValueTypedParameterIsBoxedAndANonVoidResultIsIgnored()
        {
            var seen = new List<object[]>();
            var handler = DevListen.Build(typeof(Func<int, int>), seen.Add);

            Assert.Equal(0, handler.DynamicInvoke(7));
            Assert.Single(seen);
            Assert.Equal(7, seen[0][0]);
        }

        [Fact]
        public void AnEventHandlerOfTheFrameworkTypeBuildsToo()
        {
            var seen = new List<object[]>();
            var handler = DevListen.Build(typeof(EventHandler), seen.Add);

            ((EventHandler)handler)(null, EventArgs.Empty);
            Assert.Single(seen);
        }

        [Fact]
        public void TheSnapshotKeepsTheArgumentsPublicProperties()
        {
            var snapshot = DevListen.Snapshot(new ThingArgs(3, "hello"));
            Assert.Equal(typeof(ThingArgs).FullName, snapshot["type"]);
            var properties = (IDictionary<string, object>)snapshot["properties"];
            // Values are text: an event's arguments must never fail the wire.
            Assert.Equal("3", properties["Value"]);
            Assert.Equal("hello", properties["Note"]);
        }

        [Fact]
        public void TheSnapshotOfNullIsJustItsType()
        {
            var snapshot = DevListen.Snapshot(null);
            Assert.Null(snapshot["type"]);
            Assert.Empty((IDictionary<string, object>)snapshot["properties"]);
        }

        [Fact]
        public void AnEventIsFoundOnTheTypeOrAnInterface()
        {
            Assert.Equal("Changed", DevListen.ResolveEvent(typeof(Thing), false, "Changed").Name);
        }
    }
}
