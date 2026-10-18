using System;
using System.Collections.Generic;
using Xunit;

namespace Cts.Agent.Tests
{
    // Reading a dialog exactly, and refusing to guess at it (t71).
    //
    // Everything here is pure: the caption rules, the fingerprint, the one-line
    // snapshot and the matching of a caller's names against a dialog.  The part
    // that needs a live IDE -- resolving a Win32 handle to a real control and
    // operating it -- lives in Cts.Agent (ControlReader) and is checked on
    // Windows.
    public class DialogTests
    {
        // The shape the login dialog has: three radios, a check box, three
        // buttons, one caption carrying an accelerator.
        static ModalWindow Login()
        {
            return new ModalWindow
            {
                Hwnd = 200,
                Class = "#32770",
                Title = "CODESYS",
                Text = "The application changed since last download. What do you want to do?",
                Options = new[]
                {
                    new ModalOption("Login with &online change", ModalOptionKind.Radio, false),
                    new ModalOption("Login with &download", ModalOptionKind.Radio, false),
                    new ModalOption("Login without any change", ModalOptionKind.Radio, true),
                    new ModalOption("&Update boot application", ModalOptionKind.Check, false),
                },
                Buttons = new[] { "&OK", "&Cancel", "&Details..." },
                Owner = 0,
                Ownerless = true,
                Enabled = true,
                Visible = true,
            };
        }

        // ---- captions

        [Theory]
        [InlineData("&OK", "OK")]
        [InlineData("&Details...", "Details...")]
        [InlineData("Login with &online change", "Login with online change")]
        [InlineData("  &OK  ", "OK")]
        [InlineData("A && B", "A & B")]
        [InlineData("no mnemonic", "no mnemonic")]
        [InlineData("", "")]
        [InlineData(null, "")]
        [InlineData("trailing&", "trailing")]
        public void AMnemonicIsRemovedAndALiteralAmpersandIsKept(string caption, string shown)
        {
            Assert.Equal(shown, ModalCaption.Display(caption));
        }

        [Theory]
        [InlineData("OK", "&OK", true)]
        [InlineData("ok", "OK", true)]
        [InlineData("Details...", "&Details...", true)]
        [InlineData("Login with online change", "Login with &online change", true)]
        [InlineData("Login with download", "Login with online change", false)]
        [InlineData("OK", "OK ", true)]
        public void MatchingIsExactButIgnoresCaseAndTheMnemonic(string named, string caption, bool same)
        {
            Assert.Equal(same, ModalCaption.Same(named, caption));
        }

        // ---- the fingerprint

        [Fact]
        public void TheSameDialogKeepsItsFingerprint()
        {
            Assert.Equal(ModalFingerprint.Of(Login()), ModalFingerprint.Of(Login()));
                }

        [Fact]
        public void TheFingerprintDoesNotDependOnWhatIsSelected()
        {
            var before = Login();
            var after = Login();
            after.Options[0].Checked = true;
            after.Options[2].Checked = false;

            // Which radio is selected is the answer, not the identity: --id must
            // still match after the user moved the selection.
            Assert.Equal(ModalFingerprint.Of(before), ModalFingerprint.Of(after));
        }

        [Fact]
        public void ADifferentQuestionIsADifferentFingerprint()
        {
            var other = Login();
            other.Text = "The application has unsaved changes. What do you want to do?";
            Assert.NotEqual(ModalFingerprint.Of(Login()), ModalFingerprint.Of(other));

            other = Login();
            other.Buttons = new[] { "&OK", "&Cancel" };
            Assert.NotEqual(ModalFingerprint.Of(Login()), ModalFingerprint.Of(other));
        }

        [Fact]
        public void TheFingerprintIsEightHexDigits()
        {
            var fingerprint = ModalFingerprint.Of(Login());
            Assert.Equal(8, fingerprint.Length);
            foreach (var c in fingerprint)
                Assert.True(Uri.IsHexDigit(c), "not hex: " + fingerprint);
        }

        // ---- the one line

        [Fact]
        public void TheSnapshotLineCarriesTheIdTheOptionsAndTheButtons()
        {
            Assert.Equal(
                "[id " + ModalFingerprint.Of(Login()) + "]: CODESYS - The application changed "
                + "since last download. What do you want to do? - options: "
                + "( ) Login with online change, ( ) Login with download, "
                + "(*) Login without any change, [ ] Update boot application - "
                + "buttons: [OK] [Cancel] [Details...]",
                Login().Snapshot());
        }

        [Fact]
        public void AnUnreadableStateIsShownAsAQuestionMark()
        {
            var window = Login();
            window.Options[1].Checked = null;
            Assert.Contains("(?) Login with download", window.Snapshot());
        }

        [Fact]
        public void AModalWithoutChildrenStillReads()
        {
            var window = new ModalWindow { Title = null, Text = null, Class = "#32770" };
            Assert.Contains("(untitled dialog)", window.Snapshot());
            Assert.DoesNotContain("options:", window.Snapshot());
            Assert.DoesNotContain("buttons:", window.Snapshot());
        }

        [Fact]
        public void TheBlockedLineLeadsWithTheId()
        {
            var line = ModalErrors.BlockLine(new[] { Login() });
            Assert.StartsWith("blocked by a dialog [id ", line);
            Assert.Contains("]: CODESYS - The application changed", line);
        }

