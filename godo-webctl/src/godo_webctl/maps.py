"""
Multi-map filesystem primitives (Track E, PR-C).

Pure functions over `cfg.maps_dir`. NO FastAPI imports, NO Pillow imports,
NO subprocess. The active pair is represented by two relative symlinks
inside `maps_dir`:

    /var/lib/godo/maps/
    ├─ studio_v1.pgm
    ├─ studio_v1.yaml
    ├─ studio_v2.pgm
    ├─ studio_v2.yaml
    ├─ active.pgm  → studio_v1.pgm   (relative target, basename only)
    ├─ active.yaml → studio_v1.yaml
    └─ .activate.lock                (advisory flock target, lazily created)

Symlink discipline:

- Targets are bare basenames (relative to `maps_dir`) so the directory is
  portable across hosts (backup → restore at a different mount point).
- Both `active.pgm` and `active.yaml` swap together under one
  `flock(LOCK_EX)` on `.activate.lock` so concurrent activate calls cannot
  interleave their stale-tmp sweep + dual symlink swap. Last-writer-wins.
- The atomic per-symlink swap is `os.symlink(target, tmp) +
  os.replace(tmp, link)` where `tmp = .active.<rand>.<ext>.tmp`.
  `secrets.token_hex(8)` gives a 64-bit unguessable suffix; collision is
  cryptographically negligible. Two syscalls, no observable in-between
  state outside this process.

Path-traversal defence (M1): every public function that returns or
operates on a path runs a `realpath` containment check —
`os.path.realpath(result)` MUST start with `os.path.realpath(maps_dir) +
os.sep`. Failure raises `InvalidName("path_outside_maps_dir")`. Never
`assert` (production may run with `-O`).

Reserved name (`"active"`): regex-passing but rejected by every public
function so an operator cannot upload `active.pgm` as a regular map and
confuse the resolver.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path

from .constants import (
    DERIVED_NAME_REGEX,
    DERIVED_TS_STRFTIME,
    MAPS_ACTIVATE_LOCK_BASENAME,
    MAPS_ACTIVE_BASENAME,
    MAPS_NAME_REGEX,
    MEMO_MAX_LEN_CHARS,
    MEMO_REGEX,
    PGM_HEADER_MAX_BYTES,
    YAML_HEADER_MAX_BYTES,
)

logger = logging.getLogger("godo_webctl.maps")

_PGM_EXT = "pgm"
_YAML_EXT = "yaml"
_TMP_PREFIX = ".active."
_TMP_SUFFIX = ".tmp"
_TMP_TOKEN_HEX_BYTES = 8
_LOCK_FILE_MODE = 0o600
_MAPS_DIR_MODE = 0o750


# --- Exceptions ---------------------------------------------------------


class InvalidName(ValueError):
    """Name fails `MAPS_NAME_REGEX`, is reserved, or escapes `maps_dir`."""


class MapNotFound(LookupError):
    """No `<name>.pgm + <name>.yaml` pair under `maps_dir`."""


class MapIsActive(RuntimeError):
    """`delete_pair` refuses because `<name>` is the active map."""


class MapsDirMissing(FileNotFoundError):
    """`maps_dir` itself does not exist."""


class PgmHeaderInvalid(ValueError):
    """Track D scale fix — `read_pgm_dimensions` could not parse the
    netpbm `P5` header (missing magic, missing width/height tokens, or
    non-numeric tokens). Lives here (NOT in `map_image.py`) to preserve
    `maps.py`'s Pillow-free invariant per its module docstring."""


# --- Data class ---------------------------------------------------------


