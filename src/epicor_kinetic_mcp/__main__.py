# Copyright 2026 MSPbots.ai
# SPDX-License-Identifier: Apache-2.0
"""Entry point: ``python -m epicor_kinetic_mcp``."""

import logging
import sys

from .config import get_settings
from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()

    import uvicorn

    uvicorn.run(create_app(settings), host=settings.mcp_http_host, port=settings.mcp_http_port)


if __name__ == "__main__":
    main()
