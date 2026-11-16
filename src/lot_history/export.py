"""Один рядок на лот для перевірки: що це, де, чим закінчився кожен аукціон, і посилання."""

import csv
import sqlite3
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from lot_history.store import Store


@dataclass(frozen=True)
class LotSummary:
    lot_key: str
    title: str
    property_kind: str
    classification: str | None
    region: str | None
    locality: str | None
    street_address: str | None
    ownership_type: str | None
    seller_name: str | None
    selling_method: str
    attempts: int
    unsuccessful_attempts: int
    cancelled_attempts: int
    latest_status: str
    latest_outcome: str
    first_value: float | None
    latest_value: float | None
    currency: str | None
    first_published: str | None
    latest_modified: str
    latest_auction_id: str
    source_page_url: str
    source_api_url: str
    history: str


def _day(stamp: str | None) -> str | None:
    return stamp[:10] if stamp else None


def _amount(value: str | None) -> float | None:
    return float(value) if value is not None else None


def _history_line(position: int, attempt: sqlite3.Row) -> str:
    price = (
        f"{float(attempt['value_amount']):,.2f} {attempt['value_currency']}"
        if attempt["value_amount"]
        else "-"
    )
    return (
        f"{position}. {_day(attempt['date_published']) or '?'} {attempt['auction_id']} "
        f"{attempt['status']} | {price} | {attempt['source_page_url']}"
    )


def summarize(attempts: list[sqlite3.Row]) -> LotSummary:
    """`attempts`: усі спроби одного лота, від найстарішої."""
    first, latest = attempts[0], attempts[-1]
    classification = " ".join(filter(None, [latest["classification_id"], latest["classification_name"]]))
    return LotSummary(
        lot_key=latest["lot_key"],
        title=latest["title"],
        property_kind=latest["property_kind"],
        classification=classification or None,
        region=latest["region"],
        locality=latest["locality"],
        street_address=latest["street_address"],
        ownership_type=latest["ownership_type"],
        seller_name=latest["seller_name"],
        selling_method=latest["selling_method"],
        attempts=len(attempts),
        unsuccessful_attempts=sum(attempt["outcome"] == "unsuccessful" for attempt in attempts),
        cancelled_attempts=sum(attempt["outcome"] == "cancelled" for attempt in attempts),
        latest_status=latest["status"],
        latest_outcome=latest["outcome"],
        first_value=_amount(first["value_amount"]),
        latest_value=_amount(latest["value_amount"]),
        currency=latest["value_currency"],
        first_published=_day(first["date_published"]),
        latest_modified=_day(latest["date_modified"]),
        latest_auction_id=latest["auction_id"],
        source_page_url=latest["source_page_url"],
        source_api_url=latest["source_api_url"],
        history="\n".join(_history_line(position, attempt) for position, attempt in enumerate(attempts, 1)),
    )


def lot_summaries(
    store: Store, kinds: Iterable[str] | None = None, min_attempts: int = 1
) -> list[LotSummary]:
    """Лоти з ключем, усередині кожного — від найстарішої спроби. Спроби без ключа (лоти ще не
    зведені) пропускаються: спершу запустіть крок ланцюжків."""
    wanted = set(kinds) if kinds is not None else None
    grouped: dict[str, list[sqlite3.Row]] = {}
    for attempt in store.attempts():
        if attempt["lot_key"] is not None:
            grouped.setdefault(attempt["lot_key"], []).append(attempt)
    summaries = [summarize(attempts) for attempts in grouped.values()]
    return [
        summary
        for summary in summaries
        if summary.attempts >= min_attempts and (wanted is None or summary.property_kind in wanted)
    ]


def write_csv(summaries: list[LotSummary], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LotSummary.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(asdict(summary) for summary in summaries)
