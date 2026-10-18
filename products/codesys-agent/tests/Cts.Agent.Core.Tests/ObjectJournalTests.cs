using System;
using System.Collections.Generic;
using System.Linq;
using Xunit;

namespace Cts.Agent.Tests
{
    public class ObjectJournalTests
    {
        static readonly Guid A = new Guid("a04dd5ed-83d2-4ac4-b199-490b72709fb1");
        static readonly Guid B = new Guid("4dcc59a1-8384-4688-9a7e-0cda26f41fc0");
        static readonly Guid C = new Guid("7c1e8a52-3f0d-4b6e-9a21-5d4c3b2a1f00");

        [Fact]
        public void Ide_stamp_counts_owned_and_external_events_and_survives_take()
        {
            var journal = new ObjectJournal();
            var initial = journal.Stamp;
            journal.EventSeen();
            var own = journal.Own();
            journal.EventSeen();
            journal.Record(A, "modified", null);
            own.Dispose();
            Assert.EndsWith(":2", journal.Stamp);
            journal.Take();
            Assert.Equal(2, int.Parse(journal.Stamp.Split(':')[1]));
            journal.EventSeen(true);
            Assert.NotEqual(initial.Split(':')[0], journal.Stamp.Split(':')[0]);
            Assert.EndsWith(":0", journal.Stamp);
        }

        [Fact]
        public void Events_for_one_object_are_one_change_with_each_kind_once()
        {
            var journal = new ObjectJournal();
            journal.Record(A, "modified", null);
            journal.Record(B, "renamed", "F_New");
            journal.Record(A, "modified", null);
            journal.Record(A, "renamed", "M_Toggle2");

            var taken = journal.Take();

            Assert.Equal(new[] { A, B }, new[] { taken[0].Guid, taken[1].Guid });
            Assert.Equal(new[] { "modified", "renamed" }, taken[0].Kinds);
            Assert.Equal("M_Toggle2", taken[0].Name);
            Assert.Equal(0, journal.Count);
            Assert.Empty(journal.Take());
        }

        [Fact]
        public void Events_while_cts_writes_are_not_recorded()
        {
            var journal = new ObjectJournal();
            var own = journal.Own();
            journal.Record(A, "modified", null);
            own.Dispose();
            own.Dispose();
            journal.Record(B, "modified", null);

            Assert.Equal(B, Assert.Single(journal.Take()).Guid);
        }

        [Fact]
        public void Only_the_project_writes_count_as_cts_writes()
        {
            Assert.True(ObjectJournal.IsWrite("objects.settext"));
            Assert.True(ObjectJournal.IsWrite("objects.replace"));
            Assert.True(ObjectJournal.IsWrite("objects.import"));
            Assert.False(ObjectJournal.IsWrite("objects.texts"));
            Assert.False(ObjectJournal.IsWrite("project.export"));
        }

        [Fact]
        public void An_empty_guid_is_ignored()
        {
            var journal = new ObjectJournal();
            journal.Record(Guid.Empty, "modified", null);
            Assert.Equal(0, journal.Count);
        }

        [Fact]
        public void Only_the_first_event_of_an_object_asks_for_its_text()
        {
            var journal = new ObjectJournal();
            Assert.True(journal.IsNew(A));
            journal.Record(A, "modified", null, "before");
            Assert.False(journal.IsNew(A));
            journal.Record(A, "modified", null, "later");
            Assert.Equal("before", Assert.Single(journal.Take()).Before);
            using (journal.Own()) Assert.False(journal.IsNew(B));
        }

        [Fact]
        public void A_modified_object_whose_text_is_back_is_dropped()
        {
            var journal = new ObjectJournal();
            journal.Record(A, "modified", "a", "same");
            journal.Record(B, "modified", "b", "old");
            journal.Record(C, "modified", "c", null);
            var now = new Dictionary<Guid, string> { { A, "same" }, { B, "new" }, { C, "any" } };

            var changed = ObjectJournal.Changed(journal.Take(), now);

            Assert.Equal(new[] { B, C }, changed.Select(c => c.Guid));
        }

        [Fact]
        public void A_renamed_or_unreadable_object_stays()
        {
            var journal = new ObjectJournal();
            journal.Record(A, "modified", "a", "same");
            journal.Record(A, "renamed", "a2");
            journal.Record(B, "modified", "b", "text");
            var now = new Dictionary<Guid, string> { { A, "same" } };

            Assert.Equal(new[] { A, B }, ObjectJournal.Changed(journal.Take(), now).Select(c => c.Guid));
        }

    }
}
