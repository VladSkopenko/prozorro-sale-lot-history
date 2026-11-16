import csv

import pytest

from lot_history.chains import assign_lots, backfill_previous
from lot_history.collector import collect
from lot_history.export import lot_summaries, write_csv
from tests.conftest import FakeSource


@pytest.fixture
def collected(chain, feed_page, store, settings, connect):
    source = FakeSource([*chain, *feed_page])
    collect(connect(source), store, settings, since="2026-06-01T00:00:00")
    backfill_previous(connect(source), store, settings)
    assign_lots(store)
    return store


def repeated_lot(store):
    (summary,) = lot_summaries(store, min_attempts=2)
    return summary


def test_a_lot_row_counts_every_attempt_and_how_it_ended(collected):
    summary = repeated_lot(collected)

    assert summary.attempts == 12
    assert summary.unsuccessful_attempts == 7
    assert summary.cancelled_attempts == 4
    assert (summary.latest_status, summary.latest_outcome) == ("active_tendering", "active")
    assert summary.latest_auction_id == "SPE001-UA-20261115-55411"


def test_a_lot_row_shows_where_the_price_started_and_where_it_is_now(collected):
    summary = repeated_lot(collected)

    assert (summary.first_value, summary.latest_value, summary.currency) == (3162881.0, 6325762.0, "UAH")
    assert (summary.first_published, summary.latest_modified) == ("2026-06-15", "2026-11-15")


def test_the_history_lists_every_auction_with_a_link_to_its_page(collected):
    lines = repeated_lot(collected).history.splitlines()

    assert len(lines) == 12
    assert lines[0].startswith("1. 2026-06-15 SPE001-UA-20260615-97929 unsuccessful | 3,162,881.00 UAH")
    assert lines[0].endswith("https://prozorro.sale/auction/SPE001-UA-20260615-97929/")
    assert lines[-1].startswith("12. 2026-11-15 SPE001-UA-20261115-55411 active_tendering")


def test_rows_can_be_narrowed_to_a_property_kind(collected):
    kinds = {summary.property_kind for summary in lot_summaries(collected)}
    assert kinds == {"real_estate", "land"}

    assert {summary.property_kind for summary in lot_summaries(collected, kinds=["land"])} == {"land"}


def test_attempts_without_a_lot_are_left_out_until_the_chain_step_ran(chain, store, settings, connect):
    collect(connect(FakeSource(chain)), store, settings, since="2026-06-01T00:00:00")

    assert lot_summaries(store) == []


def test_the_csv_has_one_row_per_lot_under_a_header(collected, tmp_path):
    summaries = lot_summaries(collected)
    path = tmp_path / "out" / "lots.csv"

    write_csv(summaries, path)

    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(summaries)
    assert {"lot_key", "attempts", "source_page_url", "history"} <= set(rows[0])