@dataclass(frozen=True)
class MapEntry:
    """Single map pair as exposed by `list_pairs`. Internal field
    `mtime_ns` is preserved at full nanosecond precision for ordering;
    JSON serialisation (in app.py) emits `mtime_unix` as float epoch
    seconds (per Mode-A N3) — operators read epoch seconds, not raw
    nanoseconds, on the wire.

    Operator UX 2026-05-02 KST: `width_px` / `height_px` (parsed from the
    PGM P5 header) and `resolution_m` (parsed from the YAML
    `resolution:` line) let the SPA Map list show ``W×H px (X.X×Y.Y m)``
    — useful since the project switched from 0.05 m/cell to 0.025 m/cell
    defaults and operators need to see at-a-glance which maps are
    high-resolution. Any field is `None` if the corresponding header is
    missing/malformed (graceful degradation, NOT a list-skip).

    issue#30.1 (2026-05-05 KST): `lineage_kind` mirrors
    `<name>.sidecar.json :: lineage.kind` (`operator_apply` /
    `synthesized` / `auto_migrated_pre_issue30`) so the SPA Map list
    can render a kind-coded glyph next to each variant row WITHOUT
    opening LineageModal. `None` for pristine maps (no sidecar) or
    when the sidecar is missing / malformed (graceful degradation,
    matches the `read_yaml_resolution` precedent)."""

    name: str
    pgm_path: Path
    yaml_path: Path
    pgm_size_bytes: int
    pgm_mtime_ns: int
    is_active: bool
    width_px: int | None
    height_px: int | None
    resolution_m: float | None
    lineage_kind: str | None

    def to_dict(self) -> dict[str, object]:
        """JSON wire shape (per Mode-A N3): epoch-seconds float, NOT
        raw `mtime_ns`."""
        return {
            "name": self.name,
            "size_bytes": self.pgm_size_bytes,
            "mtime_unix": self.pgm_mtime_ns / 1_000_000_000,
            "is_active": self.is_active,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "resolution_m": self.resolution_m,
            "lineage_kind": self.lineage_kind,
        }


# --- Validation primitives ---------------------------------------------


def validate_name(name: str) -> None:
    """Raise `InvalidName` if `name` does not match `MAPS_NAME_REGEX`.
    Reserved-name (`"active"`) check is the responsibility of the public
    callers (`set_active`, `delete_pair`) — they raise
    `InvalidName("reserved_name")` so the error code is distinct from a
    generic regex miss."""
    if not MAPS_NAME_REGEX.match(name):
        raise InvalidName(f"invalid_name: {name!r}")


def _check_inside_maps_dir(result: Path, maps_dir: Path) -> None:
    """Mode-A M1: realpath containment. NEVER `assert` (production may
    run with `-O`). Pinned by
    `test_realpath_containment_rejects_symlink_targeting_outside_maps_dir`."""
    real_result = os.path.realpath(result)
    real_root = os.path.realpath(maps_dir)
    if not real_result.startswith(real_root + os.sep):
        raise InvalidName("path_outside_maps_dir")


def pgm_for(maps_dir: Path, name: str) -> Path:
    """Return the canonical `<name>.pgm` path under `maps_dir`. Validates
    name + realpath containment. Raises `InvalidName` on either failure."""
    validate_name(name)
    p = maps_dir / f"{name}.{_PGM_EXT}"
    # Containment check applies whether or not the file exists; if it is
    # a symlink to outside, realpath resolves regardless.
    if p.exists() or p.is_symlink():
        _check_inside_maps_dir(p, maps_dir)
    return p


def yaml_for(maps_dir: Path, name: str) -> Path:
    """Return the canonical `<name>.yaml` path under `maps_dir`."""
    validate_name(name)
    p = maps_dir / f"{name}.{_YAML_EXT}"
    if p.exists() or p.is_symlink():
        _check_inside_maps_dir(p, maps_dir)
    return p


def is_pair_present(maps_dir: Path, name: str) -> bool:
    """True iff both `<name>.pgm` and `<name>.yaml` exist (regular files
    or symlinks resolving to files). Validates name + containment."""
    validate_name(name)
    pgm = maps_dir / f"{name}.{_PGM_EXT}"
    yaml = maps_dir / f"{name}.{_YAML_EXT}"
    if not (pgm.is_file() and yaml.is_file()):
        return False
    _check_inside_maps_dir(pgm, maps_dir)
    _check_inside_maps_dir(yaml, maps_dir)
    return True


