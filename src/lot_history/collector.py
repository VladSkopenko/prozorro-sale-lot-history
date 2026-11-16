"""Читає стрічку змін сторінка за сторінкою і зберігає нове."""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from lot_history.client import ProzorroSaleClient, SourceError
from lot_history.config import Settings
from lot_history.normalize import content_hash, normalize
from lot_history.store import Store

logger = logging.getLogger(__name__)

FEED_CURSOR = "feed"
DEFAULT_KINDS = frozenset({"real_estate", "land"})
# до якого розміру може зрости сторінка, коли всі записи на ній мають одну позначку зміни
MAX_PAGE_SIZE = 5000


@dataclass
class CollectStats:
    pages: int = 0
    seen: int = 0
    skipped_kind: int = 0
    duplicate_versions: int = 0
    new_attempts: int = 0
    changed_attempts: int = 0
    unchanged_attempts: int = 0
    invalid: list[str] = field(default_factory=list)


def ingest(raw: dict[str, Any], store: Store, settings: Settings, stats: CollectStats | None = None) -> str:
    """Зберігає одну сиру процедуру. Повертає "duplicate", якщо ця версія вже збережена, інакше те,
    що сталося зі спробою: "new", "changed", "unchanged" або "stale"."""
    attempt = normalize(raw, settings)
    digest = content_hash(attempt)
    is_new_version = store.save_version(
        attempt.procedure_id, raw["dateModified"], digest, json.dumps(raw, ensure_ascii=False)
    )
    if not is_new_version:
        if stats:
            stats.duplicate_versions += 1
        return "duplicate"
    result = store.upsert_attempt(attempt, digest)
    if stats:
        if result == "new":
            stats.new_attempts += 1
        elif result == "changed":
            stats.changed_attempts += 1
        else:
            stats.unchanged_attempts += 1
    return result


def _page(client: ProzorroSaleClient, position: str, page_size: int) -> tuple[list[dict[str, Any]], bool]:
    """Одна сторінка стрічки і ознака, що далі можуть бути ще.

    Наступну сторінку запитуємо від позначки останнього запису. Якщо повна сторінка закінчується на
    тій самій позначці, з якої почалася, повторний запит вічно повертав би ту саму сторінку, тому
    сторінку розширюємо, доки вона не дійде до пізнішої позначки або до кінця стрічки.
    """
    limit = page_size
    while True:
        page = client.feed(position, limit)
        full = len(page) >= limit
        if not full or page[-1]["dateModified"] != position:
            return page, full
        if limit >= MAX_PAGE_SIZE:
            raise SourceError(f"понад {MAX_PAGE_SIZE} записів мають одну позначку зміни {position}")
        limit = min(limit * 2, MAX_PAGE_SIZE)
        logger.warning("уся сторінка стрічки має позначку %s, читаю %s записів", position, limit)


def collect(
    client: ProzorroSaleClient,
    store: Store,
    settings: Settings,
    since: str | None = None,
    max_pages: int | None = None,
    kinds: frozenset[str] | None = DEFAULT_KINDS,
) -> CollectStats:
    """Іде стрічкою від збереженого курсора (або від `since`) до кінця.

    Курсор зберігається після кожної сторінки, тож перерваний запуск продовжує з місця зупинки. Межа
    стрічки включна, тому кожна сторінка починається з уже збережених записів; `ingest` впізнає їх за
    позначкою зміни. `kinds=None` залишає об'єкти всіх типів, а не лише нерухомість і землю.
    """
    stats = CollectStats()
    position = since or store.cursor(FEED_CURSOR)
    if position is None:
        raise ValueError("курсора ще немає: для першого запуску вкажіть `since`")
    while max_pages is None or stats.pages < max_pages:
        page, more = _page(client, position, settings.page_size)
        stats.pages += 1
        for raw in page:
            stats.seen += 1
            try:
                attempt = normalize(raw, settings)
            except (KeyError, ValueError, TypeError) as error:
                # один зіпсований запис не має зупиняти запуск: про нього повідомляємо і пропускаємо
                stats.invalid.append(f"{raw.get('_id')}: {type(error).__name__}: {error}")
                continue
            if kinds is not None and attempt.property_kind not in kinds:
                stats.skipped_kind += 1
                continue
            ingest(raw, store, settings, stats)
        if page:
            position = page[-1]["dateModified"]
            store.set_cursor(FEED_CURSOR, position)
        if not more:
            break
    return stats
