using System.IO;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ProjectFilesTests
    {
        static readonly string Root = Path.Combine(Path.GetTempPath(), "cts-projects");

        [Fact]
        public void NameIsTheFileName()
        {
            Assert.Equal("Plant", ProjectFiles.DisplayName(Path.Combine(Root, "Plant.project")));
            Assert.Equal("", ProjectFiles.DisplayName(""));
        }

        [Fact]
        public void ALibraryIsADotLibraryFile()
        {
            Assert.True(ProjectFiles.IsLibrary(Path.Combine(Root, "Util.library")));
            Assert.True(ProjectFiles.IsLibrary(Path.Combine(Root, "Util.LIBRARY")));
            Assert.False(ProjectFiles.IsLibrary(Path.Combine(Root, "Plant.project")));
            Assert.False(ProjectFiles.IsLibrary(Path.Combine(Root, "Util.compiled-library")));
            Assert.False(ProjectFiles.IsLibrary(""));
        }

        [Fact]
        public void SamePathIgnoresCaseAndATrailingSeparator()
        {
            var path = Path.Combine(Root, "Plant.project");
            Assert.True(ProjectFiles.SamePath(path, path.ToUpperInvariant()));
            Assert.True(ProjectFiles.SamePath(Root, Root + Path.DirectorySeparatorChar));
            Assert.False(ProjectFiles.SamePath(path, Path.Combine(Root, "Other.project")));
            Assert.False(ProjectFiles.SamePath("", path));
        }

        [Fact]
        public void OpenNeedsAnAbsolutePathToAFile()
        {
            Directory.CreateDirectory(Root);
            var file = Path.Combine(Root, "Exists.project");
            File.WriteAllText(file, "");
            ProjectFiles.RequireOpenable(file);
            Assert.Contains("requires a 'path'", Assert.Throws<ProtocolException>(() => ProjectFiles.RequireOpenable("")).Message);
            Assert.Contains("must be absolute", Assert.Throws<ProtocolException>(() => ProjectFiles.RequireOpenable("Exists.project")).Message);
            Assert.Contains("No project file", Assert.Throws<ProtocolException>(() => ProjectFiles.RequireOpenable(Path.Combine(Root, "Gone.project"))).Message);
            File.Delete(file);
        }

        [Fact]
        public void UnsavedRefusalNamesWhatToRunFirst()
        {
            var e = ProjectFiles.Unsaved("The project", "`cts project close`");
            Assert.Equal(ErrorCodes.BadParams, e.Code);
            Assert.Equal("The project has unsaved changes. Run `cts save`, then `cts project close`, or discard the changes in CODESYS.", e.Message);
        }
    }
}
