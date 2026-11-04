# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Read-only SQL queries against Epicor Kinetic data, via CData Connect AI's queryData tool."""

from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .. import _json
from ..api_client import CDataClient, first_text, parse_csv_rows
from ..config import Settings
from ._common import READ_IDEMPOTENT, ToolInputError, run

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="epicor_query_data",
        description=(
            "Run a read-only SQL SELECT against Epicor Kinetic data (via CData Connect AI). "
            "CData rejects non-SELECT statements upstream. Use epicor_list_tables / "
            "epicor_list_columns first to find real table and column names."
        ),
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_query_data(
        sql: Annotated[str, Field(description="A SELECT statement, e.g. SELECT * FROM Customer")],
        limit: Annotated[
            int | None,
            Field(description=f"Max rows to return (default {DEFAULT_LIMIT}, hard max {MAX_LIMIT}).", ge=1),
        ] = None,
    ) -> str:
        capped_limit = min(int(limit or DEFAULT_LIMIT), MAX_LIMIT)

        async def handler(client: CDataClient):
            if not sql.strip():
                raise ToolInputError("sql must not be empty.")
            # The row cap is applied here, not by rewriting the caller's SQL (e.g.
            # injecting TOP/LIMIT) -- SQL dialects differ across CData-backed sources
            # and rewriting someone's query text is its own source of bugs.
            content = await client.call_tool("queryData", {"query": sql})
            rows = parse_csv_rows(first_text(content))
            has_more = len(rows) > capped_limit
            return _json.dump_rows(rows[:capped_limit], limit_applied=capped_limit, has_more=has_more)

        return await run(settings, handler)
