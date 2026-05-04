"""
issue#30 — Sole-owner module for pick-anchored PGM transform + derived-pair emission.

See https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.transform

Behaviour contract (locked in `.claude/memory/project_pick_anchored_yaml_normalization_locked.md`):

- ALWAYS reads from the **pristine** baseline `<base>.{pgm,yaml}`. Never
  transforms a previously-derived PGM. This guarantees quality loss is
  exactly one BICUBIC resample regardless of how many times the
  operator iterates on the calibration (1× resample invariant).
- **Pick-anchored + canvas-expand semantic** (replaces PR #81 SUBTRACT):
  the operator's picked pristine pixel becomes the new world (0, 0);
  the bitmap rotates around that pivot by `-θ` (Pillow output→input
  convention); the canvas grows just enough to absorb rotation overhang.
  Derived YAML's `origin` lands at `[-i_p'·res, -(H_d-1-j_p')·res, 0]`
  so AMCL maps world (0, 0) to the picked pixel.
- Pristine YAML yaw `oθ_p` MAY be non-zero (e.g. live `test_v4.yaml`
  carries 1.604 rad ≈ 91.9°). It is read for world↔pixel transforms
  via `pristine_world_to_pixel` but is NOT propagated into the
  cumulative `rotate_deg` (which is operator-typed-θ accumulation only).
- 3-class re-quantise after resample so the output PGM contains only
  the canonical `{0, 205, 254}` values (occupied / unknown / free).
- Atomic C3-triple write protocol: PGM tmp → YAML tmp → JSON tmp →
  fsync all → fsync dir → rename PGM → rename YAML → rename JSON →
  fsync dir; cascade rollback on graceful failure (later commits
  unlink earlier ones so the operator never sees a half-committed
  set).
- Helper-injection: `_TransformDeps` mirrors the old `_RotateDeps`
  pattern. Production binds real Pillow + `time.monotonic` + `now_kst`;
  tests inject deterministic fakes.

Math contract (Step 1–5, derivation in §"D4" of the issue#30 plan):

Inputs:
- `(W_p, H_p)` — pristine bitmap dimensions (px).
- `res` — resolution in m/px (positive).
- `(ox_p, oy_p, oθ_p)` — pristine YAML origin: world coord of pristine's
  bottom-left pixel + bottom-left-pixel yaw. `oθ_p` may be non-zero.
- `(cum_tx, cum_ty)` — `cumulative_from_pristine.translate` in m
  (pristine-frame world coord that lands at derived world (0, 0)). The
  caller has already absorbed any operator-typed delta upstream via
  `compose_cumulative` in `sidecar.py`.
- `θ` — `cumulative_from_pristine.rotate_deg` in deg (typed-θ
  accumulation only; does NOT include `oθ_p`).

Convention pins:
- `j_p`, `j_p'` are **row-from-top** (Pillow convention).
- ROS YAML origin is **row-from-bottom**. The Y-flip from row-from-top
  to row-from-bottom is applied **only in Step 5**.
- Rotation sign: `+θ` = CCW in operator's world view. Bitmap content
  rotates by `-θ` (Pillow output→input convention).

Step 1: Bitmap pivot pixel — yaw-aware via `pristine_world_to_pixel`.
Step 2: Off-center bbox by rotating four pristine corners around
        `(i_p, j_p_top)` by `-θ`. Take floor(min) / ceil(max) → `(W_d, H_d)`.
Step 3: Picked-point's NEW pixel: `i_p' = i_p - x_min`, `j_p' = j_p_top - y_min`.
Step 4: Pillow AFFINE matrix (output → input convention). See
        `_affine_matrix_for_pivot_rotation` for the derivation.
Step 5: Derived YAML origin (Y-flip):
        `new_origin_x_m = -i_p' · res`
        `new_origin_y_m = -((H_d - 1) - j_p') · res`
        `new_origin_yaw_deg = 0.0`

The pristine pair on disk is byte-identically immutable across the
call.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import math
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .constants import (
    LANCZOS_FILTER_NAME,
    MAP_ROTATE_MAX_CANVAS_PX,
    MAP_ROTATE_THRESH_FREE,
    MAP_ROTATE_THRESH_OCC,
    MAP_ROTATE_THRESH_UNK,
    MAP_ROTATE_TIME_BUDGET_S,
    PGM_HEADER_MAX_BYTES,
    SIDECAR_LINEAGE_KIND_OPERATOR,
    SIDECAR_SCHEMA,
)

logger = logging.getLogger("godo_webctl.map_transform")

# File modes mirror map_edit.py / map_origin.py.
_PAIR_FILE_MODE = 0o644
_TMP_SUFFIX = ".tmp"

# Re-quantise mid-thresholds. 3-class output is what slam_toolbox /
# map_server produces; AMCL's likelihood field cares about the
# obstacle/non-obstacle split at OCCUPIED_CUTOFF_U8 = 100 (see
# production/RPi5/src/localization/occupancy_grid.hpp).
_REQUANT_OCC_LE = 64    # <=  → occupied (0)
_REQUANT_FREE_GE = 224  # >= → free (254); else unknown (205)


# --- Errors ------------------------------------------------------------


class RotateError(Exception):
    """Base for map_transform-module exceptions. Name preserved from the
    pre-issue#30 `map_rotate.py` for identifiability across the rename."""


