"""
Process entrypoint. ``python -m godo_webctl`` (or ``uv run godo-webctl``)
launches uvicorn with a single worker.

``workers=1`` is a project invariant (D11): the tracker UDS server is
single-client and one-shot per connection; multi-worker uvicorn would
serialise nothing meaningful and only multiply the chances of stale-socket
races. Documented in CODEBASE.md.
"""

from __future__ import annotations

import uvicorn

from .app import create_app
from .config import load_settings


def _factory():  # pragma: no cover — invoked by uvicorn at process start
    return create_app()


def main() -> None:  # pragma: no cover — entrypoint shim
    settings = load_settings()
    uvicorn.run(
        "godo_webctl.__main__:_factory",
        host=settings.host,
        port=settings.port,
        factory=True,
        workers=1,
        log_level="info",
    )


if __name__ == "__main__":  # pragma: no cover
    main()
