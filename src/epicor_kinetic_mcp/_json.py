# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Compact, size-capped JSON for tool results and the shared error envelope."""

import json
from typing import Any

MAX_CHARS = 20_000

ERROR_CODES = {
    "unauthorized",
    "invalid_argument",
    "rate_limited",
    "upstream_error",
}


def compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False, default=str)


def error(code: str, message: str, retryable: bool = False) -> str:
    assert code in ERROR_CODES, code
    return compact({"error": {"code": code, "message": message, "retryable": retryable}})


def dump_rows(rows: list[dict], *, limit_applied: int, has_more: bool = False, max_chars: int = MAX_CHARS) -> str:
    """Serialize a row list; if too large, drop rows from the end and flag has_more.

    ``has_more`` lets the caller report a cut it already made (e.g. the row-count
    limit) even when the character cap below never kicks in.
    """
    payload = {"rows": rows, "count": len(rows), "limit": limit_applied, "has_more": has_more}
    text = compact(payload)
    if len(text) <= max_chars:
        return text

    lo, hi = 0, len(rows)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        trial = {"rows": rows[:mid], "count": mid, "limit": limit_applied, "has_more": True}
        if len(compact(trial)) <= max_chars:
            lo = mid
        else:
            hi = mid - 1
    return compact({"rows": rows[:lo], "count": lo, "limit": limit_applied, "has_more": True})


def dump(data: Any, max_chars: int = MAX_CHARS) -> str:
    """Serialize arbitrary data (discovery/help results); truncate with a note if oversized."""
    text = compact(data)
    if len(text) <= max_chars:
        return text
    return compact(
        {
            "truncated": True,
            "note": f"Result is {len(text)} characters, above the {max_chars} limit. Narrow the request.",
            "preview": text[: max_chars // 2],
        }
    )