class PristineMissing(RotateError):
    """Pristine PGM/YAML pair does not exist."""


class CanvasTooLarge(RotateError):
    """Transform produces a canvas exceeding `MAP_ROTATE_MAX_CANVAS_PX`."""


class RotateBudgetExceeded(RotateError):
    """Per-call wall-clock budget exceeded mid-transform."""


class PgmHeaderInvalid(RotateError):
    """Pristine PGM lacks a valid P5 header, or pristine YAML cannot be
    parsed for `origin:` / `resolution:`."""


class PairWriteFailed(RotateError):
    """Atomic write failed (PGM, YAML, or JSON rename failure)."""


# --- Data classes ----------------------------------------------------


@dataclass(frozen=True)
class Cumulative:
    """`cumulative_from_pristine` algebra subject — pristine-frame world
    coord that lands at derived world (0, 0), plus typed-θ accumulation
    in degrees. Composes associatively via `sidecar.compose_cumulative`."""

    translate_x_m: float
    translate_y_m: float
    rotate_deg: float


@dataclass(frozen=True)
class ThisStep:
    """Operator's typed delta + the absolute world coord of the picked
    point in the active-at-pick frame. Recorded in the sidecar so the
    Apply can be replayed from logs without the cumulative state."""

    delta_translate_x_m: float
    delta_translate_y_m: float
    delta_rotate_deg: float
    picked_world_x_m: float
    picked_world_y_m: float


@dataclass(frozen=True)
class TransformResult:
    """Returned by `transform_pristine_to_derived` on success."""

    derived_pgm: Path
    derived_yaml: Path
    derived_sidecar: Path
    new_width_px: int
    new_height_px: int
    new_yaml_origin_xy_yaw: tuple[float, float, float]
    pgm_sha256: str
    yaml_sha256: str


class _ImageModule(Protocol):
    """Subset of `PIL.Image` we use (helper-injection seam)."""

    Resampling: object
    Transform: object
    LANCZOS: int

    def open(self, fp: object) -> object: ...  # noqa: D401
    def new(self, mode: str, size: tuple[int, int], color: int) -> object: ...


@dataclass(frozen=True)
class _TransformDeps:
    image_mod: _ImageModule
    monotonic: Callable[[], float]
    now_kst_iso: Callable[[], str]


def _default_deps() -> _TransformDeps:
    """Bind real Pillow + `time.monotonic` + `kst_iso_seconds`."""
    import time as _time

    from PIL import Image as _PilImage

    from .timestamps import kst_iso_seconds

    return _TransformDeps(
        image_mod=_PilImage,
        monotonic=_time.monotonic,
        now_kst_iso=kst_iso_seconds,
    )


# --- Public yaw-aware world↔pixel SSOT ------------------------------


