# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from epicor_kinetic_mcp import credentials
from epicor_kinetic_mcp.config import DEFAULT_CDATA_BASE_URL, Settings
from epicor_kinetic_mcp.server import create_mcp

BASE = DEFAULT_CDATA_BASE_URL


@pytest.fixture
def settings() -> Settings:
    # Keep retries fast in tests.
    return Settings(max_retries=2, call_budget_seconds=10)


@pytest.fixture
def mcp(settings):
    return create_mcp(settings)


@pytest.fixture
def creds():
    token = credentials._current.set(credentials.Credentials(email="you@example.com", pat="YOUR_PAT", base_url=BASE))
    yield
    credentials._current.reset(token)


@pytest.fixture
def call_raw(mcp):
    async def _call(tool: str, /, **args):
        result = await mcp.call_tool(tool, args)
        blocks = result[0] if isinstance(result, tuple) else result
        return blocks[0].text

    return _call


@pytest.fixture
def call(call_raw):
    async def _call(tool: str, /, **args):
        return json.loads(await call_raw(tool, **args))

    return _call


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    # Retries still happen, without waiting.
    async def _sleep(_seconds):
        return None

    monkeypatch.setattr("epicor_kinetic_mcp.api_client.asyncio.sleep", _sleep)