# --- PGM header reader (Track D scale fix) -----------------------------


def read_pgm_dimensions(pgm_path: Path) -> tuple[int, int]:
    """Read the netpbm `P5` text header and return `(width, height)`.

    netpbm `P5` (raw grayscale) header structure (whitespace-separated
    ASCII):

        P5
        # optional comment line(s)
        <width> <height>
        <maxval>
        <binary pixel data>

    The header fits comfortably in `PGM_HEADER_MAX_BYTES = 64` bytes for
    every map we handle (200×200 → "P5\\n200 200\\n255\\n" = 16 bytes).
    We READ AT MOST that many bytes from the file regardless of total
    file size — so a 1 GB sparse PGM never streams pixel data through
    Python.

    Raises:
        PgmHeaderInvalid — magic missing, dimensions missing/non-numeric.
        OSError — propagated from `Path.open` / `read` (caller maps).
    """
    with pgm_path.open("rb") as f:
        head = f.read(PGM_HEADER_MAX_BYTES)
    if not head.startswith(b"P5"):
        raise PgmHeaderInvalid("missing_p5_magic")
    # Drop the magic, then split on any whitespace and skip comment
    # tokens (whole-line `#…\n` chunks).
    rest = head[2:]
    tokens: list[bytes] = []
    i = 0
    while i < len(rest) and len(tokens) < 2:
        ch = rest[i : i + 1]
        if ch in (b" ", b"\t", b"\n", b"\r"):
            i += 1
            continue
        if ch == b"#":
            # Skip the rest of the comment line.
            while i < len(rest) and rest[i : i + 1] not in (b"\n", b"\r"):
                i += 1
            continue
        # Read a non-whitespace token.
        start = i
        while i < len(rest) and rest[i : i + 1] not in (b" ", b"\t", b"\n", b"\r", b"#"):
            i += 1
        tokens.append(rest[start:i])
    if len(tokens) < 2:
        raise PgmHeaderInvalid("missing_dimensions")
    try:
        width = int(tokens[0])
        height = int(tokens[1])
    except ValueError as e:
        raise PgmHeaderInvalid(f"non_numeric_dimension: {e}") from e
    if width <= 0 or height <= 0:
        raise PgmHeaderInvalid(f"non_positive_dimension: {width}x{height}")
    return (width, height)


# --- Active-symlink readers --------------------------------------------


def read_active_name(maps_dir: Path) -> str | None:
    """Return the active map's `<name>` by reading `active.pgm`'s symlink
    target and stripping `.pgm`. Returns `None` when there is no
    `active.pgm` symlink, when its target's basename does not pass
    `MAPS_NAME_REGEX` (= broken / hand-edited), or when the directory
    does not exist."""
    link = maps_dir / f"{MAPS_ACTIVE_BASENAME}.{_PGM_EXT}"
    try:
        target = os.readlink(link)
    except (FileNotFoundError, OSError):
        return None
    base = os.path.basename(target)
    if not base.endswith(f".{_PGM_EXT}"):
        return None
    stem = base[: -len(f".{_PGM_EXT}")]
    if not MAPS_NAME_REGEX.match(stem):
        return None
    return stem


# --- Listing -----------------------------------------------------------