def pristine_world_to_pixel(
    cum_tx: float,
    cum_ty: float,
    ox_p: float,
    oy_p: float,
    otheta_p: float,
    W_p: int,  # noqa: N803
    H_p: int,  # noqa: N803
    res: float,
) -> tuple[float, float]:
    """Convert pristine-frame cumulative-translate world coord to
    pristine bitmap pixel `(i_p, j_p_top)` (column-from-left,
    row-from-top).

    `cum_tx, cum_ty` is `cumulative_from_pristine.translate` (NOT raw
    `picked_world` — the caller has absorbed any typed delta upstream
    via `sidecar.compose_cumulative`).

    When `otheta_p == 0` this collapses to the simple form
        `i_p = (cum_tx - ox_p) / res`
        `j_p_top = H_p - 1 - (cum_ty - oy_p) / res`

    SSOT: this function lives in `map_transform.py` (Python) AND
    `originMath.ts` (TypeScript). Mirror tests pin them to bit-identical
    outputs across yaw ∈ {0, 0.5, 1.604, π/2, π, -π/3}.
    """
    dx = cum_tx - ox_p
    dy = cum_ty - oy_p
    c = math.cos(-otheta_p)
    s = math.sin(-otheta_p)
    local_x = c * dx - s * dy
    local_y = s * dx + c * dy
    i_p = local_x / res
    j_p_top = (H_p - 1) - local_y / res
    return i_p, j_p_top


# --- Public API ------------------------------------------------------


