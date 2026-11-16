"""Надсилає рядки лотів у таблицю Airtable для перевірки.

Рядки записуються як upsert за ключем лота, тому повторний запуск оновлює ті самі записи, а не додає
копії. Колонки, які заповнює рецензент («Перевірка», «Нотатки»), створюються разом із таблицею і
більше ніколи не записуються, тож синхронізація не може затерти роботу рецензента.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from lot_history.export import LotSummary

logger = logging.getLogger(__name__)

API = "https://api.airtable.com/v0"
# обмеження Airtable Web API: 10 записів на один запит запису, 5 запитів на секунду на базу
# і 30 секунд очікування після HTTP 429
BATCH_SIZE = 10
REQUEST_PAUSE = 0.25
RATE_LIMIT_WAIT = 30.0
MAX_RATE_LIMIT_RETRIES = 3

KEY_FIELD = "Ключ лота"
REVIEW_FIELDS = [
    {
        "name": "Перевірка",
        "type": "singleSelect",
        "options": {"choices": [{"name": "На перевірку"}, {"name": "Перевірено"}, {"name": "Відхилено"}]},
    },
    {"name": "Нотатки", "type": "multilineText"},
]
NUMBER = {"type": "number", "options": {"precision": 2}}
COUNT = {"type": "number", "options": {"precision": 0}}
TEXT = {"type": "singleLineText"}
LONG_TEXT = {"type": "multilineText"}
URL = {"type": "url"}

KIND_LABELS = {"real_estate": "нерухомість", "land": "земля", "other": "інше"}

# колонка Airtable -> (поле LotSummary, опис колонки); перша колонка стає основним полем таблиці
COLUMNS: dict[str, tuple[str, dict[str, Any]]] = {
    KEY_FIELD: ("lot_key", TEXT),
    "Назва": ("title", LONG_TEXT),
    "Тип": ("property_kind", TEXT),
    "Класифікатор": ("classification", TEXT),
    "Область": ("region", TEXT),
    "Населений пункт": ("locality", TEXT),
    "Адреса": ("street_address", TEXT),
    "Власність": ("ownership_type", TEXT),
    "Продавець": ("seller_name", TEXT),
    "Метод продажу": ("selling_method", TEXT),
    "Спроб": ("attempts", COUNT),
    "Не відбулося": ("unsuccessful_attempts", COUNT),
    "Скасовано": ("cancelled_attempts", COUNT),
    "Останній статус": ("latest_status", TEXT),
    "Початкова ціна": ("first_value", NUMBER),
    "Поточна ціна": ("latest_value", NUMBER),
    "Валюта": ("currency", TEXT),
    "Перша публікація": ("first_published", TEXT),
    "Остання зміна": ("latest_modified", TEXT),
    "Останній аукціон": ("latest_auction_id", TEXT),
    "Сторінка лота": ("source_page_url", URL),
    "Джерело (API)": ("source_api_url", URL),
    "Історія": ("history", LONG_TEXT),
}


class AirtableError(RuntimeError):
    pass


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0


def to_fields(summary: LotSummary) -> dict[str, Any]:
    """Поля Airtable одного лота. Порожні значення пропускаються: Airtable не приймає null у записі."""
    fields = {column: getattr(summary, attribute) for column, (attribute, _) in COLUMNS.items()}
    fields["Тип"] = KIND_LABELS.get(summary.property_kind, summary.property_kind)
    return {column: value for column, value in fields.items() if value is not None}


class AirtableClient:
    def __init__(
        self,
        token: str,
        base_id: str,
        table: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._base_id = base_id
        self._table = table
        self._http = http or httpx.Client(timeout=30.0)
        self._headers = {"Authorization": f"Bearer {token}"}
        self._sleep = sleep

    def ensure_table(self) -> bool:
        """Створює таблицю для перевірки, якщо її ще немає в базі. True, якщо таблицю створено."""
        tables = self._request("GET", f"{API}/meta/bases/{self._base_id}/tables")["tables"]
        if any(table["name"] == self._table for table in tables):
            return False
        fields = [{"name": column, **definition} for column, (_, definition) in COLUMNS.items()]
        self._request(
            "POST",
            f"{API}/meta/bases/{self._base_id}/tables",
            {"name": self._table, "fields": fields + REVIEW_FIELDS},
        )
        return True

    def upsert(self, summaries: list[LotSummary]) -> SyncResult:
        result = SyncResult()
        for start in range(0, len(summaries), BATCH_SIZE):
            batch = summaries[start : start + BATCH_SIZE]
            answer = self._request(
                "PATCH",
                f"{API}/{self._base_id}/{self._table}",
                {
                    "performUpsert": {"fieldsToMergeOn": [KEY_FIELD]},
                    "records": [{"fields": to_fields(summary)} for summary in batch],
                },
            )
            result.created += len(answer.get("createdRecords", []))
            result.updated += len(answer.get("updatedRecords", []))
            self._sleep(REQUEST_PAUSE)
        return result

    def _request(self, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        for _ in range(MAX_RATE_LIMIT_RETRIES + 1):
            response = self._http.request(method, url, json=body, headers=self._headers)
            if response.status_code == 429:
                logger.warning("Airtable просить сповільнитися, чекаю %s с", RATE_LIMIT_WAIT)
                self._sleep(RATE_LIMIT_WAIT)
                continue
            if response.status_code >= 400:
                raise AirtableError(
                    f"{method} {url} відповів HTTP {response.status_code}: {response.text[:300]}"
                )
            return response.json()
        raise AirtableError(f"{method} {url}: ліміт запитів {MAX_RATE_LIMIT_RETRIES + 1} рази поспіль")
