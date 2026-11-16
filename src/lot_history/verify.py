"""Звіряє збережену спробу з джерелом, з якого вона прийшла."""

from dataclasses import dataclass

from lot_history.client import ProzorroSaleClient
from lot_history.config import Settings
from lot_history.normalize import VOLATILE_FIELDS, normalize
from lot_history.store import Store, iso


@dataclass(frozen=True)
class Difference:
    field: str
    stored: str | None
    source: str | None


@dataclass(frozen=True)
class Verification:
    auction_id: str
    found_in_store: bool
    found_at_source: bool
    source_page_url: str | None
    stored_modified: str | None
    source_modified: str | None
    differences: tuple[Difference, ...]

    @property
    def matches(self) -> bool:
        return self.found_in_store and self.found_at_source and not self.differences


def _as_stored(value: object) -> str | None:
    """Записує нормалізоване значення так, як його зберігає сховище."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return iso(value)
    return str(value)


def verify(client: ProzorroSaleClient, store: Store, settings: Settings, auction_id: str) -> Verification:
    """Завантажує аукціон заново і перелічує кожне відстежуване поле, де сховище і джерело різняться.
    Розбіжність із новішою позначкою джерела означає, що лот змінився після останнього збору."""
    stored = store.attempt(auction_id)
    raw = client.by_auction_id(auction_id)
    if stored is None or raw is None:
        return Verification(
            auction_id=auction_id,
            found_in_store=stored is not None,
            found_at_source=raw is not None,
            source_page_url=stored["source_page_url"] if stored is not None else None,
            stored_modified=stored["date_modified"] if stored is not None else None,
            source_modified=raw["dateModified"] if raw is not None else None,
            differences=(),
        )
    current = normalize(raw, settings).model_dump()
    differences = tuple(
        Difference(field=name, stored=_as_stored(stored[name]), source=_as_stored(value))
        for name, value in current.items()
        if name not in VOLATILE_FIELDS and _as_stored(stored[name]) != _as_stored(value)
    )
    return Verification(
        auction_id=auction_id,
        found_in_store=True,
        found_at_source=True,
        source_page_url=stored["source_page_url"],
        stored_modified=stored["date_modified"],
        source_modified=iso(current["date_modified"]),
        differences=differences,
    )
