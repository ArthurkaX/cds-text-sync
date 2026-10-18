using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.FindSymbols;
using Microsoft.CodeAnalysis.MSBuild;

// The agent's members that nothing calls, or that only tests call: the build's
// analyzers see private members only.  Exit 1 when one is not in allow.txt, or
// when allow.txt names a member gone or called now.  Build Cts.Agent and
// Cts.Cli first: a missing build leaves references unresolved.
//   dotnet run --project tools/DeadSymbols
static class Program
{
    static readonly string Root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));

    static async Task<int> Main()
    {
        MSBuildLocator.RegisterDefaults();
        return await Run();
    }

    static async Task<int> Run()
    {
        var workspace = MSBuildWorkspace.Create();
        await workspace.OpenProjectAsync(Path.Combine(Root, "src/Cts.Agent/Cts.Agent.csproj"));
        await workspace.OpenProjectAsync(Path.Combine(Root, "src/Cts.Cli/Cts.Cli.csproj"));
        await workspace.OpenProjectAsync(Path.Combine(Root, "tests/Cts.Agent.Core.Tests/Cts.Agent.Core.Tests.csproj"));
        var solution = SameFramework(workspace.CurrentSolution);
        var allowed = new HashSet<string>(File.ReadAllLines(Path.Combine(Root, "tools/DeadSymbols/allow.txt"))
            .Select(line => line.Trim()).Where(line => line.Length > 0 && !line.StartsWith("#")));

        // A multi-targeted project loads once per framework: a member is used
        // when any of its copies is.
        var uses = new Dictionary<string, int[]>();
        var where = new Dictionary<string, string>();
        foreach (var project in solution.Projects.Where(p => !IsTests(p)))
        {
            var compilation = await project.GetCompilationAsync();
            foreach (var symbol in Members(compilation.Assembly.GlobalNamespace).Where(Checked))
            {
                var key = symbol.ToDisplayString();
                var found = (await SymbolFinder.FindReferencesAsync(symbol, solution))
                    .SelectMany(r => r.Locations).ToList();
                int[] count;
                if (!uses.TryGetValue(key, out count)) uses[key] = count = new int[2];
                count[0] += found.Count(l => !IsTests(l.Document.Project));
                count[1] += found.Count(l => IsTests(l.Document.Project));
                var line = symbol.Locations.First(l => l.IsInSource).GetLineSpan();
                where[key] = Path.GetRelativePath(Root, line.Path) + ":" + (line.StartLinePosition.Line + 1);
            }
        }

        var failed = 0;
        foreach (var item in uses.Where(u => u.Value[0] == 0 && !allowed.Contains(u.Key)).OrderBy(u => where[u.Key]))
        {
            Console.WriteLine("{0}  {1}  {2}", item.Value[1] == 0 ? "unused    " : "tests only", where[item.Key], item.Key);
            failed++;
        }
        // An entry for a member gone or called now keeps nothing alive.
        foreach (var name in allowed.Where(name => !uses.TryGetValue(name, out var count) || count[0] > 0).OrderBy(name => name, StringComparer.Ordinal))
        {
            Console.WriteLine("stale allow  {0}  {1}", name, uses.ContainsKey(name) ? "has a caller" : "is no member");
            failed++;
        }
        Console.WriteLine(failed == 0 ? "ok: every member has a caller" : failed + " member(s) without a caller or stale in allow.txt");
        return failed == 0 ? 0 : 1;
    }

    // MSBuildWorkspace binds the net48 agent and cts.exe to the netstandard2.0
    // copy of the multi-targeted Core; rebind them to the net48 copy so their
    // calls resolve.
    static Solution SameFramework(Solution solution)
    {
        var net48 = solution.Projects.Single(p => p.Name == "Cts.Agent.Core(net48)").Id;
        foreach (var name in new[] { "Cts.Agent", "Cts.Cli" })
        {
            var project = solution.Projects.Single(p => p.Name == name);
            foreach (var reference in project.ProjectReferences.ToList())
                solution = solution.RemoveProjectReference(project.Id, reference);
            solution = solution.AddProjectReference(project.Id, new ProjectReference(net48));
        }
        return solution;
    }

    static bool IsTests(Project project) => project.Name.EndsWith(".Tests");

    static bool Checked(ISymbol symbol)
    {
        if (symbol.IsImplicitlyDeclared || !symbol.Locations.Any(l => l.IsInSource)) return false;
        if (symbol is IMethodSymbol method)
        {
            if (method.MethodKind != MethodKind.Ordinary && method.MethodKind != MethodKind.Constructor) return false;
            if (method.IsOverride || method.ExplicitInterfaceImplementations.Any()) return false;
            if (method.MethodKind == MethodKind.Constructor && method.Parameters.Length == 0) return false;
        }
        if (symbol is IPropertySymbol property && property.IsOverride) return false;
        return !ImplementsInterface(symbol);
    }

    static bool ImplementsInterface(ISymbol symbol)
    {
        var type = symbol.ContainingType;
        return type != null && type.AllInterfaces.SelectMany(i => i.GetMembers())
            .Any(member => SymbolEqualityComparer.Default.Equals(type.FindImplementationForInterfaceMember(member), symbol));
    }

    static IEnumerable<ISymbol> Members(INamespaceSymbol ns)
    {
        foreach (var type in ns.GetTypeMembers())
            foreach (var symbol in Members(type)) yield return symbol;
        foreach (var inner in ns.GetNamespaceMembers())
            foreach (var symbol in Members(inner)) yield return symbol;
    }

    static IEnumerable<ISymbol> Members(INamedTypeSymbol type)
    {
        yield return type;
        foreach (var member in type.GetMembers())
        {
            if (member is INamedTypeSymbol nested)
            {
                foreach (var symbol in Members(nested)) yield return symbol;
            }
            else if (!(member is IMethodSymbol accessor && accessor.AssociatedSymbol != null))
            {
                yield return member;
            }
        }
    }
}
