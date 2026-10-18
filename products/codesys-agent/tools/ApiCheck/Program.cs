using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;

// Check the reflection names used by the in-IDE agent against an installation.
static class Program
{
    sealed record Use(string Name, string File, int Line);
    static string Root => Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../.."));

    static int Main(string[] args)
    {
        if (args.Length != 1 || !Directory.Exists(args[0]))
        {
            Console.Error.WriteLine("usage: ApiCheck <folder with CODESYS dlls>");
            return 2;
        }

        var types = new Dictionary<string, Use>(StringComparer.Ordinal);
        var members = new Dictionary<string, Use>(StringComparer.Ordinal);
        int skipped = 0;
        var sourceRoot = Path.Combine(Root, "src");
        var files = Directory.EnumerateFiles(Path.Combine(sourceRoot, "Cts.Agent"), "*.cs", SearchOption.AllDirectories)
            .Concat(Directory.EnumerateFiles(Path.Combine(sourceRoot, "Cts.Agent.Core"), "*.cs", SearchOption.AllDirectories))
            .Select(file => (file, root: CSharpSyntaxTree.ParseText(File.ReadAllText(file), path: file).GetRoot())).ToList();
        // String constants and the fields and locals assigned from FindType("...") are
        // collected over all files first: Ide's partial files share its interface fields.
        var constants = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var variable in files.SelectMany(f => f.root.DescendantNodes().OfType<VariableDeclaratorSyntax>()))
            if (variable.Initializer != null && StringArg(variable.Initializer.Value) is string text) constants[variable.Identifier.ValueText] = text;
        var known = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var (_, model) in files)
        {
            foreach (var variable in model.DescendantNodes().OfType<VariableDeclaratorSyntax>())
            {
                var name = FindName(variable.Initializer?.Value, constants);
                if (name != null) known[variable.Identifier.ValueText] = name;
            }
            foreach (var assignment in model.DescendantNodes().OfType<AssignmentExpressionSyntax>())
            {
                var name = FindName(assignment.Right, constants);
                if (name != null && assignment.Left is IdentifierNameSyntax id) known[id.Identifier.ValueText] = name;
            }
        }
        foreach (var (file, model) in files)
        {
            foreach (var literal in model.DescendantNodes().OfType<LiteralExpressionSyntax>())
            {
                if (!literal.IsKind(SyntaxKind.StringLiteralExpression)) continue;
                var value = literal.Token.ValueText;
                if (IsTypeName(value))
                    Add(types, value, UseAt(value, literal, file));
            }

            foreach (var invocation in model.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var access = invocation.Expression as MemberAccessExpressionSyntax;
                var method = access?.Name.Identifier.ValueText ?? (invocation.Expression as IdentifierNameSyntax)?.Identifier.ValueText;
                string typeName = null, memberName = null;
                var argsList = invocation.ArgumentList.Arguments;
                if ((method == "Prop" || method == "NeedMethod") && argsList.Count >= 2)
                {
                    typeName = ResolveType(argsList[0].Expression, known, constants);
                    memberName = StringArg(argsList[1].Expression);
                }
                else if (access != null && (method == "GetMethod" || method == "GetProperty" || method == "GetField") && argsList.Count >= 1)
                {
                    typeName = ResolveType(access.Expression, known, constants);
                    memberName = StringArg(argsList[0].Expression);
                }
                if (memberName == null) continue;
                if (typeName == null || !IsTypeName(typeName)) { skipped++; continue; }
                Add(members, typeName + "." + memberName, UseAt(memberName, invocation, file));
            }
        }

        var dlls = Directory.EnumerateFiles(args[0], "*.dll", SearchOption.AllDirectories)
            .Where(p => !p.EndsWith(".resources.dll", StringComparison.OrdinalIgnoreCase)).ToArray();
        var paths = dlls.Concat(((string)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")).Split(Path.PathSeparator)).Distinct(StringComparer.OrdinalIgnoreCase);
        var resolver = new PathAssemblyResolver(paths);
        using var context = new MetadataLoadContext(resolver);
        var loaded = new List<Assembly>();
        foreach (var path in dlls)
        {
            try { loaded.Add(context.LoadFromAssemblyPath(Path.GetFullPath(path))); }
            catch (BadImageFormatException) { }
            catch (FileLoadException) { }
        }
        var availableTypes = new Dictionary<string, Type>(StringComparer.Ordinal);
        foreach (var assembly in loaded)
        {
            try
            {
                foreach (var type in assembly.GetTypes())
                    if (type.FullName != null) availableTypes[type.FullName] = type;
            }
            catch (ReflectionTypeLoadException e)
            {
                foreach (var type in e.Types.Where(t => t?.FullName != null)) availableTypes[type.FullName] = type;
            }
        }

        var optional = File.ReadAllLines(Path.Combine(Root, "tools/ApiCheck/optional.txt"))
            .Select(l => l.Split('#')[0].Trim()).Where(l => l.Length > 0).ToHashSet(StringComparer.Ordinal);
        var missing = new List<string>();
        foreach (var use in types.Values.OrderBy(u => u.File).ThenBy(u => u.Line))
        {
            if (!ContainsType(use.Name, availableTypes))
            {
                var line = $"missing type {use.Name} ({use.File}:{use.Line})";
                Console.WriteLine(line);
                if (!optional.Contains(use.Name)) missing.Add(line);
            }
        }
        foreach (var use in members.Values.OrderBy(u => u.File).ThenBy(u => u.Line))
        {
            var split = use.Name.LastIndexOf('.');
            if (split < 0) continue;
            var typeName = use.Name.Substring(0, split);
            var memberName = use.Name.Substring(split + 1);
            if (!availableTypes.TryGetValue(typeName, out var type) || Declares(type, memberName)) continue;
            var line = $"missing member {use.Name} ({use.File}:{use.Line})";
            Console.WriteLine(line);
            if (!optional.Contains(use.Name)) missing.Add(line);
        }
        Console.WriteLine($"{types.Count} types checked, {members.Count} members checked, {skipped} runtime lookups skipped; {missing.Count} required name(s) missing");
        return missing.Count == 0 ? 0 : 1;
    }

    static bool ContainsType(string name, Dictionary<string, Type> types) => types.ContainsKey(name) || types.ContainsKey(name.Replace('+', '.'));
    static bool Declares(Type type, string name)
    {
        for (var current = type; current != null; current = current.BaseType)
        {
            if (current.GetMember(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Length > 0) return true;
            foreach (var iface in current.GetInterfaces())
                if (iface.GetMember(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly).Length > 0 ||
                    iface.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static) != null) return true;
        }
        return type.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static) != null;
    }
    static bool IsTypeName(string value) => value.StartsWith("_3S.", StringComparison.Ordinal) && value.Length > 4 && char.IsLetter(value[4]) && !value.EndsWith(".", StringComparison.Ordinal);
    static string FindName(ExpressionSyntax expression, Dictionary<string, string> constants)
    {
        if (expression is not InvocationExpressionSyntax i || !i.Expression.ToString().EndsWith("FindType", StringComparison.Ordinal) || i.ArgumentList.Arguments.Count == 0) return null;
        return Eval(i.ArgumentList.Arguments[0].Expression, constants);
    }
    static string Eval(ExpressionSyntax expression, Dictionary<string, string> constants)
    {
        if (StringArg(expression) is string literal) return literal;
        if (expression is IdentifierNameSyntax id && constants.TryGetValue(id.Identifier.ValueText, out var value)) return value;
        if (expression is BinaryExpressionSyntax binary && binary.IsKind(SyntaxKind.AddExpression))
        {
            var left = Eval(binary.Left, constants); var right = Eval(binary.Right, constants);
            if (left != null && right != null) return left + right;
        }
        return null;
    }
    static string ResolveType(ExpressionSyntax expression, Dictionary<string, string> known, Dictionary<string, string> constants) => FindName(expression, constants) ?? (expression is IdentifierNameSyntax id && known.TryGetValue(id.Identifier.ValueText, out var name) ? name : null);
    static string StringArg(ExpressionSyntax expression) => expression is LiteralExpressionSyntax l && l.IsKind(SyntaxKind.StringLiteralExpression) ? l.Token.ValueText : null;
    static Use UseAt(string value, SyntaxNode node, string path) => new(value, Path.GetRelativePath(Root, path).Replace('\\', '/'), node.GetLocation().GetLineSpan().StartLinePosition.Line + 1);
    static void Add(Dictionary<string, Use> items, string key, Use use) { if (!items.ContainsKey(key)) items.Add(key, use); }
}
