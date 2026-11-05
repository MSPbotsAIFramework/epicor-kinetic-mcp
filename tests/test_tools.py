# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Tool behaviour against a mocked CData Connect AI MCP endpoint."""

import json

import httpx
import pytest
import respx
from conftest import BASE

pytestmark = pytest.mark.usefixtures("creds")

V1_TOOLS = {
    "epicor_search_context",
    "epicor_list_catalogs",
    "epicor_list_schemas",
    "epicor_list_tables",
    "epicor_list_columns",
    "epicor_query_data",
    "epicor_get_started",
}


def _result(text: str) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": text}]}}


async def test_tools_list_matches_v1_read_only_surface(mcp):
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == V1_TOOLS
    assert all(name.startswith("epicor_") for name in names)
    forbidden = ("insert", "update", "delete", "procedure", "execute")
    assert not any(word in name for name in names for word in forbidden)


# ---- epicor_query_data -----------------------------------------------------------


@respx.mock
async def test_query_data_defaults_and_shape(call):
    csv_text = "id,name\n1,Acme\n2,Globex\n"
    route = respx.post(BASE).mock(return_value=httpx.Response(200, json=_result(csv_text)))

    out = await call("epicor_query_data", sql="SELECT * FROM Customer")

    sent = json.loads(route.calls.last.request.content)
    assert sent["params"] == {"name": "queryData", "arguments": {"query": "SELECT * FROM Customer"}}
    assert out["limit"] == 50
    assert out["has_more"] is False
    assert out["rows"] == [{"id": "1", "name": "Acme"}, {"id": "2", "name": "Globex"}]


@respx.mock
async def test_query_data_truncates_oversized_result(call_raw):
    csv_text = "id,name\n" + "\n".join(f"{i},{'x' * 300}" for i in range(100))
    respx.post(BASE).mock(return_value=httpx.Response(200, json=_result(csv_text)))

    text = await call_raw("epicor_query_data", sql="SELECT * FROM BigTable", limit=200)

    assert len(text) <= 20_000
    out = json.loads(text)
    assert out["has_more"] is True
    assert out["count"] < 100


@respx.mock
async def test_query_data_row_count_limit_sets_has_more_even_under_char_cap(call):
    csv_text = "id\n" + "\n".join(str(i) for i in range(10))
    respx.post(BASE).mock(return_value=httpx.Response(200, json=_result(csv_text)))

    out = await call("epicor_query_data", sql="SELECT id FROM Customer", limit=5)

    assert out["count"] == 5
    assert out["has_more"] is True


# ---- discovery --------------------------------------------------------------------


@respx.mock
async def test_discovery_tools_trim_cdata_metadata(call):
    respx.post(BASE).mock(
        side_effect=[
            httpx.Response(200, json=_result(json.dumps([{"CatalogName": "Epicor"}]))),
            httpx.Response(200, json=_result(json.dumps([{"SchemaName": "dbo", "CatalogName": "Epicor"}]))),
            httpx.Response(
                200,
                json=_result(json.dumps([{"TableName": "Customer", "TableType": "TABLE", "SchemaName": "dbo"}])),
            ),
            httpx.Response(
                200,
                json=_result(json.dumps([{"ColumnName": "CustNum", "DataType": "INTEGER", "TableName": "Customer"}])),
            ),
        ]
    )

    catalogs = await call("epicor_list_catalogs")
    schemas = await call("epicor_list_schemas", catalog="Epicor")
    tables = await call("epicor_list_tables", catalog="Epicor", schema="dbo")
    columns = await call("epicor_list_columns", table="Customer")

    assert catalogs == {"items": [{"name": "Epicor"}], "count": 1}
    assert schemas == {"items": [{"name": "dbo", "parent": "Epicor"}], "count": 1}
    assert tables == {"items": [{"name": "Customer", "type": "TABLE", "parent": "dbo"}], "count": 1}
    assert columns == {
        "items": [{"name": "CustNum", "type": "INTEGER", "parent": "Customer"}],
        "count": 1,
    }


@respx.mock
async def test_search_context_returns_candidates(call):
    payload = {"items": [{"table": "Customer", "field": "Name"}]}
    respx.post(BASE).mock(return_value=httpx.Response(200, json=_result(json.dumps(payload))))

    out = await call("epicor_search_context", question="open sales orders")

    assert out == payload


# ---- help -----------------------------------------------------------------------


@respx.mock
async def test_get_started_combines_both_sources(call):
    respx.post(BASE).mock(
        side_effect=[
            httpx.Response(200, json=_result("Welcome to CData Connect AI.")),
            httpx.Response(200, json=_result("Epicor Kinetic: queryData accepts SELECT only.")),
        ]
    )

    out = await call("epicor_get_started")

    assert "Welcome to CData Connect AI." in out["text"]
    assert "Epicor Kinetic: queryData accepts SELECT only." in out["text"]


# ---- errors -----------------------------------------------------------------------


@respx.mock
async def test_missing_sql_is_invalid_argument(call):
    out = await call("epicor_query_data", sql="   ")
    assert out["error"]["code"] == "invalid_argument"


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (400, "invalid_argument", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
@respx.mock
async def test_error_status_codes_map_to_envelope(call, status, code, retryable):
    respx.post(BASE).mock(return_value=httpx.Response(status, json={"error": {"message": "boom"}}))

    out = await call("epicor_list_catalogs")

    assert out["error"]["code"] == code
    assert out["error"]["retryable"] is retryable
    assert out["error"]["message"]


@respx.mock
async def test_connection_error_is_upstream_error(call):
    respx.post(BASE).mock(side_effect=httpx.ConnectError("boom"))

    out = await call("epicor_list_catalogs")

    assert out["error"]["code"] == "upstream_error"
    assert out["error"]["retryable"] is True


@respx.mock
async def test_json_rpc_level_error_maps_to_invalid_argument(call):
    respx.post(BASE).mock(
        return_value=httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params"}}
        )
    )

    out = await call("epicor_list_catalogs")

    assert out["error"]["code"] == "invalid_argument"


@respx.mock
async def test_tool_level_is_error_never_raises(call):
    respx.post(BASE).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"isError": True, "content": [{"type": "text", "text": "Invalid SQL syntax near SELECT"}]},
            },
        )
    )

    out = await call("epicor_query_data", sql="SELECT *")

    assert "error" in out
    assert out["error"]["code"] in {"invalid_argument", "upstream_error"}
