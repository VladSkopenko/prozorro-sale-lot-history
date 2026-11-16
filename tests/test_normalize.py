import copy
from decimal import Decimal

import pytest

from lot_history.normalize import content_hash, normalize, outcome_of, property_kind, text


def test_a_real_procedure_gives_every_field_the_review_needs(chain, settings):
    attempt = normalize(chain[0], settings)

    assert attempt.auction_id == "SPE001-UA-20261115-55411"
    assert attempt.previous_auction_id == "SPD001-UA-20261105-72962"
    assert attempt.attempt_number == 1
    assert (attempt.status, attempt.outcome) == ("active_tendering", "active")
    assert attempt.selling_method == "smallPrivatization-english"
    assert attempt.title.startswith("Цех стружки площею 207,5 кв. м")
    assert (attempt.value_amount, attempt.value_currency) == (Decimal("6325762.0"), "UAH")
    assert attempt.classification_id == "04211000-0"
    assert attempt.property_kind == "real_estate"
    assert (attempt.region, attempt.locality) == ("Волинська область", "м. Володимир")
    assert attempt.street_address == "вулиця Сонячна, 1"
    assert attempt.ownership_type == "state"
    assert attempt.seller_name
    assert attempt.date_modified.isoformat() == "2026-11-15T07:24:11.554000+00:00"


def test_every_attempt_links_to_its_source(chain, settings):
    attempt = normalize(chain[0], settings)

    assert attempt.source_api_url == f"https://procedure.prozorro.sale/api/procedures/{chain[0]['_id']}"
    assert attempt.source_page_url == "https://prozorro.sale/auction/SPE001-UA-20261115-55411/"


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("complete", "completed"),
        ("unsuccessful", "unsuccessful"),
        ("cancelled", "cancelled"),
        ("active_tendering", "active"),
        ("active_awarded", "active"),
        ("a_status_added_later", "active"),
    ],
)
def test_only_final_statuses_end_an_auction(status, outcome):
    assert outcome_of(status) == outcome


@pytest.mark.parametrize(
    ("classifier", "kind"),
    [("04211000-0", "real_estate"), ("06121000-6", "land"), ("34110000-1", "other"), (None, "other")],
)
def test_the_classifier_prefix_gives_the_property_kind(classifier, kind):
    assert property_kind(classifier) == kind


def test_texts_are_read_in_ukrainian_with_whitespace_collapsed():
    assert text({"uk_UA": "  Цех \r\n стружки ", "en_US": "Workshop"}) == "Цех стружки"
    assert text({"en_US": "Workshop"}) == "Workshop"
    assert text("plain") == "plain"
    assert text({"uk_UA": "   "}) is None
    assert text(None) is None


def test_a_seller_that_is_not_a_registered_legal_entity_is_not_kept(chain, settings):
    raw = copy.deepcopy(chain[0])
    raw["sellingEntity"] = {
        "identifier": {"scheme": "UA-IPN", "id": "1", "legalName": {"uk_UA": "Іваненко І. І."}}
    }

    assert normalize(raw, settings).seller_name is None


def test_a_procedure_without_items_or_value_is_still_an_attempt(chain, settings):
    raw = {key: chain[0][key] for key in ("_id", "auctionId", "status", "dateModified")}

    attempt = normalize(raw, settings)

    assert attempt.value_amount is None
    assert attempt.region is None
    assert attempt.property_kind == "other"
    assert attempt.previous_auction_id is None


def test_the_hash_ignores_what_the_review_does_not_look_at(chain, settings):
    raw = copy.deepcopy(chain[0])
    touched = copy.deepcopy(raw)
    touched["dateModified"] = "2026-11-16T10:00:00.000000Z"
    touched["documents"] = [{"title": "a new scan"}]

    assert content_hash(normalize(raw, settings)) == content_hash(normalize(touched, settings))


def test_the_hash_changes_with_the_status_and_with_the_price(chain, settings):
    raw = copy.deepcopy(chain[0])
    ended = {**raw, "status": "unsuccessful"}
    repriced = {**raw, "value": {**raw["value"], "amount": 3162881.0}}

    hashes = {content_hash(normalize(version, settings)) for version in (raw, ended, repriced)}

    assert len(hashes) == 3