def read_yaml_resolution(yaml_path: Path) -> float | None:
    """Parse the ``resolution:`` line out of a slam_toolbox / map_saver
    YAML companion. Returns the float in meters/cell, or None on any
    parse failure (missing line, non-numeric, file unreadable). The full
    YAML is intentionally NOT parsed via PyYAML — we already have a
    line-based parser idiom elsewhere (see backup.py / map_yaml.py) and
    a missing/malformed resolution must NEVER raise the entire
    list_pairs call (graceful degradation per Mode-A discipline).

    Header bytes are bounded by `YAML_HEADER_MAX_BYTES` so a 1 GB sparse
    YAML never streams through Python."""
    try:
        with yaml_path.open("rb") as f:
            head = f.read(YAML_HEADER_MAX_BYTES)
    except OSError:
        return None
    text = head.decode("utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("resolution"):
            continue
        # Match `resolution: <number>` (any whitespace around `:`).
        _, _, rhs = stripped.partition(":")
        rhs = rhs.strip()
        # Strip an optional inline comment.
        if "#" in rhs:
            rhs = rhs.split("#", 1)[0].strip()
        try:
            return float(rhs)
        except ValueError:
            return None
    return None


def _read_lineage_kind(maps_dir: Path, name: str) -> str | None:
    """Read `<name>.sidecar.json` and return `body.lineage.kind`, or
    `None` on any failure mode (missing file / malformed JSON / missing
    key / non-string value).

    issue#30.1: pattern matches `read_yaml_resolution` above — graceful
    degradation, NEVER raises. The SPA shows no glyph for `None`. We
    bypass `sidecar.read()` (which validates the full schema) because
    callers under `list_pairs` only need this one field; failed schema
    validation should NOT prevent the row from being listed.
    """
    p = maps_dir / f"{name}.sidecar.json"
    try:
        with p.open("rb") as f:
            raw = f.read()
    except OSError:
        return None
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict):
        return None
    lineage = body.get("lineage")
    if not isinstance(lineage, dict):
        return None
    kind = lineage.get("kind")
    if not isinstance(kind, str):
        return None
    return kind


def list_pairs(maps_dir: Path) -> list[MapEntry]:
    """Enumerate every `<stem>.pgm` + `<stem>.yaml` pair under `maps_dir`.
    Filenames not matching `MAPS_NAME_REGEX` (e.g. `active.pgm` is
    rejected because it is the reserved basename — but it appears as a
    symlink and we want to mark its TARGET, not list it twice; see
    below) are skipped silently. Sorted by name (case-sensitive,
    str-compare).

    Raises `MapsDirMissing` if `maps_dir` itself does not exist.
    """
    if not maps_dir.exists():
        raise MapsDirMissing(str(maps_dir))
    if not maps_dir.is_dir():
        raise MapsDirMissing(str(maps_dir))

    active = read_active_name(maps_dir)

    entries: list[MapEntry] = []
    for entry in maps_dir.iterdir():
        # We want to enumerate the regular-file PGMs and skip the
        # `active.pgm` symlink (its target is already in the iteration).
        # `is_file(follow_symlinks=False)` would skip the symlink itself
        # but we also must skip names matching `active`, partial uploads
        # with no YAML sibling, lockfiles, and `.active.*.tmp` leftovers.
        if entry.is_symlink():
            continue
        if not entry.is_file():
            continue
        name = entry.name
        if not name.endswith(f".{_PGM_EXT}"):
            continue
        stem = name[: -len(f".{_PGM_EXT}")]
        if stem == MAPS_ACTIVE_BASENAME:
            continue
        if not MAPS_NAME_REGEX.match(stem):
            continue
        yaml = maps_dir / f"{stem}.{_YAML_EXT}"
        if not yaml.is_file():
            continue
        try:
            st = entry.stat()
        except OSError:
            continue
        # Operator UX 2026-05-02 KST: surface PGM dimensions + YAML
        # resolution so the SPA Map list can render
        # `W×H px (X.X×Y.Y m)`. Either field may be None if the header
        # is malformed; the row still appears (graceful degradation).
        try:
            width_px, height_px = read_pgm_dimensions(entry)
        except (PgmHeaderInvalid, OSError):
            width_px = None
            height_px = None
        resolution_m = read_yaml_resolution(yaml)
        # issue#30.1 (2026-05-05 KST): opportunistic sidecar read for
        # the inline lineage glyph. None for pristines (no sidecar)
        # and for malformed/missing sidecars (graceful degradation).
        lineage_kind = _read_lineage_kind(maps_dir, stem)
        entries.append(
            MapEntry(
                name=stem,
                pgm_path=entry,
                yaml_path=yaml,
                pgm_size_bytes=st.st_size,
                pgm_mtime_ns=st.st_mtime_ns,
                is_active=(stem == active),
                width_px=width_px,
                height_px=height_px,
                resolution_m=resolution_m,
                lineage_kind=lineage_kind,
            ),
        )
    entries.sort(key=lambda e: e.name)
    return entries


