# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Process-level settings. Tenant credentials are never read from here."""

from pydantic_settings import BaseSettings, SettingsConfigDict

EMAIL_HEADER = "X-Epicor-Email"
PAT_HEADER = "X-Epicor-Pat"
BASE_URL_HEADER = "X-Epicor-Base-Url"

REQUIRED_HEADERS = [EMAIL_HEADER, PAT_HEADER]

DEFAULT_CDATA_BASE_URL = "https://mcp.cloud.cdata.com/mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    mcp_http_host: str = "0.0.0.0"
    mcp_http_port: int = 8080

    # The default CData Connect AI MCP endpoint. A request may override this with
    # X-Epicor-Base-Url for a non-default CData deployment.
    cdata_base_url: str = DEFAULT_CDATA_BASE_URL

    # Outbound HTTP behaviour (CData Connect AI's hosted MCP endpoint).
    connect_timeout: float = 5.0
    read_timeout: float = 30.0
    max_retries: int = 3
    # Upper bound for one tool call including retries (must stay below 120s).
    call_budget_seconds: float = 100.0


def get_settings() -> Settings:
    return Settings()
