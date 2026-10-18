using System.Reflection;
using Xunit;

namespace Cts.Agent.Tests
{
    // `objects.setfield` finds the type a caller's `prop` names by public
    // metadata only: a public runtime class name plus IObjectProperty.  These
    // stand-in assemblies pin the rules the live IDE relies on.
    public class PropertyTypeTests
    {
        public interface IObjectProperty { }

        public abstract class AbstractProperty : IObjectProperty { }

        public class BuildProperty : IObjectProperty { }

        public class SameNameNotAProperty { }

        public class NoInterface
        {
            public string[] SerializableValueNames { get { return new string[0]; } }
        }

        static readonly Assembly[] Here = { typeof(PropertyTypeTests).Assembly };

        [Fact]
        public void FindsAConcreteTypeByRuntimeName()
        {
            Assert.Equal(typeof(BuildProperty), PropertyType.Find("BuildProperty", Here));
        }

        [Fact]
        public void IgnoresATypeThatDoesNotImplementIObjectProperty()
        {
            Assert.Null(PropertyType.Find("SameNameNotAProperty", Here));
        }

        [Fact]
        public void IgnoresAnAbstractType()
        {
            Assert.Null(PropertyType.Find("AbstractProperty", Here));
        }

        [Fact]
        public void AnUnknownNameIsNull()
        {
            Assert.Null(PropertyType.Find("NoSuchProperty", Here));
            Assert.Null(PropertyType.Find("", Here));
        }

        [Fact]
        public void AnAssemblyThatFailsToLoadIsSkipped()
        {
            // A vendor assembly with members that do not resolve still must not
            // abort the search: the property type on a later assembly is found.
            Assert.Equal(typeof(BuildProperty),
                PropertyType.Find("BuildProperty", new Assembly[] { null, typeof(PropertyTypeTests).Assembly }));
        }
    }
}
