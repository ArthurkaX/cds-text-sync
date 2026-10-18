using System;
using System.Collections.Generic;
using System.Threading;
using Xunit;

namespace Cts.Agent.Tests
{
    public class UiCallTests
    {
        // A UI thread stand-in: runs posted actions one at a time on its own thread.
        sealed class FakeUi : IDisposable
        {
            readonly Queue<Action> _queue = new Queue<Action>();
            readonly object _lock = new object();
            readonly Thread _thread;
            bool _stop;

            public int ThreadId { get; private set; }

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
                ThreadId = Thread.CurrentThread.ManagedThreadId;
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

        [Fact]
        public void RunsOnTheUiThreadAndReturnsTheResult()
        {
            using (var ui = new FakeUi())
            {
                var id = UiCall.Run(ui.Post, () => Thread.CurrentThread.ManagedThreadId, 2000, "id");
                Assert.Equal(ui.ThreadId, id);
                Assert.NotEqual(Thread.CurrentThread.ManagedThreadId, id);
            }
        }

        [Fact]
        public void ABusyUiThreadGivesABusyErrorAndTheCallNeverRunsLate()
        {
            using (var ui = new FakeUi())
            {
                var release = new ManualResetEventSlim();
                ui.Post(() => release.Wait());   // the UI thread is stuck on something long
                var ran = false;
                var ex = Assert.Throws<ProtocolException>(() =>
                    UiCall.Run(ui.Post, () => { ran = true; return 1; }, 100, "write"));
                Assert.Equal(ErrorCodes.Busy, ex.Code);
                Assert.Contains("write", ex.Message);

                release.Set();
                // Let the UI thread drain: a following call goes through the same queue.
                Assert.Equal(5, UiCall.Run(ui.Post, () => 5, 2000, "after"));
                Assert.False(ran, "an abandoned call must not execute");
            }
        }

        [Fact]
        public void ACallAlreadyRunningIsAwaitedNotAbandoned()
        {
            using (var ui = new FakeUi())
            {
                var value = UiCall.Run(ui.Post, () => { Thread.Sleep(300); return 42; }, 50, "slow");
                Assert.Equal(42, value);
            }
        }

        [Fact]
        public void ProtocolExceptionKeepsItsCode()
        {
            using (var ui = new FakeUi())
            {
                var ex = Assert.Throws<ProtocolException>(() =>
                    UiCall.Run<int>(ui.Post, () => { throw new ProtocolException(ErrorCodes.Unavailable, "no project"); }, 2000, "x"));
                Assert.Equal(ErrorCodes.Unavailable, ex.Code);
                Assert.Equal("no project", ex.Message);
            }
        }

        [Fact]
        public void OtherFaultsAreWrappedWithTheOperationName()
        {
            using (var ui = new FakeUi())
            {
                var ex = Assert.Throws<InvalidOperationException>(() =>
                    UiCall.Run<int>(ui.Post, () => { throw new NullReferenceException("nope"); }, 2000, "read"));
                Assert.Contains("read", ex.Message);
                Assert.Contains("nope", ex.Message);
            }
        }
    }
}
