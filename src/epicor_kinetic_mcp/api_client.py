# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Thin async client for CData Connect AI's hosted MCP endpoint.

Reference: https://docs.cloud.cdata.com/en/API/MCP (fetched 2026-11-02 and again 2026-11-04).
- Endpoint: ``POST https://mcp.cloud.cdata.com/mcp`` (overridable per request via
  ``X-Epicor-Base-Url``), itself a Streamable HTTP MCP server.
- Auth: HTTP Basic, ``<Connect AI account email>:<Personal Access Token>``.
- Protocol: JSON-RPC 2.0 ``tools/call`` requests; the response is either a plain
  ``application/json`` body or a single ``text/event-stream`` SSE event carrying the
  same JSON-RPC envelope (both are valid MCP Streamable HTTP responses -- we don't
  know which mode CData runs in, so both are handled).
- ``queryData`` only accepts ``SELECT`` statements and returns CSV text in its
  ``content[0].text``; the discovery tools (``getCatalogs``/``getSchemas``/``getTables``/
  ``getColumns``/``search_context``/``getStarted``/``getInstructions``) have no documented
  response schema on that page, so their text is parsed defensively (JSON if it parses,
  otherwise returned as a single text item) -- see "Risks & dependencies" in
  docs/tickets/PRD-21335.md: this is the part most likely to need adjustment once a real
  CData Connect AI account is available (TC-EPICOR-006/008).