# --- Atomic activate ---------------------------------------------------


def _new_tmp_name(maps_dir: Path, ext: str) -> str:
    """Return an unguessable tmp symlink path inside `maps_dir`. The
    `secrets.token_hex` suffix gives a 64-bit collision space without a
    filesystem write (`mkstemp` is avoided per Mode-A M2)."""
    return str(
        maps_dir / f"{_TMP_PREFIX}{secrets.token_hex(_TMP_TOKEN_HEX_BYTES)}.{ext}{_TMP_SUFFIX}",
    )


def _sweep_stale_tmp(maps_dir: Path) -> None:
    """Remove any `.active.*.tmp` leftovers from a prior crashed swap
    (Mode-A M3). Always called under the activate flock at the START of
    `set_active`. Idempotent."""
    for stale in maps_dir.glob(f"{_TMP_PREFIX}*{_TMP_SUFFIX}"):
        with contextlib.suppress(OSError):
            stale.unlink()


def set_active(maps_dir: Path, name: str) -> None:
    """Atomically point `active.{pgm,yaml}` at `<name>.{pgm,yaml}`.

    Sequence (under `flock(LOCK_EX)` on `.activate.lock`):

    1. Sweep `.active.*.tmp` leftovers.
    2. For ext in (pgm, yaml):
       a. `os.symlink(<name>.<ext>, .active.<rand>.<ext>.tmp)` — atomic
          create-or-EEXIST.
       b. `os.replace(.active.<rand>.<ext>.tmp, active.<ext>)` — POSIX
          `rename(2)` atomic on same filesystem.

    Raises `InvalidName` (regex / reserved / containment),
    `MapNotFound` (pair missing), `MapsDirMissing` (no `maps_dir`).
    """
    validate_name(name)
    if name == MAPS_ACTIVE_BASENAME:
        raise InvalidName("reserved_name")
    if not maps_dir.exists() or not maps_dir.is_dir():
        raise MapsDirMissing(str(maps_dir))
    if not is_pair_present(maps_dir, name):
        raise MapNotFound(name)

    lock_path = maps_dir / MAPS_ACTIVATE_LOCK_BASENAME
    lock_fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, _LOCK_FILE_MODE)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        _sweep_stale_tmp(maps_dir)
        for ext in (_PGM_EXT, _YAML_EXT):
            target_basename = f"{name}.{ext}"
            link_path = maps_dir / f"{MAPS_ACTIVE_BASENAME}.{ext}"
            tmp_name = _new_tmp_name(maps_dir, ext)
            os.symlink(target_basename, tmp_name)
            try:
                os.replace(tmp_name, str(link_path))
            except OSError:
                # Best-effort cleanup; the next `set_active` sweep will
                # also catch any leftover tmp.
                with contextlib.suppress(OSError):
                    os.unlink(tmp_name)
                logger.error(
                    "maps.set_active_partial: name=%s ext=%s — "
                    "active.pgm/yaml may be mismatched; re-run activate",
                    name,
                    ext,
                )
                raise
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# --- Delete ------------------------------------------------------------