def transform_pristine_to_derived(  # noqa: C901, PLR0912, PLR0913, PLR0915
    pristine_pgm: Path,
    pristine_yaml: Path,
    derived_pgm: Path,
    derived_yaml: Path,
    derived_sidecar: Path,
    cumulative_from_pristine: Cumulative,
    this_step: ThisStep,
    parent_lineage: list[str],
    *,
    deps: _TransformDeps | None = None,
    memo: str = "",
    reason: str = "operator_apply",
) -> TransformResult:
    """Pick-anchored bitmap transform + derived-triple emission.

    See module docstring for the math contract (Steps 1-5).

    Raises `PristineMissing`, `CanvasTooLarge`, `RotateBudgetExceeded`,
    `PgmHeaderInvalid`, `PairWriteFailed`.
    """
    deps = deps or _default_deps()
    deadline = deps.monotonic() + MAP_ROTATE_TIME_BUDGET_S

    if not pristine_pgm.is_file() or not pristine_yaml.is_file():
        raise PristineMissing(str(pristine_pgm))

    # 1. Load pristine PGM via Pillow.
    try:
        with pristine_pgm.open("rb") as f:
            head = f.read(PGM_HEADER_MAX_BYTES)
        if not head.startswith(b"P5"):
            raise PgmHeaderInvalid("missing_p5_magic")
        img = deps.image_mod.open(str(pristine_pgm))  # type: ignore[arg-type]
        img.load()
    except OSError as e:
        raise PgmHeaderInvalid(f"pgm_open_failed: {e}") from e

    if img.mode != "L":
        img = img.convert("L")

    src_w, src_h = img.size

    # 1a. Parse pristine YAML for origin (ox_p, oy_p, oθ_p) + resolution.
    pristine_yaml_text = pristine_yaml.read_text("utf-8")
    ox_p, oy_p, otheta_p, res = _parse_pristine_yaml_origin_resolution(pristine_yaml_text)

    # 1b. Bitmap pivot pixel via yaw-aware world→pixel.
    i_p, j_p = pristine_world_to_pixel(
        cumulative_from_pristine.translate_x_m,
        cumulative_from_pristine.translate_y_m,
        ox_p,
        oy_p,
        otheta_p,
        src_w,
        src_h,
        res,
    )

    theta_deg = cumulative_from_pristine.rotate_deg
    theta_rad = math.radians(theta_deg)

    # 2. Off-center bbox.
    x_min, y_min, x_max, y_max = _off_center_bbox(src_w, src_h, i_p, j_p, theta_rad)
    new_w = x_max - x_min
    new_h = y_max - y_min

    if max(new_w, new_h) > MAP_ROTATE_MAX_CANVAS_PX:
        raise CanvasTooLarge(
            f"new_canvas={new_w}x{new_h} > cap={MAP_ROTATE_MAX_CANVAS_PX}",
        )

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("expand_canvas")

    # 3. Picked-point's NEW pixel.
    i_p_new = i_p - x_min
    j_p_new = j_p - y_min

    # 4. Pillow AFFINE matrix (output → input).
    # Pass `-theta_rad` (NOT `+theta_rad`) so the matrix matches the
    # `_off_center_bbox`'s `-theta_rad` corner rotation: both pieces
    # now describe a visual CW rotation of the bitmap by θ, which is
    # the Q2 lock semantic for operator-typed +θ (world frame rotates
    # +θ CCW → bitmap content rotates -θ CW). The historical `+theta_rad`
    # call produced a visual CCW rotation disagreeing with the bbox's
    # CW-sized canvas (PR #84 HIL Finding 1, 2026-05-05 KST).
    affine = _affine_matrix_for_pivot_rotation(i_p, j_p, x_min, y_min, -theta_rad)

    resample = _resolve_transform_filter(deps.image_mod)
    transformed = img.transform(
        (new_w, new_h),
        _resolve_affine_transform(deps.image_mod),
        affine,
        resample=resample,
        fillcolor=MAP_ROTATE_THRESH_UNK,
    )
    actual_w, actual_h = transformed.size
    if max(actual_w, actual_h) > MAP_ROTATE_MAX_CANVAS_PX:
        raise CanvasTooLarge(
            f"actual_canvas={actual_w}x{actual_h} > cap={MAP_ROTATE_MAX_CANVAS_PX}",
        )

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("transform_call")

    # 4a. 3-class re-quantise.
    quantised_bytes = _three_class_quantise(transformed.tobytes())

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("requantise")

    # 5. Compose derived YAML origin.
    new_origin_x_m = -i_p_new * res
    new_origin_y_m = -((actual_h - 1) - j_p_new) * res
    new_origin_yaw_deg = 0.0

    # 5a. Compose derived YAML body.
    new_yaml_text = _rewrite_origin_line(
        pristine_yaml_text,
        new_origin_x_m,
        new_origin_y_m,
        math.radians(new_origin_yaw_deg),
    )

    # 6. Build the derived PGM body.
    pgm_bytes = _build_p5_bytes(actual_w, actual_h, quantised_bytes)
    yaml_bytes = new_yaml_text.encode("utf-8")

    # 7. SHAs.
    pgm_sha = hashlib.sha256(pgm_bytes).hexdigest()
    yaml_sha = hashlib.sha256(yaml_bytes).hexdigest()

    # 8. Build the sidecar JSON body.
    sidecar_body = _build_sidecar_json(
        kind="derived",
        source_pristine_pgm=pristine_pgm.name,
        source_pristine_yaml=pristine_yaml.name,
        lineage_generation=len(parent_lineage),
        lineage_parents=tuple(parent_lineage),
        lineage_kind=SIDECAR_LINEAGE_KIND_OPERATOR,
        cumulative=cumulative_from_pristine,
        this_step=this_step,
        result_yaml_origin=(new_origin_x_m, new_origin_y_m, new_origin_yaw_deg),
        result_canvas=(actual_w, actual_h),
        pgm_sha=pgm_sha,
        yaml_sha=yaml_sha,
        created_iso_kst=deps.now_kst_iso(),
        memo=memo,
        reason=reason,
    )
    sidecar_bytes = sidecar_body.encode("utf-8")

    # 9. Atomic C3-triple write.
    _atomic_write_triple(
        derived_pgm,
        derived_yaml,
        derived_sidecar,
        pgm_bytes,
        yaml_bytes,
        sidecar_bytes,
    )

    return TransformResult(
        derived_pgm=derived_pgm,
        derived_yaml=derived_yaml,
        derived_sidecar=derived_sidecar,
        new_width_px=actual_w,
        new_height_px=actual_h,
        new_yaml_origin_xy_yaw=(new_origin_x_m, new_origin_y_m, new_origin_yaw_deg),
        pgm_sha256=pgm_sha,
        yaml_sha256=yaml_sha,
    )


