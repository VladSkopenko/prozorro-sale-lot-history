import copy
from dataclasses import replace

import pytest

from lot_history.collector import FEED_CURSOR, collect
from tests.conftest import FakeSource

SINCE = "2026-06-01T00:00:00"


def test_the_first_run_stores_every_attempt_and_the_cursor(chain, store, settings, connect):
    stats = collect(connect(FakeSource(chain)), store, settings, since=SINCE)

    assert stats.new_attempts == len(chain) == store.counts()["attempts"]
    assert store.cursor(FEED_CURSOR) == max(procedure["dateModified"] for procedure in chain)


def test_pages_overlap_on_their_bound_and_nothing_is_stored_twice(chain, store, settings, connect):
    # 12 процедур сторінками по 5: кожна наступна сторінка починається з останнього запису попередньої
    stats = collect(connect(FakeSource(chain)), store, settings, since=SINCE)

    assert stats.pages == 3
    assert stats.seen == len(chain) + 2
    assert stats.duplicate_versions == 2
    assert store.counts()["versions"] == len(chain)


def test_a_second_run_with_nothing_new_changes_nothing(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since=SINCE)
    before = store.counts()

    stats = collect(connect(source), store, settings)

    # запуск продовжує зі збереженого курсора і зустрічає лише запис на цій межі
    assert (stats.seen, stats.duplicate_versions, stats.new_attempts, stats.changed_attempts) == (1, 1, 0, 0)
    assert store.counts() == before


def test_an_interrupted_run_resumes_from_the_last_finished_page(chain, store, settings, connect):
    source = FakeSource(chain)

    first = collect(connect(source), store, settings, since=SINCE, max_pages=1)
    second = collect(connect(source), store, settings)

    assert first.new_attempts == 5
    assert second.new_attempts == len(chain) - 5
    assert store.counts()["attempts"] == len(chain)


def test_a_status_change_updates_the_attempt_and_extends_its_history(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since=SINCE)
    running = source.procedures[0]
    running["status"] = "unsuccessful"
    running["dateModified"] = "2026-12-04T18:00:00.000000Z"

    stats = collect(connect(source), store, settings)

    assert stats.changed_attempts == 1
    stored = store.attempt(running["auctionId"])
    assert (stored["status"], stored["outcome"]) == ("unsuccessful", "unsuccessful")
    assert [row["status"] for row in store.status_history(running["_id"])] == [
        "active_tendering",
        "unsuccessful",
    ]
    assert store.counts()["versions"] == len(chain) + 1


def test_a_change_the_review_does_not_look_at_is_a_version_but_not_a_change(chain, store, settings, connect):
    source = FakeSource(chain)
    collect(connect(source), store, settings, since=SINCE)
    touched = source.procedures[0]
    touched["documents"] = [{"title": "a new scan"}]
    touched["dateModified"] = "2026-11-16T09:00:00.000000Z"

    stats = collect(connect(source), store, settings)

    assert (stats.changed_attempts, stats.unchanged_attempts) == (0, 1)
    assert len(store.status_history(touched["_id"])) == 1
    assert store.attempt(touched["auctionId"])["date_modified"].startswith("2026-11-16T09:00:00")


def test_an_older_version_never_rolls_a_newer_state_back(chain, store, settings, connect):
    newer = copy.deepcopy(chain[0])
    newer["status"] = "complete"
    newer["dateModified"] = "2026-12-20T10:00:00.000000Z"
    collect(connect(FakeSource([newer])), store, settings, since=SINCE)

    collect(connect(FakeSource([chain[0]])), store, settings, since=SINCE)

    assert store.attempt(chain[0]["auctionId"])["status"] == "complete"


def test_only_real_estate_and_land_are_kept_unless_asked_otherwise(feed_page, store, settings, connect):
    vehicles = [p for p in feed_page if p["items"][0]["classification"]["id"].startswith("34")]
    assert vehicles, "у фікстурі має бути лот з автомобілем"

    # одна сторінка на всю фікстуру, тож жоден запис не зустрічається двічі на межі сторінок
    settings = replace(settings, page_size=50)
    stats = collect(connect(FakeSource(feed_page)), store, settings, since=SINCE)

    assert stats.skipped_kind == len(vehicles)
    assert store.counts()["attempts"] == len(feed_page) - len(vehicles)
    assert store.attempt(vehicles[0]["auctionId"]) is None

    collect(connect(FakeSource(feed_page)), store, settings, since=SINCE, kinds=None)
    assert store.counts()["attempts"] == len(feed_page)


def test_a_page_of_records_with_one_stamp_is_widened_not_repeated(chain, store, settings, connect):
    same_moment = copy.deepcopy(chain[:8])
    for procedure in same_moment:
        procedure["dateModified"] = "2026-11-15T07:24:11.554000Z"

    stats = collect(connect(FakeSource(same_moment)), store, settings, since="2026-11-15T07:24:11.554000Z")

    assert store.counts()["attempts"] == 8
    assert stats.pages == 1


def test_a_malformed_record_is_reported_and_the_rest_is_stored(chain, store, settings, connect):
    broken = {"_id": "broken", "dateModified": "2026-06-10T00:00:00.000000Z", "status": "complete"}

    stats = collect(connect(FakeSource([broken, *chain[:3]])), store, settings, since=SINCE)

    assert store.counts()["attempts"] == 3
    assert len(stats.invalid) == 1
    assert stats.invalid[0].startswith("broken: KeyError")


def test_the_first_run_needs_a_starting_point(chain, store, settings, connect):
    with pytest.raises(ValueError, match="вкажіть `since`"):
        collect(connect(FakeSource(chain)), store, settings)
