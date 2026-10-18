namespace Cts.Agent
{
    // When the agent runs `cts compare` by itself to bring the IDE's mirror
    // (compare's cache of the IDE's view, refs/cts/ide) up to date: once per
    // state of the project's objects (the journal's stamp), and only while
    // nobody works -- no input and no cts command for a while, no dialog up,
    // no quick window run going.  Rendering the changed objects holds the
    // IDE's UI thread, the whole project for seconds after a new cts build;
    // done here, the person's next compare (the quick window's header, an AI
    // agent's command) finds it done.
    public sealed class IdleRefresh
    {
        public const long QuietMs = 15000;

        //: The stamp of the last refresh started (or found nothing to refresh).
        string _done;

        public bool Due(string stamp, long inputIdleMs, long commandsQuietMs, bool busy)
        {
            return stamp != _done && inputIdleMs >= QuietMs && commandsQuietMs >= QuietMs && !busy;
        }

        // The state *stamp* is handled: refreshed, or not a project to refresh.
        public void Done(string stamp)
        {
            _done = stamp;
        }
    }
}
