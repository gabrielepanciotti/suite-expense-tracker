"""HttpLedgerClient: the `LedgerClient` Protocol over finance's HTTP API."""
from __future__ import annotations

from typing import Any

import httpx
from expense_tracker.ledger import LIST_FILTERS, LedgerError, Row

_PAGE = 200


class HttpLedgerClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> HttpLedgerClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise LedgerError(f"finance unreachable ({method} {url}): {e}") from e
        if resp.status_code >= 400:
            raise LedgerError(f"finance {method} {url} -> {resp.status_code}: {resp.text[:300]}")
        return resp

    def create(self, payload: Row) -> tuple[Row, bool]:
        resp = self._request("POST", "/api/transactions", json=payload)
        # Contract: 201 = created, 200 = raw_hash already present (idempotent).
        return resp.json(), resp.status_code == 201

    def list(self, **filters: Any) -> list[Row]:
        unknown = set(filters) - set(LIST_FILTERS) - {"limit", "offset"}
        if unknown:
            raise LedgerError(f"unsupported filters: {sorted(unknown)}")
        params = {k: _param(v) for k, v in filters.items() if v is not None}
        cap = int(params.pop("limit", 0) or 0) or None
        params.pop("offset", None)
        out: list[Row] = []
        offset = 0
        while True:
            page = self._request(
                "GET", "/api/transactions", params={**params, "limit": _PAGE, "offset": offset}
            ).json()
            items = page.get("items", [])
            out.extend(items)
            offset += len(items)
            total = page.get("total", len(out))
            if not items or offset >= total or (cap is not None and len(out) >= cap):
                break
        return out if cap is None else out[:cap]

    def get(self, txn_id: int) -> Row:
        return self._request("GET", f"/api/transactions/{txn_id}").json()

    def patch(self, txn_id: int, changes: Row) -> Row:
        return self._request("PATCH", f"/api/transactions/{txn_id}", json=changes).json()


def _param(v: Any) -> Any:
    if isinstance(v, bool):
        return "true" if v else "false"
    return v
