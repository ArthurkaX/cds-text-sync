// Request parsing for `objects.settext`, kept out of the IDE-facing file so the
// validation is tested without a CODESYS process.
//
//   objects.settext {"guid", "declaration"?, "implementation"?}
//
// Either part may be absent; an empty string is a real value (it clears the
// part).  At least one part must be named: a call that names neither would
// rewrite the object unchanged, so it is refused as bad_params.
namespace Cts.Agent
{
    public sealed class TextEdit
    {
        public bool HasDeclaration { get; private set; }
        public string Declaration { get; private set; }
        public bool HasImplementation { get; private set; }
        public string Implementation { get; private set; }

        // A one-part edit built in code (objects.create writes a new object's
        // declaration and implementation through the same SetObjectText path).
        public static TextEdit Of(bool hasDeclaration, string declaration, bool hasImplementation, string implementation)
        {
            return new TextEdit
            {
                HasDeclaration = hasDeclaration,
                Declaration = declaration,
                HasImplementation = hasImplementation,
                Implementation = implementation,
            };
        }

        public static TextEdit From(Request req)
        {
            object raw;
            var hasDeclaration = req.Params.TryGetValue("declaration", out raw) && raw != null;
            var hasImplementation = req.Params.TryGetValue("implementation", out raw) && raw != null;
            if (!hasDeclaration && !hasImplementation)
                throw new ProtocolException(ErrorCodes.BadParams,
                    "objects.settext needs 'declaration' and/or 'implementation'");
            return new TextEdit
            {
                HasDeclaration = hasDeclaration,
                Declaration = hasDeclaration ? req.String("declaration") : null,
                HasImplementation = hasImplementation,
                Implementation = hasImplementation ? req.String("implementation") : null,
            };
        }
    }
}