"""

import asyncio
import base64
import csv
import io
import json
import time
from dataclasses import dataclass
from itertools import count
from typing import Any
from urllib.parse import urlparse

import httpx

from .config import Settings
from .credentials import Credentials

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_BACKOFF = 20.0
_ID_SEQ = count(1)


@dataclass
class ApiError(Exception):
    code: str
    message: str
    retryable: bool = False
    status: int | None = None

    def __str__(self) -> str:
        return self.message


def validate_base_url(raw: str) -> str:
    """The base URL is either CData's default endpoint or an explicit override.

    Unlike a REST API, there is no vendor-specific path shape to normalise here --
    the whole URL is the JSON-RPC endpoint -- so this only rejects obviously-wrong
    values (used by placeholder/probe credentials, see test_middleware.py).
    """
    text = (raw or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise ApiError(
            "invalid_argument",
            "X-Epicor-Base-Url must be a full URL such as https://mcp.cloud.cdata.com/mcp (got an invalid value).",
        )
    return text


def _auth_header(creds: Credentials) -> str:
    raw = f"{creds.email}:{creds.pat}".encode()
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _retry_after(response: httpx.Response, attempt: int) -> float:
    value = response.headers.get("retry-after")
    if value:
        try:
            return max(0.0, min(float(value), MAX_BACKOFF))
        except ValueError:
            pass
    return min(2.0**attempt, MAX_BACKOFF)


def _status_to_error(status: int, detail: str) -> ApiError:
    if status in (401, 403):
        return ApiError(
            "unauthorized",
            f"CData Connect AI rejected the credentials ({status}). Check the email and personal access token. "
            f"{detail}".strip(),
            False,
            status,
        )
    if status in (400, 404, 405, 409, 415, 422):
        return ApiError(
            "invalid_argument", f"CData Connect AI refused the request ({status}). {detail}".strip(), False, status
        )
    if status == 429:
        return ApiError("rate_limited", "CData Connect AI rate limit reached. Try again shortly.", True, status)
    return ApiError("upstream_error", f"CData Connect AI returned {status}. {detail}".strip(), status >= 500, status)


_ERROR_TEXT_HINTS: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("unauthorized", "authentication", "invalid credentials", "forbidden"), "unauthorized", False),
    (("rate limit", "too many requests"), "rate_limited", True),
    (("invalid", "syntax", "bad request", "not supported", "only select"), "invalid_argument", False),
)


def _classify_tool_error(message: str) -> ApiError:
    """CData's own ``isError`` tool results carry no status code or machine-readable
    code (per the documented page), so this is a best-effort text match. Confirmed
    HTTP-level and JSON-RPC-level errors (above) take precedence and do not go
    through this path."""
    lowered = message.lower()
    for keywords, code, retryable in _ERROR_TEXT_HINTS:
        if any(k in lowered for k in keywords):
            return ApiError(code, message, retryable)
    return ApiError("upstream_error", message, False)


def _parse_sse_json(text: str) -> Any:
    """A Streamable HTTP SSE response carries one or more ``data:`` events; the
    JSON-RPC reply is the last complete one."""
    data_lines = [line[len("data:") :].strip() for line in text.splitlines() if line.startswith("data:")]
    if not data_lines:
        raise ApiError("upstream_error", "CData Connect AI returned an empty event stream.", True)
    return json.loads(data_lines[-1])


class CDataClient:
    """One instance per tool call; wraps a single httpx client for that call."""

    def __init__(self, creds: Credentials, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._creds = creds
        self._base_url = validate_base_url(creds.base_url)
        self._deadline = time.monotonic() + settings.call_budget_seconds
        self._http = httpx.AsyncClient(
            headers={
                "Authorization": _auth_header(creds),
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "User-Agent": "mspbots-epicor-kinetic-mcp/1.0",
            },
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            transport=transport,
        )

    async def __aenter__(self) -> "CDataClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._http.aclose()

    def time_left(self) -> float:
        return self._deadline - time.monotonic()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Call one CData tool via JSON-RPC ``tools/call``. Returns the MCP content list
        (``result.content``), e.g. ``[{"type": "text", "text": "..."}]``."""
        body = {
            "jsonrpc": "2.0",
            "id": next(_ID_SEQ),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
        envelope = await self._send(body)
        if "error" in envelope:
            err = envelope["error"] or {}
            jrpc_code = err.get("code")
            message = str(err.get("message") or "CData Connect AI returned a JSON-RPC error.")
            # JSON-RPC's own error-code space (invalid params / invalid request) maps to
            # invalid_argument; anything else (internal error, method not found) is upstream_error.
            if jrpc_code in (-32600, -32601, -32602, -32700):
                raise ApiError("invalid_argument", message, False)
            raise ApiError("upstream_error", message, True)

        result = envelope.get("result") or {}
        content = result.get("content") or []
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in content if isinstance(c, dict)) or "CData tool call failed."
            raise _classify_tool_error(text)
        return content

    async def _send(self, body: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            if self.time_left() <= 0:
                raise ApiError("upstream_error", "Time budget for this call ran out.", True)
            try:
                response = await self._http.post(self._base_url, json=body)
            except httpx.TimeoutException as exc:
                if attempt < self._settings.max_retries and self.time_left() > 1 + 2.0 ** (attempt + 1):
                    attempt += 1
                    await asyncio.sleep(min(2.0**attempt, MAX_BACKOFF))
                    continue
                raise ApiError("upstream_error", "CData Connect AI did not respond in time.", True) from exc
            except httpx.HTTPError as exc:
                raise ApiError(
                    "upstream_error", f"Could not reach CData Connect AI: {type(exc).__name__}.", True
                ) from exc

            status = response.status_code
            if status in RETRY_STATUSES and attempt < self._settings.max_retries:
                wait = _retry_after(response, attempt + 1)
                if self.time_left() > wait + 1:
                    attempt += 1
                    await asyncio.sleep(wait)
                    continue
            if status >= 400:
                raise _status_to_error(status, _error_detail(response))
            return _decode_envelope(response)


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
    return ""


def _decode_envelope(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        return _parse_sse_json(response.text)
    try:
        return response.json()
    except ValueError as exc:
        raise ApiError("upstream_error", "CData Connect AI returned a response that is not JSON.", True) from exc


def parse_csv_rows(csv_text: str) -> list[dict[str, str]]:
    """``queryData`` returns CSV text; turn it into a list of row dicts (header row = keys)."""
    if not csv_text.strip():
        return []
    reader = csv.DictReader(io.StringIO(csv_text))
    return [dict(row) for row in reader]


def first_text(content: list[dict[str, Any]]) -> str:
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text", "")
    return ""


def parse_json_or_text(content: list[dict[str, Any]]) -> Any:
    """Discovery/help tools have no documented response schema; try JSON first, fall
    back to the raw text wrapped in a dict so the shape is still predictable."""
    text = first_text(content)
    if not text:
        return {"items": []}
    try:
        return json.loads(text)
    except ValueError:
        return {"text": text}
