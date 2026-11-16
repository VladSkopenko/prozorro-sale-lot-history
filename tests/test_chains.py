from lot_history.chains import assign_lots, backfill_previous, lot_keys
from lot_history.collector import collect
from tests.conftest import FakeSource

# ланцюжок фікстури закінчується тут: найстаріший аукціон посилається на цей, якого у фікстурі немає
BEFORE_THE_FIXTURE = "SPE001-UA-20260522-28555"


def test_earlier_auctions_are_fetched_until_the_chain_ends(chain, store, settings, connect):
    source = FakeSource(chain)
    # стрічка за останні дні віддала лише найновіший аукціон лота
    collect(connect(FakeSource(chain[:1])), store, settings, since="2026-11-01T00:00:00")

    fetched, unresolved = backfill_previous(connect(source), store, settings)

    assert (fetched, unresolved) == (len(chain) - 1, 1)
    assert store.counts()["attempts"] == len(chain)
    assert source.lookups()[-1] == BEFORE_THE_FIXTURE
    assert store.missing_previous() == []


def test_an_auction_the_source_does_not_know_is_asked_for_only_once(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since="2026-06-01T00:00:00")
    backfill_previous(connect(source), store, settings)
    asked = len(source.lookups())

    assert backfill_previous(connect(source), store, settings) == (0, 0)
    assert len(source.lookups()) == asked


def test_a_run_stops_at_its_lookup_limit_and_the_next_one_goes_on(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(FakeSource(chain[:1])), store, settings, since="2026-11-01T00:00:00")

    assert backfill_previous(connect(source), store, settings, max_fetches=4) == (4, 0)
    assert len(store.missing_previous()) == 1

    backfill_previous(connect(source), store, settings)
    assert store.counts()["attempts"] == len(chain)


def test_all_attempts_of_a_chain_become_one_lot(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since="2026-06-01T00:00:00")
    backfill_previous(connect(source), store, settings)

    assert assign_lots(store) == 1
    assert {row["lot_key"] for row in store.attempts()} == {BEFORE_THE_FIXTURE}


def test_unrelated_auctions_are_separate_lots(feed_page, store, settings, connect):
    collect(connect(FakeSource(feed_page)), store, settings, since="2026-06-01T00:00:00")

    lots = assign_lots(store)

    assert lots == store.counts()["attempts"]


def test_the_lot_key_is_the_earliest_auction_the_chain_reaches():
    links = {"C": "B", "B": "A", "A": None, "X": None, "Z": "Y"}

    assert lot_keys(links) == {"A": "A", "B": "A", "C": "A", "X": "X", "Z": "Y"}


def test_two_auctions_that_name_the_same_previous_one_are_one_lot():
    assert lot_keys({"B1": "A", "B2": "A", "A": None}) == {"A": "A", "B1": "A", "B2": "A"}


def test_a_loop_in_the_links_ends_instead_of_running_for_ever():
    keys = lot_keys({"A": "B", "B": "A"})

    assert keys["A"] == keys["B"]
