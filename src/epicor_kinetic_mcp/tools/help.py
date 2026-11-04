# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Onboarding/guidance text, combining CData's getStarted and getInstructions tools."""

from mcp.server.fastmcp import FastMCP

from ..api_client import CDataClient, first_text
from ..config import Settings
from ._common import READ_IDEMPOTENT, run


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="epicor_get_started",
        description="Get onboarding guidance and connector-specific tips for this Epicor Kinetic connection.",
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_get_started() -> str:
        async def handler(client: CDataClient):
            started = first_text(await client.call_tool("getStarted", {}))
            instructions = first_text(await client.call_tool("getInstructions", {}))
            parts = [p for p in (started.strip(), instructions.strip()) if p]
            return {"text": "\n\n".join(parts)}

        return await run(settings, handler)
