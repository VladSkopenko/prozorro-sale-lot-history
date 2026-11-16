from lot_history.collector import collect
from lot_history.verify import verify
from tests.conftest import FakeSource

AUCTION = "SPE001-UA-20261115-55411"


def test_an_attempt_that_did_not_change_matches_its_source(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since="2026-06-01T00:00:00")

    result = verify(connect(source), store, settings, AUCTION)

    assert result.matches
    assert result.source_page_url == f"https://prozorro.sale/auction/{AUCTION}/"


def test_every_field_that_changed_at_the_source_is_listed(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since="2026-06-01T00:00:00")
    live = source.procedures[0]
    live["status"] = "unsuccessful"
    live["value"]["amount"] = 3162881.0
    live["dateModified"] = "2026-12-04T18:00:00.000000Z"

    result = verify(connect(source), store, settings, AUCTION)

    assert not result.matches
    assert {(d.field, d.stored, d.source) for d in result.differences} == {
        ("status", "active_tendering", "unsuccessful"),
        ("outcome", "active", "unsuccessful"),
        ("value_amount", "6325762.0", "3162881.0"),
    }
    assert result.source_modified > result.stored_modified


def test_an_auction_that_was_never_collected_is_reported_as_such(chain, store, settings, connect):
    result = verify(connect(FakeSource(chain)), store, settings, AUCTION)

    assert (result.found_in_store, result.found_at_source, result.matches) == (False, True, False)


def test_an_auction_the_source_dropped_is_reported_as_such(chain, store, settings, connect):
    collect(connect(FakeSource(chain)), store, settings, since="2026-06-01T00:00:00")

    result = verify(connect(FakeSource([])), store, settings, AUCTION)

    assert (result.found_in_store, result.found_at_source, result.matches) == (True, False, False)
