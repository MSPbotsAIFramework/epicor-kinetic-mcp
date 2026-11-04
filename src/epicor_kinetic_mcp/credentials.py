# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Per-request credentials, taken only from request headers.

The gateway sends each tenant's CData Connect AI credentials on every request. They
live in a ContextVar for the duration of that request and are never stored anywhere
else (not in config, not in a module-level variable, not on disk).
"""

import contextvars
from dataclasses import dataclass, field

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import BASE_URL_HEADER, EMAIL_HEADER, PAT_HEADER, REQUIRED_HEADERS, Settings


@dataclass(frozen=True)
class Credentials:
    email: str
    pat: str = field(repr=False)
    base_url: str


_current: contextvars.ContextVar["Credentials | None"] = contextvars.ContextVar("epicor_credentials", default=None)


def current() -> "Credentials | None":
    return _current.get()


def _reject(missing: list[str]) -> JSONResponse:
    return JSONResponse(
        {
            "error": "Missing or invalid credentials",
            "message": f"Send your CData Connect AI credentials in these headers: {', '.join(missing)}.",
            "required_headers": REQUIRED_HEADERS,
            "missing_headers": missing,
        },
        status_code=401,
    )


class CredentialMiddleware:
    """Reads the CData Connect AI headers on /mcp requests and binds them to the request context."""

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        values = {name: (request.headers.get(name) or "").strip() for name in REQUIRED_HEADERS}
        missing = [name for name, value in values.items() if not value]
        if missing:
            await _reject(missing)(scope, receive, send)
            return

        base_url = (request.headers.get(BASE_URL_HEADER) or "").strip() or self.settings.cdata_base_url
        token = _current.set(
            Credentials(
                email=values[EMAIL_HEADER],
                pat=values[PAT_HEADER],
                base_url=base_url,
            )
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)