# --- Maths -----------------------------------------------------------


def _off_center_bbox(
    width: int,
    height: int,
    i_p: float,
    j_p: float,
    theta_rad: float,
) -> tuple[int, int, int, int]:
    """Compute the bounding box `(x_min, y_min, x_max, y_max)` of the
    pristine bitmap's four corners after rotating around `(i_p, j_p)`
    by `-theta_rad`."""
    c = math.cos(-theta_rad)
    s = math.sin(-theta_rad)
    corners = [
        (0.0, 0.0),
        (float(width), 0.0),
        (0.0, float(height)),
        (float(width), float(height)),
    ]
    xs: list[float] = []
    ys: list[float] = []
    for x, y in corners:
        dx = x - i_p
        dy = y - j_p
        xs.append(i_p + c * dx - s * dy)
        ys.append(j_p + s * dx + c * dy)
    return (
        math.floor(min(xs)),
        math.floor(min(ys)),
        math.ceil(max(xs)),
        math.ceil(max(ys)),
    )


def _affine_matrix_for_pivot_rotation(
    i_p: float,
    j_p: float,
    x_min: int,
    y_min: int,
    theta_rad: float,
) -> tuple[float, float, float, float, float, float]:
    """Build Pillow's `Image.Transform.AFFINE` coefficient tuple
    `(a, b, c, d, e, f)` for output→input mapping `p = a·u + b·v + c,
    q = d·u + e·v + f`. See module docstring for derivation."""
    cos_t = math.cos(theta_rad)
    sin_t = math.sin(theta_rad)
    a = cos_t
    b = -sin_t
    c = i_p + cos_t * (x_min - i_p) - sin_t * (y_min - j_p)
    d = sin_t
    e = cos_t
    f = j_p + sin_t * (x_min - i_p) + cos_t * (y_min - j_p)
    return a, b, c, d, e, f


def _three_class_quantise(pixel_bytes: bytes) -> bytes:
    """Re-quantise an L-mode byte buffer to {0, 205, 254}."""
    occ = MAP_ROTATE_THRESH_OCC
    unk = MAP_ROTATE_THRESH_UNK
    free = MAP_ROTATE_THRESH_FREE
    out = bytearray(len(pixel_bytes))
    for i, v in enumerate(pixel_bytes):
        if v <= _REQUANT_OCC_LE:
            out[i] = occ
        elif v >= _REQUANT_FREE_GE:
            out[i] = free
        else:
            out[i] = unk
    return bytes(out)


def _build_p5_bytes(width: int, height: int, body: bytes) -> bytes:
    """Compose a netpbm P5 PGM byte stream. Maxval is fixed at 255."""
    header = f"P5\n{width} {height}\n255\n".encode("ascii")
    return header + body


def _resolve_transform_filter(image_mod: _ImageModule) -> int:
    """Return the resample filter id for `Image.transform`."""
    resampling = getattr(image_mod, "Resampling", None)
    if resampling is not None:
        candidate = getattr(resampling, "BICUBIC", None)
        if candidate is not None:
            return int(candidate)
    return int(getattr(image_mod, "BICUBIC", 3))


def _resolve_affine_transform(image_mod: _ImageModule) -> int:
    """Return the AFFINE transform method id for `Image.transform`."""
    transform_enum = getattr(image_mod, "Transform", None)
    if transform_enum is not None:
        candidate = getattr(transform_enum, "AFFINE", None)
        if candidate is not None:
            return int(candidate)
    return int(getattr(image_mod, "AFFINE", 0))


# --- YAML rewrite (origin line only) --------------------------------


