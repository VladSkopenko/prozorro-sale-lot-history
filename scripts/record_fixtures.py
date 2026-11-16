"""Записує відповіді API, на яких працюють тести.

Бере одну сторінку стрічки змін і один ланцюжок повторних торгів із живого API Prozorro.Продажі та
зберігає лише поля, які читає збирач. Контактні особи, банківські рахунки, ставки, рішення,
договори й документи відкидаються, тож у фікстурах немає персональних даних.

Запуск: python scripts/record_fixtures.py SPE001-UA-20261115-55411
"""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://procedure.prozorro.sale/api"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
KEPT_FIELDS = (
    "_id",
    "auctionId",
    "previousAuctionId",
    "tenderAttempts",
    "status",
    "sellingMethod",
    "title",
    "value",
    "auctionPeriod",
    "datePublished",
    "dateModified",
    "ownershipType",
)
KEPT_ITEM_FIELDS = ("classification", "address", "description", "quantity")
MAX_CHAIN = 12
FEED_SAMPLE = 12


def get(path: str):
    request = urllib.request.Request(f"{API}{path}", headers={"User-Agent": "lot-history fixtures"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def organisation(raw: dict) -> dict | None:
    """Продавець, лише якщо це юридична особа (реєстр ЄДР), і ніколи фізична особа."""
    entity = raw.get("sellingEntity") or (raw.get("relatedOrganizations") or {}).get("sellingEntity") or {}
    identifier = entity.get("identifier") or {}
    if identifier.get("scheme") != "UA-EDR":
        return None
    return {
        "identifier": {
            "scheme": "UA-EDR",
            "id": identifier.get("id"),
            "legalName": identifier.get("legalName"),
        }
    }


def sanitized(raw: dict) -> dict:
    kept = {field: raw[field] for field in KEPT_FIELDS if field in raw}
    kept["items"] = [
        {field: item[field] for field in KEPT_ITEM_FIELDS if field in item} for item in raw.get("items") or []
    ]
    seller = organisation(raw)
    if seller is not None:
        kept["sellingEntity"] = seller
    ownership = (raw.get("relatedOrganizations") or {}).get("ownershipType")
    if ownership and "ownershipType" not in kept:
        kept["ownershipType"] = ownership
    return kept


def chain(auction_id: str) -> list[dict]:
    procedures = []
    current: str | None = auction_id
    while current and len(procedures) < MAX_CHAIN:
        try:
            raw = get(f"/search/byAuctionId/{current}")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                break
            raise
        procedures.append(sanitized(raw))
        current = raw.get("previousAuctionId")
    return procedures


def main() -> None:
    auction_id = sys.argv[1]
    procedures = chain(auction_id)
    since = min(procedure["dateModified"] for procedure in procedures)[:10]
    feed = [sanitized(raw) for raw in get(f"/search/byDateModified/{since}T00:00:00?limit={FEED_SAMPLE}")]
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / "chain.json").write_text(json.dumps(procedures, ensure_ascii=False, indent=2) + "\n")
    (FIXTURES / "feed_page.json").write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n")
    print(f"ланцюжок: {len(procedures)} процедур, сторінка стрічки: {len(feed)} процедур")


if __name__ == "__main__":
    main()
