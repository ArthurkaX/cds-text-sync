using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using Xunit;

namespace Cts.Agent.Tests
{
    // The modal-detection core: the policy truth table (t55 Part 1 §1.4), the
    // snapshot diff, the UiCall epoch guard and the frozen error wording.
    public class ModalTests
    {
        // A modal-by-default dialog: an ownerless #32770 (the shape a native
        // MessageBox with no parent has).  A test that wants a non-modal window
        // gives it an owner (see AnOwnedEnabledDialogClassIsNotModal...).
        static ModalWindow Dialog(long hwnd = 100, string title = "Save changes?")
        {
            return new ModalWindow
            {
                Hwnd = hwnd,
                Class = ModalPolicy.DialogClass,
                Title = title,
                Text = "The project was modified.\nSave it now?",
                Buttons = new[] { "Yes", "No", "Cancel" },
                Owner = 0,
                Ownerless = true,
                OwnerDisabled = false,
                Enabled = true,
                Visible = true,
            };
        }

        // ---- ModalPolicy

        [Fact]
        public void AnInvisibleWindowIsNeverModal()
        {
            var w = Dialog();
            w.Visible = false;
            Assert.False(ModalPolicy.IsModal(w));
        }

        [Fact]
        public void AnOwnerlessDialogClassIsModal()
        {
            Assert.True(ModalPolicy.IsModal(Dialog()));
        }

        [Fact]
        public void ADisabledDialogClassIsModal()
        {
            var w = Dialog();
            w.Enabled = false;
            w.Ownerless = false;
            w.Owner = 42;
            Assert.True(ModalPolicy.IsModal(w));
        }

        [Fact]
        public void AnOwnedEnabledDialogClassIsNotModalItIsAModelessToolWindow()
        {
            var w = Dialog();
            w.Owner = 42;
            w.Ownerless = false;
            Assert.False(ModalPolicy.IsModal(w));
        }

        [Fact]
        public void ADisabledOwnerMakesAnyVisibleWindowModal()
        {
            var w = Dialog();
            w.Class = "SomeVendorWindow";
            w.Ownerless = false;
            w.Owner = 42;
            w.OwnerDisabled = true;
            Assert.True(ModalPolicy.IsModal(w));
        }

        [Fact]
        public void AnOrdinaryVisibleOwnedWindowIsNotModal()
        {
            var w = Dialog();
            w.Class = "SomeVendorWindow";
            w.Ownerless = false;
            w.Owner = 42;
            Assert.False(ModalPolicy.IsModal(w));
        }

        [Fact]
        public void NullIsNotModal()
        {
            Assert.False(ModalPolicy.IsModal(null));
        }

        // CODESYS's own message boxes are WinForms windows that disable their
        // owner (live, 2026-10-08: the Clean All login prompt "An application
        // ... is currently in RUN mode on the PLC").
        [Fact]
        public void AWinFormsWindowThatDisabledItsOwnerHasReadableChildren()
        {
            var w = Dialog();
            w.Class = "WindowsForms10.Window.8.app.0.13965fa_r7_ad1";
            w.Ownerless = false;
            w.Owner = 42;
            w.OwnerDisabled = true;
            Assert.True(ModalPolicy.HasReadableChildren(w));
        }

        [Fact]
        public void AnOwnerlessMainFrameIsNotWalked()
        {
            var w = Dialog();
            w.Class = "WindowsForms10.Window.8.app.0.13965fa_r7_ad1";
            Assert.False(ModalPolicy.HasReadableChildren(w));
            Assert.True(ModalPolicy.HasReadableChildren(Dialog()));
            Assert.False(ModalPolicy.HasReadableChildren(null));
        }

        [Theory]
        [InlineData("Button", ChildRole.Button)]
        [InlineData("Static", ChildRole.Text)]
        [InlineData("WindowsForms10.BUTTON.app.0.13965fa_r7_ad1", ChildRole.Button)]
        [InlineData("WindowsForms10.EDIT.app.0.13965fa_r7_ad1", ChildRole.Text)]
        [InlineData("WindowsForms10.STATIC.app.0.13965fa_r7_ad1", ChildRole.Text)]
        [InlineData("WindowsForms10.Window.8.app.0.13965fa_r7_ad1", ChildRole.Other)]
        [InlineData("Edit", ChildRole.Other)]
        [InlineData("", ChildRole.Other)]
        [InlineData(null, ChildRole.Other)]
        public void ChildControlsAreClassifiedByClass(string className, ChildRole role)
        {
            Assert.Equal(role, ModalPolicy.RoleOf(className));
        }

