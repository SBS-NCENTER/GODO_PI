"""
issue#30 — Sole owner of the `godo.map.sidecar.v1` JSON schema.

Sidecar JSON is the cumulative-tracking + lineage SSOT for derived maps.
Lives peer to the PGM + YAML pair as
`<base>.YYYYMMDD-HHMMSS-<memo>.sidecar.json`.

Module discipline:
- Stdlib only (`json`, `hashlib`, `dataclasses`, `pathlib`, `math`).
- Does NOT import Pillow, `maps.py`, or `map_transform.py`. Mirrors
  `map_origin.py`'s leaf discipline.
- Schema reads reject unknown major versions explicitly so a future v2
  cannot be silently mishandled.
- SHA over on-disk bytes is verbatim (no canonicalisation) — pinned by
  `test_sha256_no_canonicalisation_raw_bytes`.

Public API:

    @dataclass(frozen=True)
    class Sidecar: ...

    class SidecarError, SidecarMissing, SidecarSchemaMismatch,
          SidecarIntegrityFailed: ...

    def read(path: Path) -> Sidecar: ...
    def write(path: Path, sc: Sidecar) -> None: ...
    def compute_sha256(path: Path) -> str: ...
    def synthesize_for_orphan_pair(pgm: Path, yaml: Path,
                                   *, kind_label: str | None = None) -> Sidecar: ...
    def verify_integrity(sc: Sidecar, pgm: Path, yaml: Path) -> bool: ...
    def compose_cumulative(parent: Cumulative,
                            this_step_local: ThisStep) -> Cumulative: ...
    def recovery_sweep(maps_dir: Path) -> dict[str, int]: ...
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    DERIVED_NAME_REGEX,
    SIDECAR_EXT,
    SIDECAR_GENERATION_UNKNOWN,
    SIDECAR_LINEAGE_KIND_AUTO_MIGRATED,
    SIDECAR_LINEAGE_KIND_SYNTHESIZED,
    SIDECAR_SCHEMA,
)

logger = logging.getLogger("godo_webctl.sidecar")

_SIDECAR_FILE_MODE = 0o644
_TMP_SUFFIX = ".tmp"
_PGM_EXT = "pgm"
_YAML_EXT = "yaml"
# TODO(issue#30+): on schema v2 ship, document migration policy +
# bump rejection error code (currently `sidecar_schema_mismatch` lumps
# together unknown major + parse failure; v2 may want
# `sidecar_schema_v2` so callers can choose between auto-downgrade and
# refuse).
_SCHEMA_MAJOR_PREFIX = "godo.map.sidecar.v"


# --- Errors ------------------------------------------------------------


class SidecarError(Exception):
    """Base for sidecar-module exceptions."""


class SidecarMissing(SidecarError):
    """Sidecar JSON file does not exist."""


class SidecarSchemaMismatch(SidecarError):
    """Schema literal does not match `godo.map.sidecar.v1` (or unknown
    major version)."""


class SidecarIntegrityFailed(SidecarError):
    """SHA mismatch detected on sidecar verify. Mapped to HTTP 422 +
    `err: "sidecar_sha_mismatch"` at the app layer."""


# --- Data classes ----------------------------------------------------


@dataclass(frozen=True)
class Cumulative:
    """Mirror of `map_transform.Cumulative` — duplicated here so this
    module can stay leaf-clean without importing map_transform."""

    translate_x_m: float
    translate_y_m: float
    rotate_deg: float


@dataclass(frozen=True)
class ThisStep:
    delta_translate_x_m: float
    delta_translate_y_m: float
    delta_rotate_deg: float
    picked_world_x_m: float
    picked_world_y_m: float


@dataclass(frozen=True)
class Sidecar:
    """Reified `godo.map.sidecar.v1` body."""

    schema: str
    kind: str
    source_pristine_pgm: str
    source_pristine_yaml: str
    lineage_generation: int
    lineage_parents: tuple[str, ...]
    lineage_kind: str
    cumulative_from_pristine: Cumulative
    this_step: ThisStep | None
    result_yaml_origin: tuple[float, float, float]
    result_canvas: tuple[int, int]
    pgm_sha256: str
    yaml_sha256: str
    created_iso_kst: str
    created_memo: str
    created_reason: str

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema": self.schema,
            "kind": self.kind,
            "source": {
                "pristine_pgm": self.source_pristine_pgm,
                "pristine_yaml": self.source_pristine_yaml,
            },
            "lineage": {
                "generation": self.lineage_generation,
                "parents": list(self.lineage_parents),
                "kind": self.lineage_kind,
            },
            "cumulative_from_pristine": {
                "translate_x_m": self.cumulative_from_pristine.translate_x_m,
                "translate_y_m": self.cumulative_from_pristine.translate_y_m,
                "rotate_deg": self.cumulative_from_pristine.rotate_deg,
            },
            "result_yaml_origin": {
                "x_m": self.result_yaml_origin[0],
                "y_m": self.result_yaml_origin[1],
                "yaw_deg": self.result_yaml_origin[2],
            },
            "result_canvas": {
                "width_px": self.result_canvas[0],
                "height_px": self.result_canvas[1],
            },
            "integrity": {
                "pgm_sha256": self.pgm_sha256,
                "yaml_sha256": self.yaml_sha256,
            },
            "created": {
                "iso_kst": self.created_iso_kst,
                "memo": self.created_memo,
                "reason": self.created_reason,
            },
        }
        if self.this_step is not None:
            body["this_step"] = {
                "delta_translate_x_m": self.this_step.delta_translate_x_m,
                "delta_translate_y_m": self.this_step.delta_translate_y_m,
                "delta_rotate_deg": self.this_step.delta_rotate_deg,
                "picked_world_x_m": self.this_step.picked_world_x_m,
                "picked_world_y_m": self.this_step.picked_world_y_m,
            }
        else:
            body["this_step"] = None
        return body


# --- Read ------------------------------------------------------------


def read(path: Path) -> Sidecar:
    """Read + parse a sidecar JSON file. Raises `SidecarMissing` (file
    absent) or `SidecarSchemaMismatch` (schema literal unknown)."""
    if not path.is_file():
        raise SidecarMissing(str(path))
    try:
        body = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SidecarSchemaMismatch(f"json_decode_failed: {e}") from e
    return _from_dict(body)


def _from_dict(body: dict[str, object]) -> Sidecar:
    schema = body.get("schema")
    if not isinstance(schema, str):
        raise SidecarSchemaMismatch("schema_missing_or_not_string")
    if schema != SIDECAR_SCHEMA:
        # Reject unknown major versions explicitly.
        if schema.startswith(_SCHEMA_MAJOR_PREFIX):
            raise SidecarSchemaMismatch(f"unsupported_schema_version: {schema}")
        raise SidecarSchemaMismatch(f"unknown_schema: {schema}")

    kind = _str_field(body, "kind")
    source = _dict_field(body, "source")
    lineage = _dict_field(body, "lineage")
    cumulative = _dict_field(body, "cumulative_from_pristine")
    result_origin = _dict_field(body, "result_yaml_origin")
    result_canvas = _dict_field(body, "result_canvas")
    integrity = _dict_field(body, "integrity")
    created = _dict_field(body, "created")
    this_step_raw = body.get("this_step")

    parents_raw = lineage.get("parents", [])
    if not isinstance(parents_raw, list):
        raise SidecarSchemaMismatch("lineage.parents_not_list")
    parents = tuple(str(p) for p in parents_raw)

    this_step: ThisStep | None
    if this_step_raw is None:
        this_step = None
    elif isinstance(this_step_raw, dict):
        this_step = ThisStep(
            delta_translate_x_m=float(this_step_raw.get("delta_translate_x_m", 0.0)),
            delta_translate_y_m=float(this_step_raw.get("delta_translate_y_m", 0.0)),
            delta_rotate_deg=float(this_step_raw.get("delta_rotate_deg", 0.0)),
            picked_world_x_m=float(this_step_raw.get("picked_world_x_m", 0.0)),
            picked_world_y_m=float(this_step_raw.get("picked_world_y_m", 0.0)),
        )
    else:
        raise SidecarSchemaMismatch("this_step_invalid")

    return Sidecar(
        schema=schema,
        kind=kind,
        source_pristine_pgm=_str_field(source, "pristine_pgm"),
        source_pristine_yaml=_str_field(source, "pristine_yaml"),
        lineage_generation=int(lineage.get("generation", 0)),
        lineage_parents=parents,
        lineage_kind=_str_field(lineage, "kind"),
        cumulative_from_pristine=Cumulative(
            translate_x_m=float(cumulative.get("translate_x_m", 0.0)),
            translate_y_m=float(cumulative.get("translate_y_m", 0.0)),
            rotate_deg=float(cumulative.get("rotate_deg", 0.0)),
        ),
        this_step=this_step,
        result_yaml_origin=(
            float(result_origin.get("x_m", 0.0)),
            float(result_origin.get("y_m", 0.0)),
            float(result_origin.get("yaw_deg", 0.0)),
        ),
        result_canvas=(
            int(result_canvas.get("width_px", 0)),
            int(result_canvas.get("height_px", 0)),
        ),
        pgm_sha256=_str_field(integrity, "pgm_sha256"),
        yaml_sha256=_str_field(integrity, "yaml_sha256"),
        created_iso_kst=_str_field(created, "iso_kst"),
        created_memo=str(created.get("memo", "")),
        created_reason=str(created.get("reason", "")),
    )


def _str_field(d: dict[str, object], key: str) -> str:
    val = d.get(key)
    if not isinstance(val, str):
        raise SidecarSchemaMismatch(f"{key}_missing_or_not_string")
    return val


def _dict_field(d: dict[str, object], key: str) -> dict[str, object]:
    val = d.get(key)
    if not isinstance(val, dict):
        raise SidecarSchemaMismatch(f"{key}_missing_or_not_dict")
    return val


# --- Write -----------------------------------------------------------


def write(path: Path, sc: Sidecar) -> None:
    """Atomic write of the sidecar JSON. Mirror of `map_transform`'s
    `_write_fsync` + `os.replace` discipline. Mode 0644 (operator-
    readable artifact)."""
    body = json.dumps(sc.to_dict(), sort_keys=True, indent=2, ensure_ascii=False)
    data = body.encode("utf-8")
    tmp = path.with_suffix(path.suffix + _TMP_SUFFIX)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _SIDECAR_FILE_MODE)
    try:
        with os.fdopen(fd, "wb", closefd=True) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(str(tmp))
        raise


# --- Integrity -------------------------------------------------------


def compute_sha256(path: Path) -> str:
    """Return `hashlib.sha256(path.read_bytes()).hexdigest()` over the
    on-disk bytes verbatim (no canonicalisation, per §D1 [MI1])."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_integrity(sc: Sidecar, pgm: Path, yaml: Path) -> bool:
    """True iff both PGM and YAML on-disk bytes hash to the values in
    the sidecar."""
    return compute_sha256(pgm) == sc.pgm_sha256 and compute_sha256(yaml) == sc.yaml_sha256


