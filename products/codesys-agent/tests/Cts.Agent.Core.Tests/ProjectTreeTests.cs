using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ProjectTreeTests
    {
        [Fact] public void AnEmptyTreeHasNoChildren()
        {
            var root = new ProjectNode { Name = "Root" };
            Assert.False(ProjectTree.Build(root, 0).ContainsKey("children"));
        }

        [Fact] public void NestedTreePreservesGuidAndDepthLimit()
        {
            var root = new ProjectNode { Name = "Root", Guid = "root-guid", Type = "root-type", Children = new List<ProjectNode> {
                new ProjectNode { Name = "Folder", Guid = "folder-guid", Children = new List<ProjectNode> {
                    new ProjectNode { Name = "Leaf", Guid = "leaf-guid" }
                } }
            } };
            var limited = ProjectTree.Build(root, 1);
            var folder = Assert.IsType<List<Dictionary<string, object>>>(limited["children"])[0];
            Assert.Equal("folder-guid", folder["guid"]);
            Assert.False(folder.ContainsKey("children"));
            Assert.Throws<System.ArgumentNullException>(() => ProjectTree.Build(null, 0));
        }

        [Fact] public void TheObjectsOwnNameIsGivenOnlyWhereTheIdeShowsAnother()
        {
            var root = new ProjectNode { Name = "Root", Children = new List<ProjectNode> {
                new ProjectNode { Name = "Symbol Configuration", ObjectName = "Symbols", Guid = "s" },
                new ProjectNode { Name = "GVL", ObjectName = "GVL", Guid = "g" },
            } };
            var children = Assert.IsType<List<Dictionary<string, object>>>(ProjectTree.Build(root, 0)["children"]);
            Assert.Equal("Symbols", children[0]["object_name"]);
            Assert.False(children[1].ContainsKey("object_name"));
        }
    }
}
