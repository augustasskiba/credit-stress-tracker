"""Shared HTTP helper with retries and a polite User-Agent."""
from __future__ import annotations

import os
import time

import requests

# FRED rejects unknown custom User-Agents, so non-SEC requests use the requests library default.


def sec_user_agent() -> str:
    contact = os.environ.get("SEC_CONTACT_EMAIL", "").strip()
    if contact:
        return f"credit-stress-tracker {contact}"
    return "credit-stress-tracker research contact-unset@example.com"


def get(url: str, *, params=None, headers=None, timeout=30, retries=3, backoff=2.0) -> requests.Response:
    hdrs = dict(headers or {})
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=hdrs or None, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code} for {r.url}", response=r)
            r.raise_for_status()
            return r
        except requests.RequestException as exc:  # noqa: PERF203
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc
