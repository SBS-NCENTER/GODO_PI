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

    The C++ tracker emits ``{"ok": true, "keys": {<key>: <value>, ...}}``
    (see `production/RPi5/src/uds/json_mini.cpp::format_ok_get_config`).
    The wire shape consumed by the SPA (`protocol.ts::ConfigGetResponse`)
    is the FLAT dict ``{<key>: <value>, ...}``, so we unwrap the `keys`
    envelope here.

    Earlier revisions of this module assumed a flat ``{"ok": true,
    "<key>": <value>, ...}`` reply and only stripped ``ok`` — which left
    the SPA's `current["amcl.foo"]` resolving to ``undefined`` and the
    Config tab rendering "—" for every row even when the tracker was
    fully online. The C++ side has always wrapped under `keys` (since
    PR-CONFIG-α), so the projection layer is the right place to bridge
    the two shapes.

    Returns ``{}`` when:
      - the response is empty / lacks the ``keys`` field (e.g. a tracker
        error already mapped to a different code by `_map_uds_exc_to_response`),
      - or the ``keys`` field is non-dict (defensive — should not happen
        on a healthy tracker, but we don't crash the projection layer).
    """
    keys = uds_resp.get("keys")
    if isinstance(keys, dict):
        return keys
    return {}


def project_schema_view(rows: tuple[ConfigSchemaRow, ...]) -> list[dict[str, object]]:
    """Format the parsed schema for `/api/config/schema`.

    Thin wrapper over `config_schema.schema_to_json`. Kept here so the
    app.py handler imports a `config_view` module (Track E precedent
    naming) and future projections (e.g. operator-readable hints) live
    in one place.
    """
    return schema_to_json(rows)
