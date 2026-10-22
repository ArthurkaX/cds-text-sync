using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class SvWalkTests
    {
        sealed class Node
        {
            public Guid Guid = Guid.NewGuid();
            public string Name, ObjectName;
            public int Index = -1;
            public bool TaskCall;
            public Guid Type = Guid.NewGuid();
            public List<Node> Children = new List<Node>();
            public Node(string name, params Node[] children) { Name = name; Children.AddRange(children); }
        }

        static readonly SvNodeAccess Access = new SvNodeAccess
        {
            ObjectOf = n => ((Node)n).Guid,
            NameOf = n => ((Node)n).Name,
            ObjectNameOf = n => ((Node)n).ObjectName,
            ChildrenOf = n => ((Node)n).Children.Cast<object>(),
            IndexOf = n => ((Node)n).Index,
            Skip = n => ((Node)n).TaskCall,
            TypeOf = n => ((Node)n).Type,
        };

        [Fact]
        public void EntriesComeDepthFirstWithTheirAncestorsObjectNamesAsPath()
        {
            var main = new Node("MAIN");
            var app = new Node("Application", main);
            var logic = new Node("PLC Logic", app) { Index = 0, ObjectName = "Plc Logic" };
            var device = new Node("PLC_Stabur", logic);

            var placements = SvWalk.Walk(new object[] { device, new Node("GlobalTextList") }, Access).ToList();

            Assert.Equal(new[] { device.Guid, logic.Guid, app.Guid, main.Guid },
                placements.Take(4).Select(p => p.Object).ToArray());
            Assert.True(placements[0].IsRoot);
            Assert.Equal(Guid.Empty, placements[0].ParentNode);
            Assert.Empty(placements[0].Path);
            Assert.False(placements[3].IsRoot);
            Assert.Equal(app.Guid, placements[3].ParentNode);
            // The object's name, not the label the IDE shows.
            Assert.Equal(new[] { "PLC_Stabur", "Plc Logic", "Application" }, placements[3].Path);
            Assert.Equal(0, placements[1].Index);
            Assert.Equal(-1, placements[3].Index);
            // The second root starts again with an empty path.
            Assert.True(placements[4].IsRoot);
            Assert.Empty(placements[4].Path);
        }

        [Fact]
        public void ASkippedNodeTakesItsSubtreeWithIt()
        {
            var call = new Node("MAIN", new Node("inner")) { TaskCall = true };
            var task = new Node("Task", call);

            var placements = SvWalk.Walk(new object[] { task }, Access).ToList();

            Assert.Single(placements);
            Assert.Equal(task.Guid, placements[0].Object);
        }

        [Fact]
        public void TheTreeKeepsAFoldersObjectsBelowItAndShowsTaskCalls()
        {
            var gvl = new Node("GVL_InFolder");
            var folder = new Node("Folder", gvl);
            var call = new Node("MAIN") { TaskCall = true };
            var app = new Node("Application", folder, new Node("Task", call));

            var tree = SvWalk.Tree(new object[] { app }, Access);

            var root = Assert.Single(tree);
            Assert.Equal("Application", root.Name);
            Assert.Equal(app.Type.ToString("D"), root.Type);
            var inFolder = Assert.Single(root.Children[0].Children);
            Assert.Equal(gvl.Guid.ToString("D"), inFolder.Guid);
            Assert.Equal("MAIN", Assert.Single(root.Children[1].Children).Name);
        }
    }
}
