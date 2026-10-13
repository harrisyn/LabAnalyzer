"""Order (worklist) sources for answering instrument host queries.

``http`` provider: ``GET <url>?specimen_id=<id>&device_id=<id>`` must return
either ``[]`` / 404 (no orders) or JSON like::

    {"orders": [{"specimen_id": "S123", "tests": ["WBC", "HGB"], "priority": "R",
                 "specimen_type": "serum",
                 "patient": {"id": "P1", "family": "DOE", "given": "JANE",
                             "birth_date": "1980-01-31", "sex": "F"}}]}
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .. import __version__
from ..models import OrderRequest, Patient, PersonName, Query
from .senders import _basic, _ssl_context

log = logging.getLogger("labsync.orders")


class HttpOrderSource:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg

    async def lookup(self, query: Query, device_id: str) -> list[OrderRequest]:
        if not query.specimen_ids:
            return []
        url = self.cfg.get("url", "")
        auth_cfg = self.cfg.get("auth") or {}
        headers = {"Accept": "application/json", "User-Agent": f"LabSync/{__version__}"}
        if auth_cfg.get("method") == "api_key" and auth_cfg.get("api_key"):
            headers[auth_cfg.get("header") or "X-API-Key"] = auth_cfg["api_key"]
        elif auth_cfg.get("method") == "bearer" and auth_cfg.get("token"):
            headers["Authorization"] = f"Bearer {auth_cfg['token']}"
        elif auth_cfg.get("method") == "basic":
            headers["Authorization"] = _basic(auth_cfg.get("username", ""), auth_cfg.get("password", ""))
        timeout = aiohttp.ClientTimeout(total=float(self.cfg.get("timeout", 10)))
        orders: list[OrderRequest] = []
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for sid in query.specimen_ids:
                async with session.get(url, params={"specimen_id": sid, "device_id": device_id}, headers=headers,
                                       ssl=_ssl_context(self.cfg)) as resp:
                    if resp.status == 404:
                        continue
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                items = data.get("orders", []) if isinstance(data, dict) else (data or [])
                for item in items:
                    p = item.get("patient") or {}
                    orders.append(OrderRequest(
                        specimen_id=str(item.get("specimen_id") or sid),
                        tests=[str(t) for t in item.get("tests", [])],
                        priority=str(item.get("priority", "R")),
                        specimen_type=str(item.get("specimen_type", "")),
                        collected_at=str(item.get("collected_at", "")),
                        patient=Patient(id=str(p.get("id", "")),
                                        name=PersonName(family=p.get("family", ""), given=p.get("given", "")),
                                        birth_date=str(p.get("birth_date", "")), sex=str(p.get("sex", ""))),
                    ))
        log.info("order lookup for %s returned %d order(s)", ",".join(query.specimen_ids), len(orders))
        return orders


def make_order_source(cfg: dict[str, Any] | None):
    cfg = cfg or {}
    if cfg.get("provider") == "http" and cfg.get("url"):
        return HttpOrderSource(cfg)
    return None
