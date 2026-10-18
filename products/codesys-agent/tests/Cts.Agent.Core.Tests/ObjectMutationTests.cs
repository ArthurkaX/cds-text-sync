using System;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ObjectMutationTests
    {
        const string Parent = "32d92914-bcb4-4227-b529-32fd90910eca";

        static Request Req(string json)
        {
            return Request.Parse(json);
        }

        static ProtocolException FailCreate(string paramsJson)
        {
            return Assert.Throws<ProtocolException>(
                () => ObjectCreate.From(Req("{\"method\":\"objects.create\",\"params\":" + paramsJson + "}")));
        }

        static ProtocolException FailDelete(string paramsJson)
        {
            return Assert.Throws<ProtocolException>(
                () => ObjectDelete.From(Req("{\"method\":\"objects.delete\",\"params\":" + paramsJson + "}")));
        }

        [Fact]
        public void ReadsAWholeCreate()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"gvl\",\"name\":\"GVL_T\",\"declaration\":\"D\"}}"));
            Assert.Equal(Guid.Parse(Parent), spec.ParentGuid);
            Assert.Equal("gvl", spec.Kind);
            Assert.Equal("_3S.CoDeSys.GVLObject.GVLObject", spec.TypeName);
            Assert.Equal("GVL_T", spec.Name);
            Assert.True(spec.HasDeclaration);
            Assert.Equal("D", spec.Declaration);
        }

        [Fact]
        public void RootCreatesAtTheProjectRootAndExcludesAParent()
        {
            var spec = ObjectCreate.From(Req("{\"method\":\"objects.create\",\"params\":{\"root\":true,\"kind\":\"pou\",\"name\":\"F_X\"}}"));
            Assert.True(spec.AtRoot);
            Assert.Equal(Guid.Empty, spec.ParentGuid);
            var both = FailCreate("{\"root\":true,\"parent_guid\":\"" + Parent + "\",\"kind\":\"pou\",\"name\":\"F_X\"}");
            Assert.Contains("not both", both.Message);
        }

        [Fact]
        public void ADefaultKindIsCaseInsensitive()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent + "\",\"kind\":\"GVL\",\"name\":\"T\"}}"));
            Assert.Equal("gvl", spec.Kind);
        }

        [Fact]
        public void WithoutADeclarationTheKindsDefaultStays()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent + "\",\"kind\":\"gvl\",\"name\":\"T\"}}"));
            Assert.False(spec.HasDeclaration);
            Assert.Null(spec.Declaration);
        }

        [Fact]
        public void AnEmptyDeclarationIsARealEdit()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent + "\",\"kind\":\"gvl\",\"name\":\"T\",\"declaration\":\"\"}}"));
            Assert.True(spec.HasDeclaration);
            Assert.Equal("", spec.Declaration);
        }

        [Fact]
        public void AnUnknownKindNamesTheSupportedOnes()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent + "\",\"kind\":\"foo\",\"name\":\"T\"}");
            Assert.Equal("bad_params", ex.Code);
            Assert.Contains("gvl", ex.Message);
            Assert.Contains("pou", ex.Message);
            Assert.Contains("method", ex.Message);
        }

        [Theory]
        [InlineData("pou", "_3S.CoDeSys.POUObject.POUObject")]
        [InlineData("POU", "_3S.CoDeSys.POUObject.POUObject")]
        [InlineData("method", "_3S.CoDeSys.MethodObject.POUMethodObject")]
        [InlineData("METHOD", "_3S.CoDeSys.MethodObject.POUMethodObject")]
        [InlineData("action", "_3S.CoDeSys.ActionObject.ActionObject")]
        [InlineData("ACTION", "_3S.CoDeSys.ActionObject.ActionObject")]
        [InlineData("property", "_3S.CoDeSys.PropertyObject.PropertyObject")]
        [InlineData("PROPERTY", "_3S.CoDeSys.PropertyObject.PropertyObject")]
        [InlineData("dut", "_3S.CoDeSys.DUTObject.DUTObject")]
        [InlineData("DUT", "_3S.CoDeSys.DUTObject.DUTObject")]
        [InlineData("interface", "_3S.CoDeSys.InterfaceObject.InterfaceObject")]
        [InlineData("INTERFACE", "_3S.CoDeSys.InterfaceObject.InterfaceObject")]
        [InlineData("folder", "_3S.CoDeSys.DefaultNavigators.FolderObject")]
        [InlineData("FOLDER", "_3S.CoDeSys.DefaultNavigators.FolderObject")]
        public void EveryNewKindMapsToItsFactoriesObjectType(string kind, string typeName)
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"" + kind + "\",\"name\":\"T\"}}"));
            Assert.Equal(kind.ToLowerInvariant(), spec.Kind);
            Assert.Equal(typeName, spec.TypeName);
        }

        [Fact]
        public void ADeclarationAndAnImplementationGoIntoOneEdit()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"method\",\"name\":\"M_T\",\"declaration\":\"D\",\"implementation\":\"I\"}}"));
            var edit = spec.Edit();
            Assert.True(edit.HasDeclaration);
            Assert.Equal("D", edit.Declaration);
            Assert.True(edit.HasImplementation);
            Assert.Equal("I", edit.Implementation);
        }

        [Fact]
        public void NoTextPartMeansNoEditAtAll()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent + "\",\"kind\":\"pou\",\"name\":\"T\"}}"));
            Assert.Null(spec.Edit());
        }

        [Fact]
        public void AnEmptyImplementationIsARealEdit()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"pou\",\"name\":\"T\",\"implementation\":\"\"}}"));
            Assert.True(spec.HasImplementation);
            Assert.Equal("", spec.Implementation);
        }

        [Fact]
        public void AnImplementationOnAGvlIsRefusedBeforeTheIde()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"gvl\",\"name\":\"T\",\"implementation\":\"I\"}");
            Assert.Equal("bad_params", ex.Code);
            Assert.Contains("implementation", ex.Message);
        }

        [Fact]
        public void AnActionHasAnImplementationButNoDeclarationRequirement()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"action\",\"name\":\"A_T\",\"implementation\":\"x := 1;\"}}"));
            Assert.True(spec.HasImplementation);
            Assert.Equal("x := 1;", spec.Implementation);
        }

        [Fact]
        public void ADutRefusesAnImplementation()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"dut\",\"name\":\"T\",\"implementation\":\"I\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void AnInterfaceIsDeclarationOnly()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"interface\",\"name\":\"I_T\",\"declaration\":\"INTERFACE I_T\"}}"));
            Assert.Equal("_3S.CoDeSys.InterfaceObject.InterfaceObject", spec.TypeName);
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"interface\",\"name\":\"I_T\",\"implementation\":\"I\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void AnInterfaceMethodIsADifferentFactoryThanAPouMethod()
        {
            Assert.Equal("_3S.CoDeSys.MethodObject.InterfaceMethodObject", ObjectKinds.InterfaceMethodType);
        }

        [Fact]
        public void AFolderMapsToItsFactoriesObjectType()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"folder\",\"name\":\"F\",\"structured_view\":\"d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84\"}}"));
            Assert.Equal("_3S.CoDeSys.DefaultNavigators.FolderObject", spec.TypeName);
            Assert.Equal(Guid.Parse("d9b2b2cc-ea99-4c3b-aa42-1e5c49e65b84"), spec.StructuredView);
        }

        [Fact]
        public void AFolderRefusesAnyText()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"folder\",\"name\":\"F\",\"declaration\":\"D\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void WithoutAStructuredViewThereIsNone()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent + "\",\"kind\":\"gvl\",\"name\":\"T\"}}"));
            Assert.False(spec.StructuredView.HasValue);
        }

        [Fact]
        public void AStructuredViewThatIsNotAGuidIsRefused()
        {
            Assert.Equal("bad_params", FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"folder\",\"name\":\"F\",\"structured_view\":\"nope\"}").Code);
            Assert.Equal("bad_params", FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"folder\",\"name\":\"F\",\"structured_view\":\"00000000-0000-0000-0000-000000000000\"}").Code);
        }

        [Fact]
        public void APropertyTakesItsAccessorBodies()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"property\",\"name\":\"P_T\",\"declaration\":\"PROPERTY P_T : BOOL\""
                + ",\"accessors\":{\"Get\":\"G\",\"Set\":\"S\"}}}"));
            Assert.Equal("G", spec.Accessors["Get"]);
            Assert.Equal("S", spec.Accessors["Set"]);
        }

        [Fact]
        public void AnAccessorOnANonPropertyIsRefusedBeforeTheIde()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"pou\",\"name\":\"T\",\"accessors\":{\"Get\":\"G\"}}");
            Assert.Equal("bad_params", ex.Code);
            Assert.Contains("accessors", ex.Message);
        }

        [Fact]
        public void AnAccessorThatIsNotGetOrSetIsRefused()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"property\",\"name\":\"T\",\"accessors\":{\"Foo\":\"G\"}}");
            Assert.Equal("bad_params", ex.Code);
            Assert.Contains("Get", ex.Message);
        }

        [Fact]
        public void AnAccessorBodyThatIsNotAStringIsRefused()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"property\",\"name\":\"T\",\"accessors\":{\"Get\":1}}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void APropertyWithNoAccessorsKeepsTheEmptyMap()
        {
            var spec = ObjectCreate.From(Req(
                "{\"method\":\"objects.create\",\"params\":{\"parent_guid\":\"" + Parent
                + "\",\"kind\":\"property\",\"name\":\"T\"}}"));
            Assert.Empty(spec.Accessors);
        }

        [Fact]
        public void AMissingKindIsBadParams()
        {
            Assert.Equal("bad_params", FailCreate("{\"parent_guid\":\"" + Parent + "\",\"name\":\"T\"}").Code);
        }

        [Fact]
        public void AnEmptyNameIsRefused()
        {
            var ex = FailCreate("{\"parent_guid\":\"" + Parent + "\",\"kind\":\"gvl\",\"name\":\"\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void AMissingNameIsBadParams()
        {
            Assert.Equal("bad_params", FailCreate("{\"parent_guid\":\"" + Parent + "\",\"kind\":\"gvl\"}").Code);
        }

        [Fact]
        public void ABadParentGuidIsRefused()
        {
            Assert.Equal("bad_params", FailCreate("{\"parent_guid\":\"not-a-guid\",\"kind\":\"gvl\",\"name\":\"T\"}").Code);
        }

        [Fact]
        public void TheEmptyParentGuidIsRefusedBeforeTheIde()
        {
            var ex = FailCreate("{\"parent_guid\":\"00000000-0000-0000-0000-000000000000\",\"kind\":\"gvl\",\"name\":\"T\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void AMissingParentGuidIsBadParams()
        {
            Assert.Equal("bad_params", FailCreate("{\"kind\":\"gvl\",\"name\":\"T\"}").Code);
        }

        [Fact]
        public void DeleteReadsAWholeGuid()
        {
            var spec = ObjectDelete.From(Req("{\"method\":\"objects.delete\",\"params\":{\"guid\":\"" + Parent + "\"}}"));
            Assert.Equal(Guid.Parse(Parent), spec.Guid);
        }

        [Fact]
        public void DeleteRefusesTheEmptyGuid()
        {
            var ex = FailDelete("{\"guid\":\"00000000-0000-0000-0000-000000000000\"}");
            Assert.Equal("bad_params", ex.Code);
        }

        [Fact]
        public void DeleteRefusesAGuidThatDoesNotParse()
        {
            Assert.Equal("bad_params", FailDelete("{\"guid\":\"12345\"}").Code);
        }

        [Fact]
        public void DeleteRefusesAMissingGuid()
        {
            Assert.Equal("bad_params", FailDelete("{}").Code);
        }

        static ProtocolException FailRename(string paramsJson)
        {
            return Assert.Throws<ProtocolException>(
                () => ObjectRename.From(Req("{\"method\":\"objects.rename\",\"params\":" + paramsJson + "}")));
        }

        [Fact]
        public void RenameReadsAGuidAndAName()
        {
            var spec = ObjectRename.From(Req("{\"method\":\"objects.rename\",\"params\":{\"guid\":\"" + Parent + "\",\"name\":\"FB_Drive\"}}"));
            Assert.Equal(Guid.Parse(Parent), spec.Guid);
            Assert.Equal("FB_Drive", spec.Name);
        }

        [Fact]
        public void MoveReadsTheObjectAndItsNewParent()
        {
            var spec = ObjectMove.From(Req("{\"method\":\"objects.move\",\"params\":{\"guid\":\"" + Parent + "\",\"parent_guid\":\"22222222-2222-2222-2222-222222222222\"}}"));
            Assert.Equal(Guid.Parse(Parent), spec.Guid);
            Assert.Equal(Guid.Parse("22222222-2222-2222-2222-222222222222"), spec.ParentGuid);
            Assert.Throws<ProtocolException>(() => ObjectMove.From(Req("{\"method\":\"objects.move\",\"params\":{\"guid\":\"" + Parent + "\"}}")));
        }

        [Fact]
        public void RenameRefusesAnEmptyName()
        {
            Assert.Equal("bad_params", FailRename("{\"guid\":\"" + Parent + "\",\"name\":\"\"}").Code);
        }

        [Fact]
        public void RenameRefusesAGuidThatDoesNotParse()
        {
            Assert.Equal("bad_params", FailRename("{\"guid\":\"12345\",\"name\":\"FB_Drive\"}").Code);
        }
    }
}
