"""Один аукціон лота, зведений до полів, потрібних для перевірки."""

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

Outcome = Literal["completed", "unsuccessful", "cancelled", "active"]
PropertyKind = Literal["real_estate", "land", "other"]


class Attempt(BaseModel):
    """Окремий аукціон («процедура» в джерелі). Лот, який не продався, публікують знову як новий
    аукціон із посиланням на попередній, тому лот — це ланцюжок спроб."""

    model_config = ConfigDict(frozen=True)

    procedure_id: str
    auction_id: str
    previous_auction_id: str | None
    # джерело рахує спроби в межах одного кола продажу (1, 2, 3, потім знову 1);
    # загальну кількість дає ланцюжок
    attempt_number: int | None
    status: str
    outcome: Outcome
    selling_method: str
    title: str
    value_amount: Decimal | None
    value_currency: str | None
    classification_id: str | None
    classification_name: str | None
    property_kind: PropertyKind
    region: str | None
    locality: str | None
    street_address: str | None
    ownership_type: str | None
    seller_name: str | None
    auction_start: datetime | None
    date_published: datetime | None
    date_modified: datetime
    source_api_url: str
    source_page_url: str