# --- Cumulative composition (D3 algebra) -----------------------------


_YAW_WRAP_MAX_INCL_DEG = 180.0
_YAW_WRAP_MIN_EXCL_DEG = -180.0


def _wrap_yaw_deg(value: float) -> float:
    """Wrap `value` into `(-180, 180]`. Edge case: -180 reflects to +180."""
    if not math.isfinite(value):
        return value
    span = _YAW_WRAP_MAX_INCL_DEG - _YAW_WRAP_MIN_EXCL_DEG
    shifted = (value - _YAW_WRAP_MIN_EXCL_DEG) % span
    wrapped = shifted + _YAW_WRAP_MIN_EXCL_DEG
    if wrapped == _YAW_WRAP_MIN_EXCL_DEG:
        wrapped = _YAW_WRAP_MAX_INCL_DEG
    return wrapped


def compose_cumulative(parent: Cumulative, this_step_local: ThisStep) -> Cumulative:
    """Compose a new cumulative from a parent + this Apply's typed delta.

    Per the C-2.1 round-3 lock + Q1 lock #5: the new cumulative
    `translate` is the pristine-frame world coord that lands at derived
    world (0, 0). Computed as
        cumulative.translate = picked_world − R(-θ_active)·typed_delta
    where `picked_world = (this_step_local.picked_world_x_m,
    this_step_local.picked_world_y_m)`, `typed_delta =
    (this_step_local.delta_translate_x_m, this_step_local.delta_translate_y_m)`,
    and `θ_active = parent.rotate_deg`.

    The standard 2D CCW rotation matrix is `[c -s; s c]`. R(-θ_active)
    rotates the typed-delta vector by `-θ_active` to express it in
    pristine-frame coords, since the active-at-pick frame's `+x` axis
    is pristine's `+x` rotated CCW by `θ_active`.

    `rotate_deg` accumulates additively + wraps to (-180, 180].
    """
    theta_active = math.radians(parent.rotate_deg)
    c = math.cos(-theta_active)
    s = math.sin(-theta_active)
    typed_dx = this_step_local.delta_translate_x_m
    typed_dy = this_step_local.delta_translate_y_m
    rotated_dx = c * typed_dx - s * typed_dy
    rotated_dy = s * typed_dx + c * typed_dy
    new_tx = this_step_local.picked_world_x_m - rotated_dx
    new_ty = this_step_local.picked_world_y_m - rotated_dy
    new_theta = _wrap_yaw_deg(parent.rotate_deg + this_step_local.delta_rotate_deg)
    return Cumulative(translate_x_m=new_tx, translate_y_m=new_ty, rotate_deg=new_theta)


