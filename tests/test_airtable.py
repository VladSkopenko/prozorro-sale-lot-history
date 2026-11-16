import json
from dataclasses import replace

import httpx
import pytest

from lot_history.airtable import COLUMNS, KEY_FIELD, AirtableClient, AirtableError, to_fields
from lot_history.export import LotSummary


def summary(lot_key: str = "SPE001-UA-20260522-28555", **changes) -> LotSummary:
    base = LotSummary(
        lot_key=lot_key,
        title="Цех стружки",
        property_kind="real_estate",
        classification="04211000-0 Промислова будівля",
        region="Волинська область",
        locality="м. Володимир",
        street_address=None,
        ownership_type="state",
        seller_name=None,
        selling_method="smallPrivatization-english",
        attempts=12,
        unsuccessful_attempts=7,
        cancelled_attempts=4,
        latest_status="active_tendering",
        latest_outcome="active",
        first_value=3162881.0,
        latest_value=6325762.0,
        currency="UAH",
        first_published="2026-06-15",
        latest_modified="2026-11-15",
        latest_auction_id="SPE001-UA-20261115-55411",
        source_page_url="https://prozorro.sale/auction/SPE001-UA-20261115-55411/",
        source_api_url="https://procedure.prozorro.sale/api/procedures/6af95e1bfaf378a897b563a4",
        history="1. ...",
    )
    return replace(base, **changes)


class FakeAirtable:
    def __init__(self, answers=None, tables=()):
        self.requests: list[httpx.Request] = []
        self.answers = iter(answers or [])
        self.tables = list(tables)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        forced = next(self.answers, None)
        if forced is not None:
            return forced
        if request.url.path.endswith("/tables") and request.method == "GET":
            return httpx.Response(200, json={"tables": [{"name": name} for name in self.tables]})
        if request.url.path.endswith("/tables"):
            return httpx.Response(200, json={"id": "tblNew"})
        records = json.loads(request.content)["records"]
        return httpx.Response(
            200,
            json={"records": [], "createdRecords": ["rec"] * (len(records) - 1), "updatedRecords": ["rec"]},
        )

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests if request.content]


def client_for(fake: FakeAirtable, sleeps=None) -> AirtableClient:
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return AirtableClient(
        "pat-test", "appBase", "Lots", http=http, sleep=(sleeps if sleeps is not None else []).append
    )


def test_a_lot_becomes_named_columns_without_empty_values():
    fields = to_fields(summary())

    assert fields[KEY_FIELD] == "SPE001-UA-20260522-28555"
    assert fields["Спроб"] == 12
    assert fields["Тип"] == "нерухомість"
    assert fields["Сторінка лота"].startswith("https://prozorro.sale/auction/")
    assert "Адреса" not in fields and "Продавець" not in fields


def test_the_columns_a_reviewer_fills_in_are_never_sent():
    assert not {"Перевірка", "Нотатки"} & set(to_fields(summary()))
    assert not {"Перевірка", "Нотатки"} & set(COLUMNS)


def test_rows_go_in_batches_of_ten_as_upserts_on_the_lot_key():
    fake = FakeAirtable()
    lots = [summary(f"LOT-{number}") for number in range(25)]

    result = client_for(fake).upsert(lots)

    bodies = fake.bodies()
    assert [len(body["records"]) for body in bodies] == [10, 10, 5]
    assert all(body["performUpsert"] == {"fieldsToMergeOn": ["Ключ лота"]} for body in bodies)
    assert {request.method for request in fake.requests} == {"PATCH"}
    assert fake.requests[0].url.path == "/v0/appBase/Lots"
    assert fake.requests[0].headers["Authorization"] == "Bearer pat-test"
    assert (result.created, result.updated) == (22, 3)


def test_a_rate_limit_answer_is_waited_out_and_the_batch_is_sent_again():
    fake = FakeAirtable(answers=[httpx.Response(429, json={"errors": "rate"})])
    sleeps = []

    result = client_for(fake, sleeps).upsert([summary()])

    assert len(fake.requests) == 2
    assert sleeps[0] == 30.0
    assert result.updated == 1


def test_a_rejected_write_is_an_error_with_the_answer_in_it():
    fake = FakeAirtable(answers=[httpx.Response(422, json={"error": {"type": "UNKNOWN_FIELD_NAME"}})])

    with pytest.raises(AirtableError, match="HTTP 422.*UNKNOWN_FIELD_NAME"):
        client_for(fake).upsert([summary()])


def test_the_review_table_is_created_once_with_the_reviewer_columns():
    fake = FakeAirtable(tables=["Table 1"])

    assert client_for(fake).ensure_table() is True

    created = fake.bodies()[-1]
    names = [column["name"] for column in created["fields"]]
    assert created["name"] == "Lots"
    assert names[0] == "Ключ лота"
    assert names[-2:] == ["Перевірка", "Нотатки"]

    assert client_for(FakeAirtable(tables=["Table 1", "Lots"])).ensure_table() is False
