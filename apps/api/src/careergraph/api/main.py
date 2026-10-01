"""Entrypoint: ``careergraph-api`` (uvicorn with proxy headers, structured logs)."""

from __future__ import annotations

import os

import uvicorn


def run() -> None:
    uvicorn.run(
        "careergraph.api.app:create_app",
        factory=True,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_config=None,
        access_log=False,
        timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    run()