        // ---- ModalState

        // A dialog that opened after the epoch is named, closed again or not.
        [Fact]
        public void OpenedSinceNamesTheDialogsThatCameEvenWhenTheyWent()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog(1, "Before") });
            var epoch = state.Epoch;
            state.Update(new[] { Dialog(1, "Before"), Dialog(2, "Thread was being aborted") });
            state.Update(new ModalWindow[0]);
            state.Update(new[] { Dialog(3, "Save changes?") });
            Assert.Equal(new[] { "Thread was being aborted", "Save changes?" }, state.OpenedSince(epoch).Select(window => window.Title));
            Assert.Empty(state.OpenedSince(state.Epoch));
        }

        [Fact]
        public void AnOpenedDialogGetsAnIdRaisesOpenedAndBumpsTheEpoch()
        {
            var state = new ModalState();
            var opened = new List<ModalWindow>();
            state.Opened += opened.Add;

            Assert.Equal(0L, state.Epoch);
            var diff = state.Update(new[] { Dialog() });

            Assert.True(diff.Changed);
            Assert.Single(diff.Opened);
            Assert.Empty(diff.Closed);
            Assert.Equal(1L, diff.Opened[0].Id);
            Assert.Equal(1L, state.Epoch);
            Assert.True(state.AnyOpen);
            Assert.Single(opened);
            Assert.Single(state.Current);
        }

        [Fact]
        public void AStillOpenDialogKeepsItsIdAndDoesNotBumpTheEpoch()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog() });
            var epoch = state.Epoch;

            // The same window, now saying something else (a progress dialog).
            var again = Dialog();
            again.Text = "Still saving...";
            var diff = state.Update(new[] { again });

            Assert.False(diff.Changed);
            Assert.Equal(epoch, state.Epoch);
            Assert.Equal(1L, state.Current[0].Id);
            Assert.Equal("Still saving...", state.Current[0].Text);
        }

        [Fact]
        public void AClosedDialogBumpsTheEpochAndRaisesClosed()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog() });
            var closed = new List<ModalWindow>();
            state.Closed += closed.Add;

            var diff = state.Update(new ModalWindow[0]);

            Assert.True(diff.Changed);
            Assert.Single(diff.Closed);
            Assert.Equal(1L, diff.Closed[0].Id);
            Assert.Equal(2L, state.Epoch);
            Assert.False(state.AnyOpen);
            Assert.Single(closed);
            Assert.Empty(state.Current);
        }

        [Fact]
        public void OnlyModalWindowsAreTracked()
        {
            var state = new ModalState();
            var toolWindow = Dialog(hwnd: 200);
            toolWindow.Owner = 42;              // owned + enabled => modeless
            toolWindow.Ownerless = false;
            var hidden = Dialog(hwnd: 300);
            hidden.Visible = false;

            state.Update(new[] { Dialog(hwnd: 100), toolWindow, hidden });

            Assert.Single(state.Current);
            Assert.Equal(100L, state.Current[0].Hwnd);
        }

        [Fact]
        public void TwoUpdatesThatOpenAndCloseStillChangedTheEpoch()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog() });
            state.Update(new ModalWindow[0]);

            // The UiCall guard relies on this: a dialog that came and went while
            // a call was queued must still be visible as an epoch change, even
            // though no dialog is open now.
            Assert.Equal(2L, state.Epoch);
            Assert.False(state.AnyOpen);
        }

        [Fact]
        public void SeveralDialogsGetDistinctIdsAndTheNewestComesFirst()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog(hwnd: 1) });
            state.Update(new[] { Dialog(hwnd: 1), Dialog(hwnd: 2) });

            // A message box stacked on a dialog takes the input: it is the one
            // `cts dialog` names and the Next line answers.
            Assert.Equal(new[] { 2L, 1L }, new[] { state.Current[0].Id, state.Current[1].Id });
            Assert.Equal(new[] { 2L, 1L }, new[] { state.Current[0].Hwnd, state.Current[1].Hwnd });
        }

        // ---- the refusal

        [Fact]
        public void BlockedCarriesTheSnapshotInTheMessageAndTheWindowsInDetails()
        {
            var ex = ModalErrors.Blocked(new[] { Dialog(title: "Download") });

            Assert.Equal(ErrorCodes.DialogBlocked, ex.Code);
            Assert.Contains("Download", ex.Message);
            Assert.Contains("Yes", ex.Message);
            var data = Assert.IsType<Dictionary<string, object>>(ex.Details);
            var dialogs = Assert.IsType<List<object>>(data["dialogs"]);
            var first = Assert.IsType<Dictionary<string, object>>(dialogs[0]);
            Assert.Equal(100L, first["hwnd"]);
            Assert.Equal(new[] { "Yes", "No", "Cancel" }, Assert.IsType<string[]>(first["buttons"]));
        }

        [Fact]
        public void TheRefusalSurvivesTheWireEnvelope()
        {
            var reply = Replies.Fail(7, ErrorCodes.DialogBlocked, "blocked",
                new Dictionary<string, object> { { "dialogs", new List<object>() } });
            var parsed = (IDictionary<string, object>)Json.Parse(reply);
            var error = (IDictionary<string, object>)parsed["error"];

            Assert.Equal("dialog_blocked", error["code"]);
            Assert.True(error.ContainsKey("data"));
        }

        // ---- the method allowlist

        [Theory]
        [InlineData("ping", true)]
        [InlineData("hello", true)]
        [InlineData("state", true)]
        [InlineData("dialog.probe", true)]
        [InlineData("dialog.answer", true)]
        [InlineData("project.status", true)]
        [InlineData("subscribe", true)]
        [InlineData("vars.read", false)]
        [InlineData("vars.write", false)]
        [InlineData("dev.reflect", false)]
        public void OnlyTheUiFreeMethodsAnswerWhileAModalIsOpen(string method, bool answers)
        {
            Assert.Equal(answers, ModalGate.AnswersWhileModal(method));
        }

        [Fact]
        public void ASecondUiRequestIsBusyButAlwaysAllowedRequestsPass()
        {
            var blocked = ModalGate.CheckBusy("app.build", new[] { "app.build", "app.build" });
            Assert.NotNull(blocked);
            Assert.Equal(ErrorCodes.Busy, blocked.Code);
            Assert.Contains("app.build", blocked.Message);
            Assert.Null(ModalGate.CheckBusy("dialog.probe", new[] { "app.build", "dialog.probe" }));
            Assert.Null(ModalGate.CheckBusy("app.build", new[] { "app.build" }));
            // A widget.drive waits for the cts runs the window starts: they must get through.
            Assert.Null(ModalGate.CheckBusy("project.export", new[] { "widget.drive", "project.export" }));
            // test.run's and test.app's steps are agent calls of their own.
            Assert.Null(ModalGate.CheckBusy("app.login", new[] { "test.run", "app.login" }));
            Assert.Null(ModalGate.CheckBusy("app.download", new[] { "test.app", "app.download" }));
        }

        // ---- the gate's confirm step (t60)

        [Fact]
        public void AStaleOpenSnapshotIsConfirmedAndTheBlockedRequestProceeds()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog() });     // what the last poll saw
            var closed = new List<ModalWindow>();
            state.Closed += closed.Add;
            var probe = new FakeProbe(state);     // the fresh look finds nothing

            Assert.Null(ModalGate.Check("vars.read", state, probe));

            Assert.Equal(1, probe.Calls);
            Assert.False(state.AnyOpen);
            Assert.Single(closed);                // the closed dialog was announced
        }

        [Fact]
        public void AConfirmedOpenSnapshotIsRefusedWithTheLiveDialog()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog(title: "Save changes?") });
            var probe = new FakeProbe(state, Dialog(title: "Saving the project"));

            var blocked = ModalGate.Check("vars.write", state, probe);

            Assert.NotNull(blocked);
            Assert.Equal(ErrorCodes.DialogBlocked, blocked.Code);
            Assert.Contains("Saving the project", blocked.Message);   // fresh, not cached
        }

        [Fact]
        public void TheSnapshotIsNotConfirmedWhenNoDialogIsCached()
        {
            var state = new ModalState();
            var probe = new FakeProbe(state);

            Assert.Null(ModalGate.Check("vars.read", state, probe));

            Assert.Equal(0, probe.Calls);   // a normal call pays nothing extra
        }

        [Fact]
        public void AnAlwaysAnsweredMethodIsNotConfirmedWhileADialogIsOpen()
        {
            var state = new ModalState();
            state.Update(new[] { Dialog() });
            var probe = new FakeProbe(state);

            Assert.Null(ModalGate.Check("ping", state, probe));

            Assert.Equal(0, probe.Calls);
        }

        // ---- UiCall: the modal epoch guard

        [Fact]
        public void ADialogThatOpensWhileACallIsQueuedRefusesItInsteadOfRunningNested()
        {
            using (var ui = new FakeUi())
            {
                var release = new ManualResetEventSlim();
                ui.Post(() => release.Wait());   // hold the UI thread
                var modal = new ModalState();
                var ran = false;

                var thrown = Watch(() => UiCall.Run(ui.Post,
                    () => { ran = true; return 1; }, 5000, "vars.write", modal, 5000));
                // The call is queued; a dialog appears before the UI thread starts it.
                modal.Update(new[] { Dialog() });
                release.Set();

                var ex = Assert.Throws<ProtocolException>(() => thrown());
                Assert.Equal(ErrorCodes.DialogBlocked, ex.Code);
                Assert.False(ran, "a blocked call must not run inside the modal loop");
            }
        }

        [Fact]
        public void ADialogThatOpenedAndClosedWhileQueuedStillRefusesTheCall()
        {
            var modal = new ModalState();
            var ran = false;
            Action queuedAction = null;
            var queued = new ManualResetEventSlim();
            var finished = new ManualResetEventSlim();
            Exception failure = null;

            // A `post` that only captures the action: this is exactly "the call
            // is queued and the UI thread has not started it yet".
            var caller = new Thread(() =>
            {
                try
                {
                    // Even a confirm that finds nothing open now must not rescue a
                    // call whose world changed while it waited: the dialog came AND
                    // went, so the call was queued in a different world (t55 §2.1).
                    UiCall.Run<object>(action => { queuedAction = action; queued.Set(); },
                        () => { ran = true; return 1; }, 5000, "vars.write", modal, 5000,
                        new FakeProbe(modal));
                }
                catch (Exception e) { failure = e; }
                finally { finished.Set(); }
            });
            caller.IsBackground = true;
            caller.Start();

            Assert.True(queued.Wait(5000), "the call was never queued");
            modal.Update(new[] { Dialog() });
            modal.Update(new ModalWindow[0]);   // answered before we start
            queuedAction();                     // the UI thread finally reaches it
            Assert.True(finished.Wait(5000));

            var ex = Assert.IsType<ProtocolException>(failure);
            Assert.Equal(ErrorCodes.DialogBlocked, ex.Code);
            Assert.False(ran);
            // Gone by the time anyone looks: the refusal itself says which dialog it was.
            Assert.StartsWith("a dialog opened and closed while the command waited: ", ex.Message);
            Assert.Contains("Save changes?", ex.Message);
            Assert.Single((System.Collections.IEnumerable)((IDictionary<string, object>)ex.Details)["gone"]);
        }

        [Fact]
        public void AStaleOpenSnapshotIsConfirmedAndTheCallRuns()
        {
            var modal = new ModalState();
            modal.Update(new[] { Dialog() });   // the cached snapshot says open
            var probe = new FakeProbe(modal);   // the fresh look finds it gone
            var ran = false;

            var value = UiCall.Run<object>(a => a(), () => { ran = true; return 1; },
                2000, "vars.read", modal, 5000, probe);

            Assert.True(ran);
            Assert.Equal(1, value);
            Assert.Equal(1, probe.Calls);
            Assert.False(modal.AnyOpen);
        }

        [Fact]
        public void ADialogThatOpensWhileACallIsQueuedIsRefusedWithTheFreshSnapshot()
        {
            using (var ui = new FakeUi())
            {
                var release = new ManualResetEventSlim();
                ui.Post(() => release.Wait());   // hold the UI thread
                var modal = new ModalState();
                var probe = new FakeProbe(modal, Dialog(title: "Downloading"));
                var ran = false;

                var thrown = Watch(() => UiCall.Run(ui.Post,
                    () => { ran = true; return 1; }, 5000, "vars.write", modal, 5000, probe));
                // The call is queued; a dialog appears before the UI thread starts it.
                modal.Update(new[] { Dialog(title: "Something else") });
                release.Set();

                var ex = Assert.Throws<ProtocolException>(() => thrown());
                Assert.Equal(ErrorCodes.DialogBlocked, ex.Code);
                // The fresh poll, not the cached snapshot, is what the client sees.
                Assert.Contains("Downloading", ex.Message);
                Assert.Equal(1, probe.Calls);
                Assert.False(ran, "a blocked call must not run inside the modal loop");
            }
        }

        [Fact]
        public void ACallWithNoDialogRunsNormally()
        {
            using (var ui = new FakeUi())
            {
                var modal = new ModalState();
                Assert.Equal(9, UiCall.Run(ui.Post, () => 9, 2000, "vars.read", modal, 5000));
            }
        }

        [Fact]
        public void ADialogThatOpensAfterTheCallStartedDoesNotAffectIt()
        {
            using (var ui = new FakeUi())
            {
                var modal = new ModalState();
                // The dialog appears after the call has already started: the
                // guard is a start-time check, it cannot un-run the action.
                var value = UiCall.Run(ui.Post, () => { modal.Update(new[] { Dialog() }); return 3; },
                    2000, "state", modal, 5000);
                Assert.Equal(3, value);
            }
        }

        // ---- UiCall: the frozen wording

        [Fact]
        public void NotStartingInTimeIsBusyAndSaysNothingRan()
        {
            using (var ui = new FakeUi())
            {
                var release = new ManualResetEventSlim();
                ui.Post(() => release.Wait());
                var ex = Assert.Throws<ProtocolException>(() =>
                    UiCall.Run(ui.Post, () => 1, 100, "write"));
                Assert.Equal(ErrorCodes.Busy, ex.Code);
                Assert.Contains("write", ex.Message);
                Assert.Contains(UiCall.NotStarted, ex.Message);
                Assert.DoesNotContain("cancelled", ex.Message);
                release.Set();
            }
        }

        [Fact]
        public void StartingButNotFinishingIsTimeoutAndTheOutcomeIsUnknown()
        {
            using (var ui = new FakeUi())
            {
                var ex = Assert.Throws<ProtocolException>(() =>
                    UiCall.Run(ui.Post, () => { Thread.Sleep(2000); return 1; }, 100, "download", null, 100));
                Assert.Equal(ErrorCodes.Timeout, ex.Code);
                Assert.Contains("download", ex.Message);
                Assert.Contains(UiCall.OutcomeUnknown, ex.Message);
                Assert.DoesNotContain("cancelled", ex.Message);
            }
        }

        // Runs `call` on another thread so the test can mutate state while it is
        // queued; the returned thunk rethrows what the call threw.
        static Func<object> Watch(Func<object> call)
        {
            Exception error = null;
            object value = null;
            var done = new ManualResetEventSlim();
            var thread = new Thread(() =>
            {
                try { value = call(); }
                catch (Exception e) { error = e; }
                finally { done.Set(); }
            });
            thread.IsBackground = true;
            thread.Start();
            return () =>
            {
                Assert.True(done.Wait(10000), "the call did not finish");
                if (error != null) throw error;
                return value;
            };
        }

        // A stand-in for the live confirm step: it performs the same ModalState
        // update the real Win32 poll does, then answers from it, so the tests
        // exercise "confirm reconciled the state" and not just a bool.
        sealed class FakeProbe : IModalProbe
        {
            readonly ModalState _state;
            readonly ModalWindow[] _sees;

            public int Calls;

            public FakeProbe(ModalState state, params ModalWindow[] sees)
            {
                _state = state;
                _sees = sees;
            }

            public bool ConfirmModal()
            {
                Calls++;
                _state.Update(_sees);
                return _state.AnyOpen;
            }
        }

        // A UI thread stand-in: runs posted actions one at a time on its own thread.
        sealed class FakeUi : IDisposable
        {
            readonly Queue<Action> _queue = new Queue<Action>();
            readonly object _lock = new object();
            readonly Thread _thread;
            bool _stop;

            public FakeUi()
            {
                _thread = new Thread(Loop) { IsBackground = true };
                _thread.Start();
            }

            public void Post(Action a)
            {
                lock (_lock) { _queue.Enqueue(a); Monitor.Pulse(_lock); }
            }

            void Loop()
            {
                while (true)
                {
                    Action next;
                    lock (_lock)
                    {
                        while (_queue.Count == 0 && !_stop) Monitor.Wait(_lock);
                        if (_stop) return;
                        next = _queue.Dequeue();
                    }
                    next();
                }
            }

            public void Dispose()
            {
                lock (_lock) { _stop = true; Monitor.Pulse(_lock); }
            }
        }
    }
}
