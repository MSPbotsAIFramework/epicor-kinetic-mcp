# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Schema discovery and natural-language search, proxied to CData Connect AI."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import CDataClient, parse_json_or_text
from ..config import Settings
from ._common import READ_IDEMPOTENT, run

# CData's hosted connectors expose schema metadata through its common provider naming
# (CatalogName/SchemaName/TableName/TableType, ColumnName/DataType, matching the
# ADO.NET/ODBC metadata views CData's drivers have used for years) -- these exact keys
# are not shown on https://docs.cloud.cdata.com/en/API/MCP itself (no response-shape
# example is given there), so this is a best-effort match, not a confirmed contract.
# Confirm against a real response once a CData Connect AI account is available
# (TC-EPICOR-007/008; see "Risks & dependencies" in docs/tickets/PRD-21335.md).
# Keyed per level because an item often carries more than one "*Name" field (a schema
# row also echoes its parent CatalogName) -- the level-specific order makes sure the
# item's own name wins over a parent reference with a similarly-named key.
_NAME_KEYS: dict[str, tuple[str, ...]] = {
    "catalogs": ("CatalogName", "name", "Name"),
    "schemas": ("SchemaName", "name", "Name"),
    "tables": ("TableName", "name", "Name"),
    "columns": ("ColumnName", "name", "Name"),
}
_TYPE_KEYS = ("TableType", "DataType", "Type", "type")
_PARENT_KEYS: dict[str, tuple[str, ...]] = {
    "catalogs": (),
    "schemas": ("CatalogName",),
    "tables": ("SchemaName", "CatalogName"),
    "columns": ("TableName", "SchemaName"),
}


def _first(item: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        if key in item and item[key] is not None:
            return str(item[key])
    return None


def _items(parsed: Any) -> list[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("items", "catalogs", "schemas", "tables", "columns", "results", "data", "rows"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
    return []


def _trim(level: str, parsed: Any) -> dict[str, Any]:
    parent_keys = _PARENT_KEYS[level]
    trimmed: list[dict[str, Any]] = []
    for raw in _items(parsed):
        if isinstance(raw, str):
            trimmed.append({"name": raw})
            continue
        if not isinstance(raw, dict):
            continue
        entry: dict[str, Any] = {"name": _first(raw, _NAME_KEYS[level]) or str(raw)}
        type_value = _first(raw, _TYPE_KEYS)
        if type_value is not None:
            entry["type"] = type_value
        parent_value = _first(raw, parent_keys) if parent_keys else None
        if parent_value is not None:
            entry["parent"] = parent_value
        trimmed.append(entry)
    return {"items": trimmed, "count": len(trimmed)}


def register(mcp: FastMCP, settings: Settings) -> None:
    @mcp.tool(
        name="epicor_search_context",
        description=(
            "Find Epicor Kinetic tables and fields relevant to a natural-language question, before writing a SQL query."
        ),
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_search_context(
        question: Annotated[str, Field(description="A natural-language description of the data you're looking for.")],
    ) -> str:
        async def handler(client: CDataClient):
            content = await client.call_tool("search_context", {"query": question})
            return parse_json_or_text(content)

        return await run(settings, handler)

    @mcp.tool(
        name="epicor_list_catalogs",
        description="List the catalogs (data sources) visible through this tenant's CData Connect AI connection.",
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_list_catalogs() -> str:
        async def handler(client: CDataClient):
            content = await client.call_tool("getCatalogs", {})
            return _trim("catalogs", parse_json_or_text(content))

        return await run(settings, handler)

    @mcp.tool(
        name="epicor_list_schemas",
        description="List the schemas in a catalog.",
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_list_schemas(
        catalog: Annotated[
            str | None, Field(description="Catalog name from epicor_list_catalogs. Omit to use the default catalog.")
        ] = None,
    ) -> str:
        async def handler(client: CDataClient):
            args = {"catalog": catalog} if catalog else {}
            content = await client.call_tool("getSchemas", args)
            return _trim("schemas", parse_json_or_text(content))

        return await run(settings, handler)

    @mcp.tool(
        name="epicor_list_tables",
        description="List the tables in a catalog/schema.",
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_list_tables(
        catalog: Annotated[str | None, Field(description="Catalog name. Omit to use the default catalog.")] = None,
        schema: Annotated[
            str | None, Field(description="Schema name from epicor_list_schemas. Omit to use the default schema.")
        ] = None,
    ) -> str:
        async def handler(client: CDataClient):
            args = {k: v for k, v in {"catalog": catalog, "schema": schema}.items() if v}
            content = await client.call_tool("getTables", args)
            return _trim("tables", parse_json_or_text(content))

        return await run(settings, handler)

    @mcp.tool(
        name="epicor_list_columns",
        description="List the columns of a table, with name and data type.",
        annotations=READ_IDEMPOTENT,
        structured_output=False,
    )
    async def epicor_list_columns(
        table: Annotated[str, Field(description="Table name from epicor_list_tables.")],
    ) -> str:
        async def handler(client: CDataClient):
            content = await client.call_tool("getColumns", {"table": table})
            return _trim("columns", parse_json_or_text(content))

        return await run(settings, handler)