# --- Synthesize for orphan pair --------------------------------------


def synthesize_for_orphan_pair(
    pgm: Path,
    yaml: Path,
    *,
    kind_label: str | None = None,
    created_iso_kst: str = "1970-01-01T00:00:00+09:00",
) -> Sidecar:
    """Best-effort sidecar synthesis for an orphan PGM+YAML pair (no
    sidecar JSON on disk).

    Heuristic per §D1 [MA-2.1]:
    - filename matches `<base>.YYYYMMDD-HHMMSS-<memo>` → PR #81-era
      derived: classify as `lineage.kind = auto_migrated_pre_issue30`,
      `top-level kind = derived`, `generation = 1`.
    - filename does NOT match the derived pattern → genuine
      crash-window orphan: classify as
      `top-level kind = synthesized`, `lineage.kind = synthesized`,
      `generation = -1`.

    Caller may override with `kind_label` (e.g. `"backup"`) to force a
    specific classification.
    """
    stem = pgm.stem
    is_derived_pattern = DERIVED_NAME_REGEX.match(stem) is not None
    if kind_label is not None:
        top_kind = kind_label
        lineage_kind = kind_label
        generation = 1 if is_derived_pattern else SIDECAR_GENERATION_UNKNOWN
    elif is_derived_pattern:
        top_kind = "derived"
        lineage_kind = SIDECAR_LINEAGE_KIND_AUTO_MIGRATED
        generation = 1
    else:
        top_kind = "synthesized"
        lineage_kind = SIDECAR_LINEAGE_KIND_SYNTHESIZED
        generation = SIDECAR_GENERATION_UNKNOWN

    pgm_sha = compute_sha256(pgm) if pgm.is_file() else ""
    yaml_sha = compute_sha256(yaml) if yaml.is_file() else ""

    parents: tuple[str, ...] = ()
    pristine_pgm = pgm.name
    pristine_yaml = yaml.name
    if is_derived_pattern:
        m = DERIVED_NAME_REGEX.match(stem)
        if m is not None:
            base = m.group("base")
            parents = (base,)
            pristine_pgm = f"{base}.{_PGM_EXT}"
            pristine_yaml = f"{base}.{_YAML_EXT}"

    # Best-effort YAML origin parse.
    origin_xy_yaw = (0.0, 0.0, 0.0)
    canvas = (0, 0)
    if yaml.is_file():
        with contextlib.suppress(Exception):
            origin_xy_yaw = _parse_yaml_origin(yaml.read_text("utf-8"))
    if pgm.is_file():
        with contextlib.suppress(Exception):
            canvas = _parse_pgm_dims(pgm)

    return Sidecar(
        schema=SIDECAR_SCHEMA,
        kind=top_kind,
        source_pristine_pgm=pristine_pgm,
        source_pristine_yaml=pristine_yaml,
        lineage_generation=generation,
        lineage_parents=parents,
        lineage_kind=lineage_kind,
        cumulative_from_pristine=Cumulative(0.0, 0.0, 0.0),
        this_step=None,
        result_yaml_origin=origin_xy_yaw,
        result_canvas=canvas,
        pgm_sha256=pgm_sha,
        yaml_sha256=yaml_sha,
        created_iso_kst=created_iso_kst,
        created_memo="",
        created_reason="recovery_sweep",
    )