def _rewrite_origin_line(
    yaml_text: str, new_x: float, new_y: float, new_theta_rad: float,
) -> str:
    """Rewrite the unique flow-style `origin: [x, y, theta]` line."""
    from .map_origin import _find_unique_origin_line, _line_ending_of

    lines_with_ends = yaml_text.splitlines(keepends=True)
    origin_idx, m = _find_unique_origin_line(lines_with_ends)
    leading = m.group(1)
    after_colon_ws = m.group(2)
    inside_lead_ws = m.group(3)
    xy_sep = m.group(5)
    y_theta_sep = m.group(7)
    inside_trail_ws = m.group(9)
    tail = m.group(10)
    new_line_ending = _line_ending_of(lines_with_ends[origin_idx])
    new_line = (
        f"{leading}{after_colon_ws}["
        f"{inside_lead_ws}{repr(new_x)}{xy_sep}{repr(new_y)}{y_theta_sep}{repr(new_theta_rad)}"
        f"{inside_trail_ws}]{tail}{new_line_ending}"
    )
    new_lines = list(lines_with_ends)
    new_lines[origin_idx] = new_line
    return "".join(new_lines)


def _parse_pristine_yaml_origin_resolution(
    yaml_text: str,
) -> tuple[float, float, float, float]:
    """Parse `origin: [x, y, theta]` + `resolution:` out of pristine YAML.
    Returns `(ox, oy, otheta, res)`. Raises `PgmHeaderInvalid` on
    malformed input."""
    from .map_origin import _find_unique_origin_line

    try:
        lines_with_ends = yaml_text.splitlines(keepends=True)
        _, m = _find_unique_origin_line(lines_with_ends)
        ox = float(m.group(4))
        oy = float(m.group(6))
        otheta = float(m.group(8))
    except Exception as e:  # noqa: BLE001
        raise PgmHeaderInvalid(f"pristine_yaml_origin_parse_failed: {e}") from e

    res: float | None = None
    for line in yaml_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("resolution"):
            continue
        _, _, rhs = stripped.partition(":")
        rhs = rhs.strip()
        if "#" in rhs:
            rhs = rhs.split("#", 1)[0].strip()
        try:
            res = float(rhs)
            break
        except ValueError:
            continue
    if res is None or res <= 0:
        raise PgmHeaderInvalid(f"pristine_yaml_resolution_missing_or_invalid: {res!r}")
    return ox, oy, otheta, res


# --- Sidecar JSON composition ----------------------------------------


def _build_sidecar_json(  # noqa: PLR0913
    *,
    kind: str,
    source_pristine_pgm: str,
    source_pristine_yaml: str,
    lineage_generation: int,
    lineage_parents: tuple[str, ...],
    lineage_kind: str,
    cumulative: Cumulative,
    this_step: ThisStep | None,
    result_yaml_origin: tuple[float, float, float],
    result_canvas: tuple[int, int],
    pgm_sha: str,
    yaml_sha: str,
    created_iso_kst: str,
    memo: str,
    reason: str,
) -> str:
    """Compose the v1 sidecar JSON body."""
    body: dict[str, object] = {
        "schema": SIDECAR_SCHEMA,
        "kind": kind,
        "source": {
            "pristine_pgm": source_pristine_pgm,
            "pristine_yaml": source_pristine_yaml,
        },
        "lineage": {
            "generation": lineage_generation,
            "parents": list(lineage_parents),
            "kind": lineage_kind,
        },
        "cumulative_from_pristine": {
            "translate_x_m": cumulative.translate_x_m,
            "translate_y_m": cumulative.translate_y_m,
            "rotate_deg": cumulative.rotate_deg,
        },
        "result_yaml_origin": {
            "x_m": result_yaml_origin[0],
            "y_m": result_yaml_origin[1],
            "yaw_deg": result_yaml_origin[2],
        },
        "result_canvas": {
            "width_px": result_canvas[0],
            "height_px": result_canvas[1],
        },
        "integrity": {
            "pgm_sha256": pgm_sha,
            "yaml_sha256": yaml_sha,
        },
        "created": {
            "iso_kst": created_iso_kst,
            "memo": memo,
            "reason": reason,
        },
    }
    if this_step is not None:
        body["this_step"] = {
            "delta_translate_x_m": this_step.delta_translate_x_m,
            "delta_translate_y_m": this_step.delta_translate_y_m,
            "delta_rotate_deg": this_step.delta_rotate_deg,
            "picked_world_x_m": this_step.picked_world_x_m,
            "picked_world_y_m": this_step.picked_world_y_m,
        }
    else:
        body["this_step"] = None
    return json.dumps(body, sort_keys=True, indent=2, ensure_ascii=False)


