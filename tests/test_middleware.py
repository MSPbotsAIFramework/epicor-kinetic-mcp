# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from epicor_kinetic_mcp import credentials
from epicor_kinetic_mcp.config import DEFAULT_CDATA_BASE_URL, REQUIRED_HEADERS, Settings
from epicor_kinetic_mcp.server import create_app

LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
PLACEHOLDERS = {name: "probe-placeholder" for name in REQUIRED_HEADERS}


@pytest.fixture
def client():
    with TestClient(create_app(Settings())) as c:
        yield c


def test_health_needs_no_credentials(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_missing_both_credential_headers_returns_401(client):
    r = client.post("/mcp", json=LIST, headers=HEADERS)
    assert r.status_code == 401
    body = r.json()
    assert body["required_headers"] == REQUIRED_HEADERS
    assert set(body["missing_headers"]) == set(REQUIRED_HEADERS)


def test_missing_pat_header_returns_401(client):
    h = {**HEADERS, "X-Epicor-Email": "you@example.com"}
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 401
    assert r.json()["missing_headers"] == ["X-Epicor-Pat"]


def test_blank_header_counts_as_missing(client):
    h = {**HEADERS, **PLACEHOLDERS, "X-Epicor-Pat": "   "}
    assert client.post("/mcp", json=LIST, headers=h).status_code == 401


def test_placeholder_values_pass_initialize_and_tools_list(client):
    # The platform probes with placeholder values; CData-specific formats are not
    # validated by the middleware, only presence.
    h = {**HEADERS, **{k.lower(): v for k, v in PLACEHOLDERS.items()}}
    r = client.post("/mcp", json=LIST, headers=h)
    assert r.status_code == 200
    assert len(r.json()["result"]["tools"]) == 7


async def _call_as(mcp, email: str, pat: str) -> str:
    token = credentials._current.set(credentials.Credentials(email=email, pat=pat, base_url=DEFAULT_CDATA_BASE_URL))
    try:
        result = await mcp.call_tool("epicor_list_catalogs", {})
    finally:
        credentials._current.reset(token)
    blocks = result[0] if isinstance(result, tuple) else result
    return blocks[0].text


@respx.mock
async def test_concurrent_requests_keep_credentials_isolated(mcp):
    captured: list[str] = []

    def responder(request: httpx.Request) -> httpx.Response:
        captured.append(request.headers["authorization"])
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "[]"}]}},
        )

    respx.post(DEFAULT_CDATA_BASE_URL).mock(side_effect=responder)

    await asyncio.gather(
        _call_as(mcp, "tenant-a@example.com", "PAT_A"),
        _call_as(mcp, "tenant-b@example.com", "PAT_B"),
    )

    expected_a = "Basic " + base64.b64encode(b"tenant-a@example.com:PAT_A").decode()
    expected_b = "Basic " + base64.b64encode(b"tenant-b@example.com:PAT_B").decode()
    assert len(captured) == 2
    assert set(captured) == {expected_a, expected_b}
    # Neither call's credentials leaked into the other's outgoing header.
    assert captured[0] != captured[1]


def test_credentials_do_not_leak_outside_a_request():
    assert credentials.current() is None
