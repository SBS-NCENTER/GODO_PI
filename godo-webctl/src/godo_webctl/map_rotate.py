"""
issue#28 — Sole-owner module for PGM rotation + derived-pair emission.

Behaviour contract (locked in `.claude/memory/project_map_edit_origin_rotation.md`):

- ALWAYS reads from the **pristine** baseline `<base>.{pgm,yaml}`. Never
  rotates a previously-derived PGM. This guarantees quality loss is
  exactly one Lanczos resample regardless of how many times the
  operator iterates on the calibration.
- Compose order: **translate-FIRST, rotate-SECOND** in world frame —
  apply the SUBTRACT origin shift to the YAML metadata, then rotate
  the PGM bitmap by `-typed_yaw_deg` around the post-shift origin.
- Resample kernel: Pillow's `Image.rotate` only accepts NEAREST,
  BILINEAR, and BICUBIC (LANCZOS is `resize`-only). We use BICUBIC,
  which is the closest visual match to Lanczos-3 for the rotate
  operation. The 3-class re-quantise pass below absorbs the small
  edge-pixel difference vs. a true Lanczos-3 pipeline. Constant
  `LANCZOS_FILTER_NAME` is retained for forward-compat: a future
  resize-based rotation pipeline (rotate-then-downsample to a target
  cell size) would consume the LANCZOS kernel.
- 3-class re-quantise after resample so the output PGM contains only
  the canonical `{0, 205, 254}` values the AMCL likelihood field
  expects (occupied / unknown / free).
- Auto-canvas-expand: rotation-by-θ on a `W×H` map needs a
  `|W·cosθ|+|H·sinθ| × |W·sinθ|+|H·cosθ|` canvas to avoid clipping.
  We grow the canvas to that bbox; failure mode is a cap at
  `MAP_ROTATE_MAX_CANVAS_PX` per side (raises `CanvasTooLarge`).
- Atomic pair-write protocol (C3 lock): PGM tmp → YAML tmp → fsync
  both → fsync dir → rename PGM → rename YAML → fsync dir; on YAML
  failure the PGM tmp/final is unlinked.
- Helper-injection: the Pillow `Image` module and `time.monotonic` are
  injected via `_RotateDeps` so unit tests can swap in a deterministic
  fake without monkey-patching the global Pillow import.

The pristine pair on disk is byte-identically immutable across the
call. A `θ=0` rotation produces a derived pair byte-identical to the
pristine PGM (sanity pin in tests).
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .constants import (
    LANCZOS_FILTER_NAME,
    MAP_ROTATE_MAX_CANVAS_PX,
    MAP_ROTATE_THRESH_FREE,
    MAP_ROTATE_THRESH_OCC,
    MAP_ROTATE_THRESH_UNK,
    MAP_ROTATE_TIME_BUDGET_S,
    PGM_HEADER_MAX_BYTES,
)

logger = logging.getLogger("godo_webctl.map_rotate")

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
    """Base for map_rotate-module exceptions."""


class PristineMissing(RotateError):
    """Pristine PGM/YAML pair does not exist."""


class CanvasTooLarge(RotateError):
    """Rotation produces a canvas exceeding `MAP_ROTATE_MAX_CANVAS_PX`."""


class RotateBudgetExceeded(RotateError):
    """Per-call wall-clock budget exceeded mid-rotation."""


class PgmHeaderInvalid(RotateError):
    """Pristine PGM lacks a valid P5 header."""


class PairWriteFailed(RotateError):
    """Atomic pair-write failed (PGM or YAML rename failure)."""


# --- Result + injection seam -----------------------------------------


@dataclass(frozen=True)
class RotateResult:
    derived_pgm: Path
    derived_yaml: Path
    new_width_px: int
    new_height_px: int


class _ImageModule(Protocol):
    """Subset of `PIL.Image` we use. Defined for helper-injection
    testability — production binds `_default_deps()` to the real
    Pillow import."""

    Resampling: object  # PIL.Image.Resampling
    LANCZOS: int  # legacy constant (kept as fallback)

    def open(self, fp: object) -> object: ...  # noqa: D401 — protocol stub
    def new(self, mode: str, size: tuple[int, int], color: int) -> object: ...


@dataclass(frozen=True)
class _RotateDeps:
    image_mod: _ImageModule
    monotonic: Callable[[], float]


def _default_deps() -> _RotateDeps:
    """Bind real Pillow + `time.monotonic`. Localised import keeps the
    module importable without Pillow (matches `map_edit.py`)."""
    import time as _time

    from PIL import Image as _PilImage

    return _RotateDeps(image_mod=_PilImage, monotonic=_time.monotonic)


# --- Public API ------------------------------------------------------


def rotate_pristine_to_derived(
    pristine_pgm: Path,
    pristine_yaml: Path,
    derived_pgm: Path,
    derived_yaml: Path,
    yaml_text_with_new_origin: str,
    typed_yaw_deg: float,
    *,
    deps: _RotateDeps | None = None,
) -> RotateResult:
    """Rotate the pristine PGM by ``-typed_yaw_deg`` (world-frame:
    operator's typed +θ rotates the world; the bitmap rotates by −θ)
    and emit a derived `<base>.YYYYMMDD-HHMMSS-<memo>.{pgm,yaml}` pair.

    The caller (app.py) owns:
        - resolving pristine + derived paths via `maps.derive_name`
        - computing the post-SUBTRACT YAML text via
          `map_origin.apply_origin_edit_in_memory` (this module never
          rewrites YAML byte sequences itself)
        - invoking us under the `asyncio.Lock` and SSE progress emitter

    `yaml_text_with_new_origin` is the COMPLETE post-SUBTRACT YAML
    body bytes-as-str; this module only writes that to the derived
    YAML path under the atomic pair-write protocol.

    Returns ``RotateResult`` with the derived pair paths + final
    canvas dimensions.

    Raises `PristineMissing`, `CanvasTooLarge`, `RotateBudgetExceeded`,
    `PgmHeaderInvalid`, `PairWriteFailed`.
    """
    deps = deps or _default_deps()
    deadline = deps.monotonic() + MAP_ROTATE_TIME_BUDGET_S

    if not pristine_pgm.is_file() or not pristine_yaml.is_file():
        raise PristineMissing(str(pristine_pgm))

    # 1. Load pristine PGM via Pillow. Pillow handles P5 natively.
    try:
        with pristine_pgm.open("rb") as f:
            head = f.read(PGM_HEADER_MAX_BYTES)
        if not head.startswith(b"P5"):
            raise PgmHeaderInvalid("missing_p5_magic")
        img = deps.image_mod.open(str(pristine_pgm))  # type: ignore[arg-type]
        # Force decode now so corrupt files raise here, not lazily.
        img.load()
    except OSError as e:
        raise PgmHeaderInvalid(f"pgm_open_failed: {e}") from e

    if img.mode != "L":
        img = img.convert("L")

    src_w, src_h = img.size

    # 2. Auto-canvas-expand bbox (covers any θ; 0° → identity).
    new_w, new_h = _expanded_canvas(src_w, src_h, typed_yaw_deg)
    if max(new_w, new_h) > MAP_ROTATE_MAX_CANVAS_PX:
        raise CanvasTooLarge(
            f"new_canvas={new_w}x{new_h} > cap={MAP_ROTATE_MAX_CANVAS_PX}",
        )

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("expand_canvas")

    # 3. Rotate. expand=True grows to the bbox we just predicted; we
    # pass the resampled value via the canonical Pillow ≥ 10 enum if
    # available, falling back to the legacy `Image.LANCZOS` int for
    # pre-10 envs.
    resample = _resolve_rotate_filter(deps.image_mod)
    # `fillcolor=MAP_ROTATE_THRESH_UNK` (205): freshly exposed pixels
    # outside the source bbox are "unknown" — not "free", which would
    # invent passable cells the operator never saw, and not "occupied",
    # which would brick the AMCL likelihood field with phantom walls.
    # HIL fix 2026-05-04 KST: pass `-typed_yaw_deg` per the module
    # docstring intent. Operator's typed +θ means "rotate the world
    # frame by +θ"; equivalently, the bitmap content rotates by -θ
    # relative to the source so that a wall at +θ in pristine ends up
    # at 0° (the new +x) in derived. Pillow's positive `angle` parameter
    # rotates content visually CCW; we want CW so the picked direction
    # becomes horizontal — hence the negation.
    rotated = img.rotate(
        -typed_yaw_deg,
        resample=resample,
        expand=True,
        fillcolor=MAP_ROTATE_THRESH_UNK,
    )
    rotated_w, rotated_h = rotated.size
    # Pillow's `expand=True` may produce a slightly different size from
    # our predicted bbox by ±1 px (rounding); accept the actual size as
    # the truth and re-cap it.
    if max(rotated_w, rotated_h) > MAP_ROTATE_MAX_CANVAS_PX:
        raise CanvasTooLarge(
            f"actual_canvas={rotated_w}x{rotated_h} > cap={MAP_ROTATE_MAX_CANVAS_PX}",
        )

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("rotate_call")

    # 4. 3-class re-quantise so the output is only {0, 205, 254}.
    quantised_bytes = _three_class_quantise(rotated.tobytes())

    if deps.monotonic() > deadline:
        raise RotateBudgetExceeded("requantise")

    # 5. Build the derived PGM body.
    pgm_bytes = _build_p5_bytes(rotated_w, rotated_h, quantised_bytes)

    # 6. Atomic pair-write — C3 protocol. PGM → YAML → fsyncs → renames.
    _atomic_write_pair(
        derived_pgm,
        derived_yaml,
        pgm_bytes,
        yaml_text_with_new_origin.encode("utf-8"),
    )

    return RotateResult(
        derived_pgm=derived_pgm,
        derived_yaml=derived_yaml,
        new_width_px=rotated_w,
        new_height_px=rotated_h,
    )


# --- Maths -----------------------------------------------------------


def _expanded_canvas(width: int, height: int, theta_deg: float) -> tuple[int, int]:
    """Predict the post-rotate canvas size needed to contain the source
    rectangle without clipping, mirror of Pillow's `expand=True` logic
    (accepts ±1 px disagreement)."""
    theta_rad = math.radians(theta_deg)
    c = abs(math.cos(theta_rad))
    s = abs(math.sin(theta_rad))
    new_w = int(math.ceil(width * c + height * s))
    new_h = int(math.ceil(width * s + height * c))
    return new_w, new_h


def _three_class_quantise(rgba_bytes: bytes) -> bytes:
    """Re-quantise an L-mode byte buffer to {0, 205, 254}. Pure byte-
    level operation; no Pillow dependency."""
    occ = MAP_ROTATE_THRESH_OCC
    unk = MAP_ROTATE_THRESH_UNK
    free = MAP_ROTATE_THRESH_FREE
    out = bytearray(len(rgba_bytes))
    for i, v in enumerate(rgba_bytes):
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


def _resolve_rotate_filter(image_mod: _ImageModule) -> int:
    """Return the resample filter id used by `Image.rotate`. Pillow's
    `rotate` accepts only NEAREST, BILINEAR, and BICUBIC — LANCZOS is
    rejected at runtime as resize-only. We use BICUBIC as the highest-
    quality option allowed; the 3-class re-quantise downstream absorbs
    the small edge-pixel difference vs. a true Lanczos-3 pipeline."""
    resampling = getattr(image_mod, "Resampling", None)
    if resampling is not None:
        candidate = getattr(resampling, "BICUBIC", None)
        if candidate is not None:
            return int(candidate)
    return int(getattr(image_mod, "BICUBIC", 3))


# --- Atomic pair-write (C3 protocol) --------------------------------


def _atomic_write_pair(
    pgm_target: Path,
    yaml_target: Path,
    pgm_bytes: bytes,
    yaml_bytes: bytes,
) -> None:
    """C3 lock: PGM tmp → YAML tmp → fsync both → fsync dir → rename
    PGM → rename YAML → fsync dir. On YAML failure the PGM tmp/final
    is unlinked so the operator does not see a half-committed pair."""
    pgm_tmp = pgm_target.with_suffix(pgm_target.suffix + _TMP_SUFFIX)
    yaml_tmp = yaml_target.with_suffix(yaml_target.suffix + _TMP_SUFFIX)
    parent = pgm_target.parent

    pgm_committed = False

    try:
        # 1. Write + fsync PGM tmp.
        _write_fsync(pgm_tmp, pgm_bytes)
        # 2. Write + fsync YAML tmp.
        _write_fsync(yaml_tmp, yaml_bytes)
        # 3. fsync the dir so both tmp inodes are durable.
        _fsync_dir(parent)
        # 4. rename PGM (commit point one).
        os.replace(str(pgm_tmp), str(pgm_target))
        pgm_committed = True
        # 5. rename YAML (commit point two).
        try:
            os.replace(str(yaml_tmp), str(yaml_target))
        except OSError as e:
            # YAML failed AFTER PGM landed. Roll back the PGM so the
            # operator never sees a half-committed pair.
            with contextlib.suppress(OSError):
                os.unlink(str(pgm_target))
            raise PairWriteFailed(f"yaml_rename_failed: {e}") from e
        # 6. Final dir fsync.
        _fsync_dir(parent)
    except PairWriteFailed:
        raise
    except OSError as e:
        raise PairWriteFailed(f"pair_write_failed: {e}") from e
    finally:
        # Best-effort tmp cleanup. After a successful run both tmps
        # are gone (consumed by os.replace); after a failure either
        # may linger.
        for tmp in (pgm_tmp, yaml_tmp):
            with contextlib.suppress(OSError):
                if tmp.exists():
                    os.unlink(str(tmp))
        if not pgm_committed:
            with contextlib.suppress(OSError):
                if pgm_target.exists() and pgm_target.is_symlink():
                    pass  # never unlink the active.pgm symlink — caller's job
        # Idempotent — never raises.


def _write_fsync(target: Path, data: bytes) -> None:
    """Open + write + fsync + close. Mode 0644 mirrors map_edit /
    map_origin discipline (publicly readable artifact)."""
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
    """Best-effort directory fsync. On filesystems that do not support
    directory fsync (rare; tmpfs allows it) the syscall returns EINVAL
    and we suppress."""
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
    """Remove any leftover `*.tmp` files inside `maps_dir`. Called
    opportunistically by `app.py:list_maps` so a crashed Apply does
    not leak forever. Returns the count swept."""
    swept = 0
    for stale in maps_dir.glob(f"*{_TMP_SUFFIX}"):
        try:
            stale.unlink()
            swept += 1
        except OSError as e:
            logger.warning("map_rotate.sweep_failed: %s — %s", stale, e)
    return swept
