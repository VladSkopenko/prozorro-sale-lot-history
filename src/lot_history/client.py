"""Клієнт публічного API процедур Prozorro.Продажі. Тільки читання."""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from lot_history.config import Settings

logger = logging.getLogger(__name__)

# відповіді, після яких варто спробувати ще раз: сервер зайнятий або просить сповільнитися
RETRIED_STATUSES = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """Джерело не дало придатної відповіді після всіх повторів."""


class ProzorroSaleClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._http = http or httpx.Client(
            timeout=settings.timeout, headers={"User-Agent": settings.user_agent}
        )
        self._sleep = sleep

    def feed(self, since: str, limit: int) -> list[dict[str, Any]]:
        """Процедури, змінені в момент `since` або пізніше, від найстарішої зміни. Межа включна."""
        page = self._get(f"/search/byDateModified/{since}", params={"limit": limit})
        return page or []

    def procedure(self, procedure_id: str) -> dict[str, Any] | None:
        return self._get(f"/procedures/{procedure_id}")

    def by_auction_id(self, auction_id: str) -> dict[str, Any] | None:
        """Процедура з таким публічним номером аукціону або None, якщо джерело його не знає."""
        return self._get(f"/search/byAuctionId/{auction_id}")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._settings.api_base}{path}"
        failure = "жодної спроби"
        for attempt in range(self._settings.max_retries + 1):
            if attempt:
                self._sleep(self._settings.request_delay * 2**attempt)
            try:
                response = self._http.get(url, params=params)
            except httpx.TransportError as error:
                failure = f"{type(error).__name__}: {error}"
                logger.warning("GET %s не вдався (%s), спроба %s", url, failure, attempt + 1)
                continue
            if response.status_code == 404:
                return None
            if response.status_code in RETRIED_STATUSES:
                failure = f"HTTP {response.status_code}"
                logger.warning("GET %s відповів %s, спроба %s", url, failure, attempt + 1)
                continue
            if response.status_code != 200:
                raise SourceError(f"GET {url} відповів HTTP {response.status_code}: {response.text[:200]}")
            self._sleep(self._settings.request_delay)
            return response.json()
        raise SourceError(
            f"GET {url}: немає відповіді після {self._settings.max_retries + 1} спроб: {failure}"
        )