# --- Atomic triple-write (C3 protocol extended) ---------------------


def _atomic_write_triple(  # noqa: PLR0913
    pgm_target: Path,
    yaml_target: Path,
    json_target: Path,
    pgm_bytes: bytes,
    yaml_bytes: bytes,
    json_bytes: bytes,
) -> None:
    """C3-triple lock with cascade rollback: PGM tmp → YAML tmp → JSON
    tmp → fsync all → fsync dir → rename PGM → rename YAML → rename
    JSON → fsync dir.

    Cascade rollback on graceful failure: YAML rename failure unlinks
    the PGM; JSON rename failure unlinks both PGM and YAML."""
    pgm_tmp = pgm_target.with_suffix(pgm_target.suffix + _TMP_SUFFIX)
    yaml_tmp = yaml_target.with_suffix(yaml_target.suffix + _TMP_SUFFIX)
    json_tmp = json_target.with_suffix(json_target.suffix + _TMP_SUFFIX)
    parent = pgm_target.parent

    pgm_committed = False
    yaml_committed = False

    try:
        _write_fsync(pgm_tmp, pgm_bytes)
        _write_fsync(yaml_tmp, yaml_bytes)
        _write_fsync(json_tmp, json_bytes)
        _fsync_dir(parent)
        os.replace(str(pgm_tmp), str(pgm_target))
        pgm_committed = True
        try:
            os.replace(str(yaml_tmp), str(yaml_target))
            yaml_committed = True
        except OSError as e:
            with contextlib.suppress(OSError):
                os.unlink(str(pgm_target))
            raise PairWriteFailed(f"yaml_rename_failed: {e}") from e
        try:
            os.replace(str(json_tmp), str(json_target))
        except OSError as e:
            with contextlib.suppress(OSError):
                os.unlink(str(pgm_target))
            with contextlib.suppress(OSError):
                os.unlink(str(yaml_target))
            raise PairWriteFailed(f"json_rename_failed: {e}") from e
        _fsync_dir(parent)
    except PairWriteFailed:
        raise
    except OSError as e:
        if yaml_committed:
            with contextlib.suppress(OSError):
                os.unlink(str(yaml_target))
        if pgm_committed:
            with contextlib.suppress(OSError):
                os.unlink(str(pgm_target))
        raise PairWriteFailed(f"triple_write_failed: {e}") from e
    finally:
        for tmp in (pgm_tmp, yaml_tmp, json_tmp):
            with contextlib.suppress(OSError):
                if tmp.exists():
                    os.unlink(str(tmp))


def _write_fsync(target: Path, data: bytes) -> None:
    """Open + write + fsync + close. Mode 0644."""
    fd = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PAIR_FILE_MODE)
    try:
        with os.fdopen(fd, "wb", closefd=True) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(str(target))
        raise


def _fsync_dir(path: Path) -> None:
    """Best-effort directory fsync."""
    try:
        dfd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        with contextlib.suppress(OSError):
            os.fsync(dfd)
    finally:
        os.close(dfd)


# --- Stale-tmp sweep -------------------------------------------------


def sweep_stale_tmp(maps_dir: Path) -> int:
    """Remove leftover `*.tmp` files. Idempotent."""
    swept = 0
    for stale in maps_dir.glob(f"*{_TMP_SUFFIX}"):
        try:
            stale.unlink()
            swept += 1
        except OSError as e:
            logger.warning("map_transform.sweep_failed: %s — %s", stale, e)
    return swept


# Marker — preserves the legacy `LANCZOS` constant export so existing
# import sites compile.
_LANCZOS_FILTER_NAME_MARKER: str = LANCZOS_FILTER_NAME
