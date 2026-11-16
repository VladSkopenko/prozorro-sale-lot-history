import copy
import json
from pathlib import Path

import httpx
import pytest

from lot_history.client import ProzorroSaleClient
from lot_history.config import Settings
from lot_history.store import Store

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSource:
    """Замінює API Prozorro.Продажі: ті самі маршрути, дані — зі списку процедур."""

    def __init__(self, procedures: list[dict]) -> None:
        self.procedures = copy.deepcopy(procedures)
        self.requests: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if "/search/byDateModified/" in path:
            since = path.rsplit("/", 1)[1]
            limit = int(request.url.params["limit"])
            matching = [p for p in self.procedures if p["dateModified"] >= since]
            return httpx.Response(200, json=sorted(matching, key=lambda p: p["dateModified"])[:limit])
        if "/search/byAuctionId/" in path:
            auction_id = path.rsplit("/", 1)[1]
            found = [p for p in self.procedures if p["auctionId"] == auction_id]
            if found:
                return httpx.Response(200, json=found[0])
            return httpx.Response(404, json={"message": f"Procedure with auctionId {auction_id} not found"})
        return httpx.Response(500, json={"message": "unexpected route"})

    def lookups(self) -> list[str]:
        return [path.rsplit("/", 1)[1] for path in self.requests if "/search/byAuctionId/" in path]


@pytest.fixture
def settings() -> Settings:
    return Settings(request_delay=0, page_size=5, max_retries=2)


@pytest.fixture
def chain() -> list[dict]:
    """Справжній лот: 12 аукціонів однієї державної будівлі, від найновішого."""
    return json.loads((FIXTURES / "chain.json").read_text(encoding="utf-8"))


@pytest.fixture
def feed_page() -> list[dict]:
    """Справжня сторінка стрічки: земля, нерухомість і один автомобіль, від найстарішої зміни."""
    return json.loads((FIXTURES / "feed_page.json").read_text(encoding="utf-8"))


@pytest.fixture
def store() -> Store:
    database = Store(":memory:")
    yield database
    database.close()


@pytest.fixture
def connect(settings):
    """Створює клієнта, який звертається до FakeSource, а не до мережі."""

    def build(source: FakeSource) -> ProzorroSaleClient:
        http = httpx.Client(transport=httpx.MockTransport(source.handler))
        return ProzorroSaleClient(settings, http=http, sleep=lambda seconds: None)

    return build