        [Fact]
        public void TwoDialogsKeepTheirOwnParts()
        {
            var other = Login();
            other.Hwnd = 201;
            other.Title = "Second";
            var line = ModalErrors.BlockLine(new[] { Login(), other });

            Assert.StartsWith("blocked by a dialog: ", line);
            Assert.Contains("; [id ", line);
            Assert.Contains("Second", line);
        }

        [Fact]
        public void TheWireShapeCarriesTheOptionsAndTheFingerprint()
        {
            var data = Login().ToData();

            Assert.Equal(ModalFingerprint.Of(Login()), data["fingerprint"]);
            var options = Assert.IsType<List<object>>(data["options"]);
            Assert.Equal(4, options.Count);
            var first = Assert.IsType<Dictionary<string, object>>(options[0]);
            Assert.Equal("Login with &online change", first["caption"]);
            Assert.Equal("radio", first["kind"]);
            Assert.Equal(false, first["checked"]);
            Assert.Equal(new[] { "&OK", "&Cancel", "&Details..." }, Assert.IsType<string[]>(data["buttons"]));
        }

        [Fact]
        public void AnUnreadableCheckedStateIsNullOnTheWire()
        {
            var option = new ModalOption("Maybe", ModalOptionKind.Check, null);
            Assert.Null(option.ToData()["checked"]);
        }

        // ---- the request

        static Request Req(Dictionary<string, object> parameters)
        {
            return new Request(1, "dialog.answer", parameters);
        }

        [Fact]
        public void APressIsRequired()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogRequest.Parse(Req(new Dictionary<string, object>())));
            Assert.Equal(ErrorCodes.BadParams, ex.Code);
            Assert.Contains("'press' is required", ex.Message);
        }

        [Fact]
        public void TheRequestTakesOptionsButtonsAndAnId()
        {
            var request = DialogRequest.Parse(Req(new Dictionary<string, object>
            {
                { "press", " OK " },
                { "choose", new List<object> { "Login with download" } },
                { "uncheck", new List<object> { "Update boot application" } },
                { "id", " abcd1234 " },
            }));

            Assert.Equal("OK", request.Press);
            Assert.Equal(new[] { "Login with download" }, request.Choose);
            Assert.Equal(new[] { "Update boot application" }, request.Uncheck);
            Assert.Equal("abcd1234", request.Id);
        }

        [Fact]
        public void AWronglyTypedListIsRefusedNotCoerced()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogRequest.Parse(Req(new Dictionary<string, object>
            {
                { "press", "OK" },
                { "choose", "Login with download" },
            })));
            Assert.Equal(ErrorCodes.BadParams, ex.Code);
        }

        // ---- resolving names against a dialog

        static DialogRequest Ask(string id = null, string[] choose = null, string[] uncheck = null, string press = "OK")
        {
            return new DialogRequest { Id = id, Choose = choose ?? new string[0], Uncheck = uncheck ?? new string[0], Press = press };
        }

        [Fact]
        public void NamesMatchRegardlessOfCaseAndMnemonics()
        {
            var plan = DialogResolver.Resolve(Login(), Ask(
                choose: new[] { "login with ONLINE change" },
                press: "cancel"));

            Assert.Equal(new[] { "Login with &online change" }, plan.Choose);
            Assert.Equal("&Cancel", plan.Press);
        }

        [Fact]
        public void AnUnknownOptionIsRefusedWithTheDialogAsItIs()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(Login(), Ask(choose: new[] { "Login with online changes" })));

            Assert.Equal(ErrorCodes.BadParams, ex.Code);
            Assert.Contains("no option named 'Login with online changes'", ex.Message);
            Assert.Contains("Login with download", ex.Message);   // what it could have said
            Assert.NotNull(ex.Details);
        }

        [Fact]
        public void PressingSomethingThatIsAnOptionIsRefused()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(Login(), Ask(press: "Login with download")));
            Assert.Equal(ErrorCodes.BadParams, ex.Code);
            Assert.Contains("no button named 'Login with download'", ex.Message);
            Assert.Contains("[OK] [Cancel]", ex.Message);
        }

        [Fact]
        public void ClearingARadioIsRefusedRatherThanIgnored()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(Login(), Ask(uncheck: new[] { "Login with download" })));
            Assert.Equal(ErrorCodes.BadParams, ex.Code);
            Assert.Contains("is a radio button", ex.Message);
        }

        [Fact]
        public void AStaleIdIsRefusedAndBothIdsAreNamed()
        {
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(Login(), Ask(id: "deadbeef")));

            Assert.Equal(ErrorCodes.DialogChanged, ex.Code);
            Assert.Contains("deadbeef", ex.Message);
            Assert.Contains(ModalFingerprint.Of(Login()), ex.Message);
        }

        [Fact]
        public void TheMatchingIdIsAccepted()
        {
            var plan = DialogResolver.Resolve(Login(), Ask(id: ModalFingerprint.Of(Login())));
            Assert.Equal("&OK", plan.Press);
        }

        [Fact]
        public void AnAmbiguousCaptionIsRefused()
        {
            var window = Login();
            window.Buttons = new[] { "OK", "&OK" };
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(window, Ask()));
            Assert.Equal(ErrorCodes.BadParams, ex.Code);
            Assert.Contains("two buttons are named 'OK'", ex.Message);
        }

        [Fact]
        public void ADialogWithNoReadableOptionsSaysSo()
        {
            var window = Login();
            window.Options = new ModalOption[0];
            var ex = Assert.Throws<ProtocolException>(() => DialogResolver.Resolve(window, Ask(choose: new[] { "Login with download" })));
            Assert.Contains("none that could be read", ex.Message);
        }
    }
}
