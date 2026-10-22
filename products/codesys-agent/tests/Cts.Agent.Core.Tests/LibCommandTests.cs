using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
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
            Assert.Contains("\n  placeholder Standard -> Standard, 3.5.22.0 (System)\n", output);
        }

        // Several CODESYS versions on one PC share the library repository:
        // the newest there is what * loads, even in the older CODESYS.
        [Fact]
        public void ListNamesTheVersionAStarLoadsHere()
        {
            var libraries = Path.Combine(_root, "codesys");
            foreach (var version in new[] { "1.0.9.0", "1.0.10.0", "browsercache" })
                Directory.CreateDirectory(Path.Combine(libraries, "Managed Libraries", "PSV Electro", "PSVRetain", version));

            var output = Lib("lib", "--libraries", libraries).output;

            Assert.Contains("\n  PSVRetain  PSVRetain, * (PSV Electro)  * is 1.0.10.0 here\n", output);
            Assert.Contains("\n  PSVRetain  PSVRetain, * (PSV Electro)\n", Lib("lib").output);
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
        public void AddThroughAPlaceholderWritesAPlaceholderReference()
        {
            var (code, output, _) = Lib("lib", "add", "CAA Net Base Services, 3.5.15.0 (CAA Technical Workgroup)", "--namespace", "NBS", "--placeholder", "CAA NetBaseSrv");

            Assert.Equal(0, code);
            Assert.Contains("App/Library Manager.xml: CAA Net Base Services, 3.5.15.0 (CAA Technical Workgroup) through placeholder CAA NetBaseSrv, namespace NBS\n", output);
            Assert.Contains("\n  NBS  CAA Net Base Services, 3.5.15.0 (CAA Technical Workgroup)  placeholder CAA NetBaseSrv\n", Lib("lib").output);
            Assert.Contains("<Single Name=\"ResolverGuid\" Type=\"System.Guid\">b303f5ce-75ff-4668-a777-7da8debb449c</Single>", File.ReadAllText(_manager));
            Assert.Contains("already references NBS", Lib("lib", "add", "Other, * (Vendor)", "--namespace", "Other", "--placeholder", "CAA NetBaseSrv").error);

            Assert.StartsWith("ok lib-remove changed=1\n", Lib("lib", "remove", "CAA NetBaseSrv").output);
            Assert.Equal(_original, File.ReadAllText(_manager));
        }

        // A library project starts with no Library Manager: the first lib add
        // writes one at the project root, which cts import creates there.
        [Fact]
        public void AddToAProjectWithoutALibraryManagerCreatesOneAtTheRoot()
        {
            File.Delete(_manager);
            Assert.Contains("cts lib add creates one", Lib("lib").error);

            var (code, output, _) = Lib("lib", "add", "Standard, * (System)", "--namespace", "Standard");

            Assert.Equal(0, code);
            Assert.Contains("\nPOUs/Library Manager.xml: Standard, * (System), namespace Standard\n", output);
            Assert.Contains("\n  Standard  Standard, * (System)\n", Lib("lib").output);
            var created = File.ReadAllText(Path.Combine(_root, "project-view", "POUs", "Library Manager.xml"));
            Assert.Contains("<Single Name=\"ParentGuid\" Type=\"System.Guid\">00000000-0000-0000-0000-000000000000</Single>", created);
            Assert.DoesNotContain("{guid}", created);
            System.Xml.Linq.XDocument.Parse(created);
        }

        // Without --namespace a reference takes the one the installed library
        // names, as the Library Manager's dialog offers it.
        [Fact]
        public void AddTakesTheNamespaceTheInstalledLibraryNames()
        {
            var libraries = Installed("CAA Technical Workgroup", "CAA File", "3.5.19.0", "FILE");

            var (code, output, _) = Lib("lib", "add", "CAA File, * (CAA Technical Workgroup)", "--libraries", libraries);

            Assert.Equal(0, code);
            Assert.Contains("App/Library Manager.xml: CAA File, * (CAA Technical Workgroup), namespace FILE (the library's own)\n", output);
            Assert.Contains("\n  FILE  CAA File, * (CAA Technical Workgroup)\n", Lib("lib").output);
            Lib("lib", "remove", "FILE");
            Assert.Contains(", namespace CF (the library's own is FILE)\n", Lib("lib", "add", "CAA File, 3.5.19.0 (CAA Technical Workgroup)", "--namespace", "CF", "--libraries", libraries).output);
        }

        [Fact]
        public void AddWithoutANamespaceTheLibraryDoesNotNameIsRefused()
        {
            var libraries = Installed("Vendor", "Plain", "1.0.0.0", null);

            var (code, _, error) = Lib("lib", "add", "Nowhere, * (Vendor)", "--libraries", libraries);
            Assert.Equal(2, code);
            Assert.Contains("Nowhere, * (Vendor) is not installed under " + libraries + ", so its namespace is unknown: give --namespace", error);
            Assert.Contains("Plain, * (Vendor) names no default namespace: give --namespace", Lib("lib", "add", "Plain, * (Vendor)", "--libraries", libraries).error);
            Assert.Equal(_original, File.ReadAllText(_manager));
        }

        // The device resolves a placeholder to its own version; the table
        // fixes another for the application, whoever references it.
        [Fact]
        public void RedirectAddsChangesAndDropsATableEntry()
        {
            var (code, output, _) = Lib("lib", "redirect", "CAA Async Manager", "CAA Async Manager, 3.5.17.0 (CAA Technical Workgroup)");

            Assert.Equal(0, code);
            Assert.StartsWith("ok lib-redirect changed=1\nDev/Plc Logic/App/Library Manager.xml: placeholder CAA Async Manager -> CAA Async Manager, 3.5.17.0 (CAA Technical Workgroup)\nNext: cts import", output);
            Assert.Contains("\n  placeholder Standard -> Standard, 3.5.22.0 (System)\n  placeholder CAA Async Manager -> CAA Async Manager, 3.5.17.0 (CAA Technical Workgroup)\n", Lib("lib").output);
            System.Xml.Linq.XDocument.Parse(File.ReadAllText(_manager));
            Assert.Contains("nothing changed", Lib("lib", "redirect", "caa async manager", "CAA Async Manager, 3.5.17.0 (CAA Technical Workgroup)").output);
            Assert.Contains("placeholder CAA Async Manager no longer redirected (was CAA Async Manager, 3.5.17.0 (CAA Technical Workgroup))", Lib("lib", "redirect", "CAA Async Manager").output);
            Assert.Equal(_original, File.ReadAllText(_manager));

            Lib("lib", "redirect", "Standard", "Standard, 3.5.17.0 (System)");
            Assert.Contains("\n  placeholder Standard -> Standard, 3.5.17.0 (System)\n", Lib("lib").output);
            Lib("lib", "redirect", "Standard", "Standard, 3.5.22.0 (System)");
            Assert.Equal(_original, File.ReadAllText(_manager));
            Assert.Contains("nothing changed", Lib("lib", "redirect", "Nothing").output);
            Assert.Equal(2, Lib("lib", "redirect", "Standard", "Standard 3.5").code);
        }

        [Fact]
        public void RedirectOpensAnEmptySelfClosedTable()
        {
            var lines = _original.Split('\n').ToList();
            var start = lines.FindIndex(line => line.Contains("Name=\"PlaceholderRedirectionTable\""));
            var end = lines.FindIndex(start, line => line.Trim() == "</Dictionary>");
            lines.RemoveRange(start + 1, end - start);
            lines[start] = lines[start].Replace("\">", "\" />");
            File.WriteAllText(_manager, string.Join("\n", lines));

            Assert.Equal(0, Lib("lib", "redirect", "Standard", "Standard, 3.5.17.0 (System)").code);

            Assert.Contains("\n  placeholder Standard -> Standard, 3.5.17.0 (System)\n", Lib("lib").output);
            Assert.Contains("PlaceholderRedirectionTable\">\n          <Entry>\n", File.ReadAllText(_manager));
        }

        // A library in the repository under the returned root, whose
        // projectinfo string table names its default namespace (none: null).
        string Installed(string vendor, string name, string version, string defaultNamespace)
        {
            var libraries = Path.Combine(_root, "codesys");
            var folder = Path.Combine(libraries, "Managed Libraries", vendor, name, version);
            Directory.CreateDirectory(folder);
            var bytes = new List<byte> { 2, 0, 1 };
            var number = 3;
            foreach (var text in defaultNamespace == null ? new[] { "Company", vendor } : new[] { "Company", vendor, "DefaultNamespace", defaultNamespace })
            {
                var utf16 = Encoding.Unicode.GetBytes(text);
                bytes.Add((byte)number++);
                bytes.Add((byte)utf16.Length);
                bytes.AddRange(utf16);
            }
            File.WriteAllBytes(Path.Combine(folder, "projectinfo"), bytes.ToArray());
            return libraries;
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
