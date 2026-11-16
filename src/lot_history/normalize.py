"""Перетворює сиру процедуру джерела на `Attempt` і на хеш того, що в ній важливе."""

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from lot_history.config import Settings
from lot_history.models import Attempt, Outcome, PropertyKind

# статуси, що завершують аукціон; будь-який інший означає, що він ще триває
FINAL_OUTCOMES: dict[str, Outcome] = {
    "complete": "completed",
    "unsuccessful": "unsuccessful",
    "cancelled": "cancelled",
}

# перші дві цифри класифікатора CAV, яким джерело описує об'єкт аукціону
KIND_BY_CLASSIFIER_PREFIX: dict[str, PropertyKind] = {"04": "real_estate", "06": "land"}

# реєстр юридичних осіб; продавець з іншою схемою може бути фізичною особою, його не зберігаємо
LEGAL_ENTITY_SCHEME = "UA-EDR"

# поля, які нічого не кажуть про сам аукціон і не мають створювати нову версію
VOLATILE_FIELDS = ("date_modified", "source_api_url", "source_page_url")


def text(value: Any) -> str | None:
    """Джерело пише тексти як {"uk_UA": ..., "en_US": ...}; оригінал — українською."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("uk_UA") or value.get("en_US") or next(iter(value.values()), None)
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def outcome_of(status: str) -> Outcome:
    return FINAL_OUTCOMES.get(status, "active")


def property_kind(classification_id: str | None) -> PropertyKind:
    return KIND_BY_CLASSIFIER_PREFIX.get((classification_id or "")[:2], "other")


def _seller_name(raw: dict[str, Any]) -> str | None:
    entity = raw.get("sellingEntity") or (raw.get("relatedOrganizations") or {}).get("sellingEntity") or {}
    identifier = entity.get("identifier") or {}
    if identifier.get("scheme") != LEGAL_ENTITY_SCHEME:
        return None
    return text(identifier.get("legalName")) or text(entity.get("name"))


def normalize(raw: dict[str, Any], settings: Settings) -> Attempt:
    items = raw.get("items") or []
    first_item = items[0] if items else {}
    classification = first_item.get("classification") or {}
    address = first_item.get("address") or {}
    value = raw.get("value") or {}
    amount = value.get("amount")
    status = str(raw.get("status") or "unknown")
    classification_id = classification.get("id")
    attempts = raw.get("tenderAttempts")
    organizations = raw.get("relatedOrganizations") or {}
    return Attempt(
        procedure_id=raw["_id"],
        auction_id=raw["auctionId"],
        previous_auction_id=raw.get("previousAuctionId") or None,
        attempt_number=int(attempts) if attempts is not None else None,
        status=status,
        outcome=outcome_of(status),
        selling_method=str(raw.get("sellingMethod") or "unknown"),
        title=text(raw.get("title")) or "",
        # спершу str(): джерело шле float, і 6325762.0 не має стати 6325762.000000000001
        value_amount=Decimal(str(amount)) if amount is not None else None,
        value_currency=value.get("currency"),
        classification_id=classification_id,
        classification_name=text(classification.get("description")),
        property_kind=property_kind(classification_id),
        region=text(address.get("region")),
        locality=text(address.get("locality")),
        street_address=text(address.get("streetAddress")),
        ownership_type=raw.get("ownershipType") or organizations.get("ownershipType"),
        seller_name=_seller_name(raw),
        auction_start=timestamp((raw.get("auctionPeriod") or {}).get("startDate")),
        date_published=timestamp(raw.get("datePublished")),
        date_modified=timestamp(raw["dateModified"]),
        source_api_url=f"{settings.api_base}/procedures/{raw['_id']}",
        source_page_url=f"{settings.site_base}/auction/{raw['auctionId']}/",
    )


def content_hash(attempt: Attempt) -> str:
    """Однаковий для двох версій процедури, що різняться лише тим, на що перевірка не дивиться
    (нові документи, запитання, позначка часу зміни), тож такі версії не рахуються як зміна."""
    tracked = attempt.model_dump(mode="json", exclude=set(VOLATILE_FIELDS))
    canonical = json.dumps(tracked, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