def delete_pair(maps_dir: Path, name: str) -> None:
    """Remove `<name>.pgm` + `<name>.yaml`.

    Raises `InvalidName` (regex / reserved / containment),
    `MapNotFound` (pair missing), `MapIsActive` (`<name>` is the
    currently active map; operator must activate a different map first).
    """
    validate_name(name)
    if name == MAPS_ACTIVE_BASENAME:
        raise InvalidName("reserved_name")
    if not is_pair_present(maps_dir, name):
        raise MapNotFound(name)
    if read_active_name(maps_dir) == name:
        raise MapIsActive(name)
    pgm = maps_dir / f"{name}.{_PGM_EXT}"
    yaml = maps_dir / f"{name}.{_YAML_EXT}"
    _check_inside_maps_dir(pgm, maps_dir)
    _check_inside_maps_dir(yaml, maps_dir)
    pgm.unlink()
    yaml.unlink()
    # issue#30 — also unlink the sidecar JSON if present. Sidecar
    # absence is fine (pre-issue#30 derived, pristine, or
    # auto-migrated path that hasn't been list-swept yet).
    sidecar = maps_dir / f"{name}.sidecar.json"
    try:
        _check_inside_maps_dir(sidecar, maps_dir)
        sidecar.unlink(missing_ok=True)
    except (InvalidName, OSError) as e:
        logger.info("maps.delete_pair_sidecar_unlink_skipped: name=%s — %s", name, e)


# --- Back-compat soft migration ---------------------------------------


def migrate_legacy_active(maps_dir: Path, legacy_pgm: Path) -> bool:
    """One-shot migration from the deprecated single-`cfg.map_path`
    layout to the multi-map layout.

    Behaviour:

    1. If `maps_dir/active.pgm` already exists → return False (no-op).
    2. Else, ensure `maps_dir` exists at mode 0750.
    3. If `legacy_pgm` is INSIDE `maps_dir` already, only create the
       active symlinks pointing at it. Otherwise, copy the `.pgm` and
       `.yaml` sibling into `maps_dir` (preserving basename) and create
       the symlinks. Existing same-named files in `maps_dir` are NOT
       overwritten — operator may have hand-migrated already; we just
       fix the symlinks.

    Returns True iff a migration ran. Idempotent.
    """
    active_pgm = maps_dir / f"{MAPS_ACTIVE_BASENAME}.{_PGM_EXT}"
    if active_pgm.exists() or active_pgm.is_symlink():
        return False
    if not legacy_pgm.exists() or not legacy_pgm.is_file():
        return False

    legacy_yaml = legacy_pgm.with_suffix(".yaml")
    if not legacy_yaml.is_file():
        return False

    legacy_stem = legacy_pgm.stem
    if not MAPS_NAME_REGEX.match(legacy_stem):
        logger.warning(
            "maps.legacy_basename_unsafe: stem=%s does not match name regex; aborting migration",
            legacy_stem,
        )
        return False

    maps_dir.mkdir(parents=True, exist_ok=True, mode=_MAPS_DIR_MODE)

    legacy_in_maps = os.path.dirname(os.path.abspath(legacy_pgm)) == os.path.abspath(maps_dir)
    if not legacy_in_maps:
        target_pgm = maps_dir / legacy_pgm.name
        target_yaml = maps_dir / legacy_yaml.name
        if not target_pgm.exists():
            shutil.copy2(legacy_pgm, target_pgm)
        if not target_yaml.exists():
            shutil.copy2(legacy_yaml, target_yaml)

    set_active(maps_dir, legacy_stem)
    logger.warning(
        "maps.legacy_migration_complete: source=%s target=%s name=%s",
        legacy_pgm,
        maps_dir,
        legacy_stem,
    )
    return True


# --- issue#28 — pristine vs derived classification --------------------


class InvalidMemo(ValueError):
    """Memo postfix fails `MEMO_REGEX` or exceeds `MEMO_MAX_LEN_CHARS`."""


