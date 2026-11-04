# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Shared plumbing for tool handlers."""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.types import ToolAnnotations

from .. import _json
from ..api_client import ApiError, CDataClient
from ..config import REQUIRED_HEADERS, Settings
from ..credentials import current

log = logging.getLogger("epicor_kinetic_mcp")

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=False, openWorldHint=True)
READ_IDEMPOTENT = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True)


class ToolInputError(ValueError):
    """Raised by handlers for arguments CData would reject anyway."""


Handler = Callable[[CDataClient], Awaitable[Any]]


async def run(settings: Settings, handler: Handler) -> str:
    """Execute ``handler`` with a client bound to this request's credentials.

    Always returns a string: the JSON result, or an error envelope. Never raises --
    every tool must return structured output, per the platform's error contract.
    """
    creds = current()
    if creds is None:
        # The middleware already rejects requests missing a required header with a
        # 401 before any tool runs, so this should be unreachable in practice.
        return _json.error(
            "invalid_argument", f"No CData Connect AI credentials. Send the headers: {', '.join(REQUIRED_HEADERS)}."
        )
    try:
        async with CDataClient(creds, settings) as client:
            result = await handler(client)
    except ApiError as exc:
        return _json.error(exc.code, exc.message, exc.retryable)
    except ToolInputError as exc:
        return _json.error("invalid_argument", str(exc))
    except Exception:  # noqa: BLE001 - tools must never raise
        log.exception("unexpected error in tool handler")
        return _json.error("upstream_error", "Unexpected error while calling CData Connect AI.", True)
    return result if isinstance(result, str) else _json.dump(result)
