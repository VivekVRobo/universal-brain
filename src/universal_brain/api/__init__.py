"""API package for Universal Brain.

The FastAPI application is loaded lazily so importing a schema/action module does not
instantiate database drivers or runtime singletons as a side effect.
"""
from __future__ import annotations

__all__ = ["app", "create_app"]


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from .app import app, create_app

        return app if name == "app" else create_app
    raise AttributeError(name)
