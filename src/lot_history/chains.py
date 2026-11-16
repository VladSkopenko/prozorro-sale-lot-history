"""Зводить повторні аукціони в лоти.

Аукціон, який не відбувся, публікують знову як новий, а його `previousAuctionId` вказує на старий.
Стрічка віддає лише те, що змінилося за зібраний період, тому ранні аукціони ланцюжка дозбираємо
за номером. Лот — це набір спроб, які ведуть до одного кореня.
"""

from lot_history.client import ProzorroSaleClient
from lot_history.collector import ingest
from lot_history.config import Settings
from lot_history.store import Store


def backfill_previous(
    client: ProzorroSaleClient, store: Store, settings: Settings, max_fetches: int = 500
) -> tuple[int, int]:
    """Дозбирає попередні аукціони, на які посилаються збережені спроби, потім їхні попередні, доки
    кожен ланцюжок не дійде до першого аукціону. Повертає (дозібрано, не знайдено в джерелі)."""
    fetched = 0
    unresolved = 0
    while fetched + unresolved < max_fetches:
        missing = store.missing_previous()
        if not missing:
            break
        for auction_id in missing:
            if fetched + unresolved >= max_fetches:
                break
            raw = client.by_auction_id(auction_id)
            if raw is None:
                # запам'ятовуємо, щоб наступний запуск не питав про нього знову
                store.mark_unresolved(auction_id)
                unresolved += 1
                continue
            ingest(raw, store, settings)
            fetched += 1
    return fetched, unresolved


def lot_keys(links: dict[str, str | None]) -> dict[str, str]:
    """номер аукціону -> ключ лота, з `links` (номер аукціону -> попередній аукціон).

    Ключ — номер найранішого аукціону, до якого доходить ланцюжок: першого аукціону лота, якщо він
    збережений, інакше попереднього аукціону, на який ланцюжок посилається, але якого немає у сховищі.
    """
    keys: dict[str, str] = {}
    for auction_id in links:
        path: list[str] = []
        current = auction_id
        while True:
            if current in keys:
                # приєдналися до вже розв'язаного ланцюжка
                key = keys[current]
                break
            if current not in links or current in path:
                # попереднього аукціону немає у сховищі або в даних цикл: ланцюжок закінчується тут
                key = current
                break
            path.append(current)
            previous = links[current]
            if previous is None:
                # перший аукціон лота
                key = current
                break
            current = previous
        for member in path:
            keys[member] = key
    return keys


def assign_lots(store: Store) -> int:
    """Записує ключ лота кожній спробі. Повертає кількість лотів."""
    keys = lot_keys(store.links())
    store.set_lot_keys(keys)
    return len(set(keys.values()))