def is_pristine(name: str) -> bool:
    """Return True iff `name` does NOT match the derived-name regex.

    The derived form is `<base>.YYYYMMDD-HHMMSS-<memo>`; the second-
    resolution timestamp + memo postfix together make the regex match
    unambiguous (a hand-edited map name like `chroma.foo` does not
    match because no timestamp triple is present). This function is
    the SOLE classifier — never re-implement the regex elsewhere.
    """
    return DERIVED_NAME_REGEX.match(name) is None


def derived_base(name: str) -> str | None:
    """Return the base (= pristine) name for a derived map name, or
    None when `name` is itself pristine. Pure-string operation; does
    NOT touch the filesystem."""
    m = DERIVED_NAME_REGEX.match(name)
    if m is None:
        return None
    return m.group("base")


def validate_memo(memo: str) -> None:
    """Raise `InvalidMemo` if `memo` fails the project's regex or
    length cap. Surfaced through app.py as 422."""
    if not memo or len(memo) > MEMO_MAX_LEN_CHARS:
        raise InvalidMemo("memo_length_out_of_range")
    if not MEMO_REGEX.match(memo):
        raise InvalidMemo("memo_invalid_chars")


def derive_name(base: str, memo: str, ts: str | None = None) -> str:
    """Build a derived map name `<base>.<ts>-<memo>`. `ts` defaults to
    KST `strftime(DERIVED_TS_STRFTIME)`; tests inject a fixed ts.

    Validates `base` against `MAPS_NAME_REGEX` and `memo` against
    `MEMO_REGEX` so a malformed input cannot be silently composed
    into a pair on disk."""
    validate_name(base)
    validate_memo(memo)
    if ts is None:
        from .timestamps import now_kst

        ts = now_kst().strftime(DERIVED_TS_STRFTIME)
    if len(ts) != 15 or ts[8] != "-":
        # Defence: caller-injected ts must look like YYYYMMDD-HHMMSS.
        raise InvalidMemo("ts_invalid_shape")
    return f"{base}.{ts}-{memo}"


# --- issue#28 — grouped tree listing ----------------------------------


@dataclass(frozen=True)
class MapGroup:
    """One pristine + its derived variants. `pristine` may be None when
    a base lacks an on-disk pristine pair (e.g. operator hand-removed
    it but kept derivatives) — surfaced as `pristine: null` in JSON
    so the SPA can warn the operator."""

    base: str
    pristine: MapEntry | None
    variants: list[MapEntry]

    def to_dict(self) -> dict[str, object]:
        return {
            "base": self.base,
            "pristine": self.pristine.to_dict() if self.pristine else None,
            "variants": [v.to_dict() for v in self.variants],
        }


def list_pairs_grouped(maps_dir: Path) -> list[MapGroup]:
    """Group `list_pairs(maps_dir)` results into pristine-parent
    rows + derived-child rows. Sort: groups by pristine name, variants
    by full name (= chronological because timestamp is the leading
    discriminator after the base prefix).

    Pristine/derived classification uses `is_pristine`; the regex is
    the SSOT (do not re-implement)."""
    flat = list_pairs(maps_dir)
    groups: dict[str, MapGroup] = {}
    # Pass 1 — pristines.
    for e in flat:
        if is_pristine(e.name):
            groups[e.name] = MapGroup(base=e.name, pristine=e, variants=[])
    # Pass 2 — variants. A derived whose base lacks an on-disk pristine
    # entry still gets surfaced (with pristine=None) so the operator
    # can see the orphan.
    for e in flat:
        if is_pristine(e.name):
            continue
        base = derived_base(e.name)
        if base is None:
            continue  # defensive — is_pristine returning False guarantees a base
        grp = groups.get(base)
        if grp is None:
            groups[base] = MapGroup(base=base, pristine=None, variants=[e])
        else:
            grp.variants.append(e)
    # Stable order: groups by base name; variants by full name.
    ordered: list[MapGroup] = []
    for base in sorted(groups):
        grp = groups[base]
        grp.variants.sort(key=lambda v: v.name)
        ordered.append(grp)
    return ordered
