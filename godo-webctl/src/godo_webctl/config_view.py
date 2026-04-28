"""
Track B-CONFIG (PR-CONFIG-β) — pure projection helpers for the three
config endpoints. No FastAPI imports; no UDS imports. Tests can drive
these directly with dicts mocking the UDS reply shape.
"""

from __future__ import annotations

from typing import Any

from .config_schema import ConfigSchemaRow, schema_to_json


def project_config_view(uds_resp: dict[str, Any]) -> dict[str, Any]:
    """Project the tracker's `get_config` UDS reply down to the wire shape.

    The tracker emits ``{"ok": true, "<key>": <value>, ...}`` — one JSON
    field per schema row, with the JSON-typed value (int / number /
    string). We strip the protocol-level ``ok`` field; everything else
    flows through unchanged.

    A single key is dropped (``ok``); the projection is otherwise lossless
    so the SPA can iterate the dict without knowing the schema.
    """
    return {k: v for k, v in uds_resp.items() if k != "ok"}


def project_schema_view(rows: tuple[ConfigSchemaRow, ...]) -> list[dict[str, object]]:
    """Format the parsed schema for `/api/config/schema`.

    Thin wrapper over `config_schema.schema_to_json`. Kept here so the
    app.py handler imports a `config_view` module (Track E precedent
    naming) and future projections (e.g. operator-readable hints) live
    in one place.
    """
    return schema_to_json(rows)