_ORIGIN_LINE_RE = re.compile(
    r"^\s*origin\s*:\s*\[\s*([^,\]\s][^,\]]*?)\s*,\s*([^,\]\s][^,\]]*?)\s*,\s*([^,\]\s][^,\]]*?)\s*\]",
)


def _parse_yaml_origin(yaml_text: str) -> tuple[float, float, float]:
    for line in yaml_text.splitlines():
        m = _ORIGIN_LINE_RE.match(line)
        if m is not None:
            return (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    raise ValueError("origin_missing")


def _parse_pgm_dims(pgm: Path) -> tuple[int, int]:
    head = pgm.read_bytes()[:64]
    if not head.startswith(b"P5"):
        raise ValueError("not_p5")
    rest = head[2:]
    tokens: list[bytes] = []
    i = 0
    while i < len(rest) and len(tokens) < 2:
        ch = rest[i : i + 1]
        if ch in (b" ", b"\t", b"\n", b"\r"):
            i += 1
            continue
        if ch == b"#":
            while i < len(rest) and rest[i : i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        start = i
        while i < len(rest) and rest[i : i + 1] not in (b" ", b"\t", b"\n", b"\r", b"#"):
            i += 1
        tokens.append(rest[start:i])
    if len(tokens) < 2:
        raise ValueError("missing_dims")
    return (int(tokens[0]), int(tokens[1]))


# --- Recovery sweep --------------------------------------------------


@dataclass
class _SweepCounts:
    synthesized: int = 0
    auto_migrated: int = 0
    orphan_pgm_unlinked: int = 0
    orphan_yaml_unlinked: int = 0


def recovery_sweep(maps_dir: Path) -> dict[str, int]:
    """Walk `maps_dir` for orphan PGM+YAML pairs without a sidecar (and
    half-pairs missing one side), classify per §D1, and emit
    sidecar JSON / unlink as appropriate.

    Returns a dict with EXACTLY four keys: `synthesized`,
    `auto_migrated`, `orphan_pgm_unlinked`, `orphan_yaml_unlinked`.

    Idempotent: a second invocation returns all-zero counts (every
    paired PGM+YAML now has its sidecar peer)."""
    counts = _SweepCounts()
    if not maps_dir.is_dir():
        return _counts_to_dict(counts)

    # Index: stem → has_pgm, has_yaml, has_sidecar.
    by_stem: dict[str, tuple[bool, bool, bool]] = {}
    for entry in maps_dir.iterdir():
        if entry.is_symlink() or not entry.is_file():
            continue
        name = entry.name
        if name.startswith("."):
            continue
        if name.endswith(f".{_PGM_EXT}"):
            stem = name[: -len(f".{_PGM_EXT}")]
            cur = by_stem.get(stem, (False, False, False))
            by_stem[stem] = (True, cur[1], cur[2])
        elif name.endswith(f".{_YAML_EXT}"):
            stem = name[: -len(f".{_YAML_EXT}")]
            cur = by_stem.get(stem, (False, False, False))
            by_stem[stem] = (cur[0], True, cur[2])
        elif name.endswith(f".{SIDECAR_EXT}"):
            stem = name[: -len(f".{SIDECAR_EXT}")]
            cur = by_stem.get(stem, (False, False, False))
            by_stem[stem] = (cur[0], cur[1], True)

    for stem, flags in by_stem.items():
        has_pgm, has_yaml, has_sidecar = flags
        if has_sidecar:
            continue
        # Skip the active.* family.
        if stem == "active":
            continue
        pgm = maps_dir / f"{stem}.{_PGM_EXT}"
        yaml = maps_dir / f"{stem}.{_YAML_EXT}"
        sidecar_path = maps_dir / f"{stem}.{SIDECAR_EXT}"
        if has_pgm and has_yaml:
            try:
                sc = synthesize_for_orphan_pair(pgm, yaml)
                write(sidecar_path, sc)
                if sc.lineage_kind == SIDECAR_LINEAGE_KIND_AUTO_MIGRATED:
                    counts.auto_migrated += 1
                    logger.info(
                        "sidecar.recovery_sweep: synthesized auto_migrated for %s",
                        stem,
                    )
                else:
                    counts.synthesized += 1
                    logger.info(
                        "sidecar.recovery_sweep: synthesized for %s", stem,
                    )
            except OSError as e:
                logger.warning(
                    "sidecar.recovery_sweep: write_failed for %s — %s", stem, e,
                )
        elif has_pgm and not has_yaml:
            with contextlib.suppress(OSError):
                pgm.unlink()
                counts.orphan_pgm_unlinked += 1
                logger.info(
                    "sidecar.recovery_sweep: unlinked orphan_pgm %s", stem,
                )
        elif has_yaml and not has_pgm:
            with contextlib.suppress(OSError):
                yaml.unlink()
                counts.orphan_yaml_unlinked += 1
                logger.info(
                    "sidecar.recovery_sweep: unlinked orphan_yaml %s", stem,
                )

    return _counts_to_dict(counts)


def _counts_to_dict(c: _SweepCounts) -> dict[str, int]:
    return {
        "synthesized": c.synthesized,
        "auto_migrated": c.auto_migrated,
        "orphan_pgm_unlinked": c.orphan_pgm_unlinked,
        "orphan_yaml_unlinked": c.orphan_yaml_unlinked,
    }


# --- Path helpers ----------------------------------------------------


def sidecar_path_for(maps_dir: Path, name: str) -> Path:
    """Return the sidecar JSON path for `<name>` under `maps_dir`."""
    return maps_dir / f"{name}.{SIDECAR_EXT}"
