using System;
using System.IO;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    // cts lib reads and edits the Library Manager files on disk; only the
    // lines of the reference it changes move.
    public sealed class LibCommandTests : IDisposable
    {
        readonly string _root = Path.Combine(Path.GetTempPath(), "cts-lib-" + Guid.NewGuid().ToString("N"));
        readonly string _manager;
        readonly string _original;

        public LibCommandTests()
        {
            var app = Path.Combine(_root, "project-view", "Dev", "Plc Logic", "App");
            Directory.CreateDirectory(app);
            _manager = Path.Combine(app, "Library Manager.xml");
            File.Copy(Path.Combine(AppContext.BaseDirectory, "Golden", "Docs", "Library Manager.xml"), _manager);
            _original = File.ReadAllText(_manager);
        }

        public void Dispose() => Directory.Delete(_root, true);

        [Fact]
        public void ListNamesEachReferenceWithItsNamespaceAndQualifiedOnly()
        {
            var (code, output, _) = Lib("lib");

            Assert.Equal(0, code);
            Assert.StartsWith("ok lib managers=1 libraries=", output);
            Assert.Contains("\nDev/Plc Logic/App/Library Manager.xml:\n", output);
            Assert.Contains("\n  DED  CAA Device Diagnosis, 3.5.15.0 (CAA Technical Workgroup)  placeholder CAA Device Diagnosis  qualified-only\n", output);
            Assert.Contains("\n  PSVRetain  PSVRetain, * (PSV Electro)\n", output);
        }

        [Fact]
        public void SetChangesOnlyTheFlagsLine()
        {
            var (code, output, _) = Lib("lib", "set", "DED", "--qualified-only", "off");

            Assert.Equal(0, code);
            Assert.StartsWith("ok lib-set changed=1\nDev/Plc Logic/App/Library Manager.xml: CAA Device Diagnosis, 3.5.15.0 (CAA Technical Workgroup)\nNext: cts import", output);
            var before = _original.Split('\n');
            var after = File.ReadAllText(_manager).Split('\n');
            Assert.Equal(before.Length, after.Length);
            var moved = Enumerable.Range(0, before.Length).Where(i => before[i] != after[i]).ToList();
            Assert.Single(moved);
            Assert.Equal(before[moved[0]].Replace(">True<", ">False<"), after[moved[0]]);
            Assert.Contains("nothing changed", Lib("lib", "set", "CAA Device Diagnosis", "--qualified-only", "off").output);
        }

        [Fact]
        public void AddWritesADirectReferenceThatListAndRemoveFind()
        {
            var (code, output, _) = Lib("lib", "add", "CAA Net Base Services, * (CAA Technical Workgroup)", "--namespace", "NBS");

            Assert.Equal(0, code);
            Assert.StartsWith("ok lib-add changed=1\n", output);
            Assert.Contains("\n  NBS  CAA Net Base Services, * (CAA Technical Workgroup)\n", Lib("lib").output);
            var again = Lib("lib", "add", "CAA Net Base Services, 3.5.17.0 (CAA Technical Workgroup)", "--namespace", "NBS2");
            Assert.StartsWith("error lib-add cause=\"already referenced\"", again.output);
            Assert.Contains("already references NBS  CAA Net Base Services", again.error);

            Assert.StartsWith("ok lib-remove changed=1\n", Lib("lib", "remove", "NBS").output);
            Assert.Equal(_original, File.ReadAllText(_manager));
        }

        [Fact]
        public void UnknownNamesAndMalformedLibrariesAreRefused()
        {
            Assert.Contains("no Library Manager references Nothing", Lib("lib", "remove", "Nothing").error);
            var (code, output, error) = Lib("lib", "add", "Standard", "--namespace", "Standard");
            Assert.Equal(2, code);
            Assert.Contains("LIBRARY is \"Name, Version (Vendor)\"", output + error);
            Assert.Contains("no Library Manager belongs to Other; the managers are in: App", Lib("lib", "--app", "Other").error);
            Assert.Equal(_original, File.ReadAllText(_manager));
        }

        (int code, string output, string error) Lib(params string[] args) => CliTests.RunLocal(args.Concat(new[] { "--workspace", _root }).ToArray());
    }
}
