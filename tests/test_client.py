import httpx
import pytest

from lot_history.client import ProzorroSaleClient, SourceError
from lot_history.config import Settings


def client_for(handler, settings=None, sleeps=None):
    settings = settings or Settings(request_delay=0.5, max_retries=2)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    return ProzorroSaleClient(settings, http=http, sleep=(sleeps if sleeps is not None else []).append)


def test_the_feed_is_asked_from_a_stamp_with_a_limit():
    seen = []

    def handler(request):
        seen.append(request.url)
        return httpx.Response(200, json=[{"_id": "1"}])

    page = client_for(handler).feed("2026-11-15T00:00:00", 100)

    assert page == [{"_id": "1"}]
    assert seen[0].path == "/api/search/byDateModified/2026-11-15T00:00:00"
    assert seen[0].params["limit"] == "100"


def test_an_unknown_auction_number_is_none_not_an_error():
    client = client_for(lambda request: httpx.Response(404, json={"message": "not found"}))

    assert client.by_auction_id("XXX001-UA-20200101-00000") is None


def test_a_busy_server_is_asked_again_with_a_growing_pause():
    answers = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json={"_id": "1"})])
    sleeps = []

    result = client_for(lambda request: next(answers), sleeps=sleeps).by_auction_id("A")

    assert result == {"_id": "1"}
    # два повтори з подвоєнням паузи, потім ввічлива пауза після відповіді
    assert sleeps == [1.0, 2.0, 0.5]


def test_a_dropped_connection_is_retried():
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"_id": "1"})

    assert client_for(handler).by_auction_id("A") == {"_id": "1"}
    assert len(calls) == 2


def test_a_server_that_stays_down_is_reported_after_the_last_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(502)

    with pytest.raises(SourceError, match="немає відповіді після 3 спроб: HTTP 502"):
        client_for(handler).feed("2026-11-15T00:00:00", 10)
    assert len(calls) == 3


def test_a_rejected_request_is_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(422, json={"message": "not a valid ObjectId"})

    with pytest.raises(SourceError, match="HTTP 422"):
        client_for(handler).procedure("SPD001-UA-20261105-72962")
    assert len(calls) == 1
