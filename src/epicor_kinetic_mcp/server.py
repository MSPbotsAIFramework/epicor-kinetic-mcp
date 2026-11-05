# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""FastMCP server and HTTP app."""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .config import Settings
from .credentials import CredentialMiddleware
from .tools import discovery, query
from .tools import help as help_tools

INSTRUCTIONS = (
    "Epicor Kinetic (ERP) data, reached through your organization's CData Connect AI account. "
    "This connector is read-only in v1: no inserts, updates, or stored-procedure execution. "
    "Typical flow: epicor_list_catalogs -> epicor_list_schemas -> epicor_list_tables -> "
    "epicor_list_columns to discover the data model, or epicor_search_context with a "
    "natural-language question to jump straight to relevant tables/fields, then "
    "epicor_query_data with a SELECT statement to read rows. Call epicor_get_started first "
    "if you are unsure what this tenant's Epicor Kinetic connection exposes."
)

MODULES = (discovery, query, help_tools)


def create_mcp(settings: Settings) -> FastMCP:
    mcp = FastMCP(
        name="epicor-kinetic-mcp",
        instructions=INSTRUCTIONS,
        stateless_http=True,
        json_response=True,
        # The gateway forwards requests with its own Host header; DNS-rebinding
        # protection would reject them with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    for module in MODULES:
        module.register(mcp, settings)
    return mcp


def create_app(settings: Settings) -> Starlette:
    mcp = create_mcp(settings)
    mcp_app = mcp.streamable_http_app()

    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Mount() does not run a sub-app's lifespan; without forwarding it the session
    # manager never starts and /mcp fails while /health still passes.
    return Starlette(
        routes=[Route("/health", health), Mount("/", app=CredentialMiddleware(mcp_app, settings))],
        lifespan=lambda app: mcp_app.router.lifespan_context(app),
    )
