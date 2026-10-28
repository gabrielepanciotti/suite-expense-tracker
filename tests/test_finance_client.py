"""HttpLedgerClient against a mocked finance (httpx.MockTransport — no network)."""
import json

import httpx
import pytest
from expense_tracker.ledger import LedgerError
from expense_tracker_backend.finance_client import HttpLedgerClient


def _client(handler) -> HttpLedgerClient:
    return HttpLedgerClient("http://finance.test", transport=httpx.MockTransport(handler))


def test_create_maps_201_and_200():
    seen: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        status = 201 if len(seen) == 1 else 200
        return httpx.Response(status, json={"id": 1, **body})

    c = _client(handler)
    row, created = c.create({"description": "x", "amount_cents": 1, "raw_hash": "h"})
    assert created is True and row["id"] == 1
    _, created = c.create({"description": "x", "amount_cents": 1, "raw_hash": "h"})
    assert created is False
    assert seen[0]["raw_hash"] == "h"


def test_list_walks_every_page_and_serialises_bools():
    rows = [{"id": i} for i in range(450)]
    calls: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        q = dict(req.url.params)
        calls.append(q)
        off, lim = int(q["offset"]), int(q["limit"])
        return httpx.Response(200, json={"items": rows[off:off + lim], "total": len(rows)})

    out = _client(handler).list(status="proposto", shared=True, date_from="2026-01-01")
    assert len(out) == 450
    assert len(calls) == 3
    assert calls[0]["shared"] == "true" and calls[0]["status"] == "proposto"


def test_list_rejects_unknown_filter():
    with pytest.raises(LedgerError):
        _client(lambda r: httpx.Response(200, json={"items": [], "total": 0})).list(amount=1)


def test_patch_and_get_paths():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "PATCH":
            assert req.url.path == "/api/transactions/5"
            return httpx.Response(200, json={"id": 5, **json.loads(req.content)})
        return httpx.Response(200, json={"id": 5, "status": "proposto"})

    c = _client(handler)
    assert c.patch(5, {"status": "confermato"})["status"] == "confermato"
    assert c.get(5)["status"] == "proposto"


def test_http_errors_raise_never_return_empty():
    c = _client(lambda r: httpx.Response(500, text="boom"))
    with pytest.raises(LedgerError, match="500"):
        c.list()


def test_unreachable_finance_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(LedgerError, match="unreachable"):
        _client(handler).create({"description": "x"})
