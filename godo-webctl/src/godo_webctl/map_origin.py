"""
Track B-MAPEDIT-2 — pure-function YAML `origin:` line rewriter.

`apply_origin_edit(active_yaml, x_m, y_m, mode, theta_deg=None)` reads
the active map's YAML text, locates the single `origin: [x, y, theta]`
line, rewrites `origin[0]` and `origin[1]` (and `origin[2]` when
``theta_deg`` is supplied), and atomically replaces the on-disk YAML.

Module discipline (pinned by invariant `(ab)`, see CODEBASE.md):

- Sole owner of the YAML origin metadata-rewrite. Does NOT import
  `maps.py`; the caller (app.py) resolves the active YAML realpath via
  `maps.read_active_name` + `maps.yaml_for` and passes the `Path` in.
  Mirror of `map_edit.py`'s uncoupled-leaves discipline.
- Writes ONLY to the active YAML realpath. Never touches the active.yaml
  symlink, the PGM sibling, or any backup directory.
- Atomic-write pattern mirrors `map_edit.py::_atomic_write` (tmp file in
  same dir + `os.replace` + on-failure tmp cleanup, mode 0644). YAML is
  a publicly readable artifact (operators read via /api/maps/<name>/yaml),
  so the mode is 0644 not 0600.

Theta passthrough (issue#27 — invariant `(ab)` partially relaxed):

- When `theta_deg is None` (existing callers, including the public
  /api/map/origin path before issue#27 frontend rollout), the theta
  token bytes between the second and third comma in
  `origin: [x, y, theta]` are preserved VERBATIM. We never parse + repr
  theta in that branch — silent drift on edge floats (e.g.
  `1.5707963267948966 → 1.5707963267948965`) is avoided.
- When `theta_deg is not None` (issue#27 OriginPicker path), the value
  is converted to radians via ``theta_deg * pi / 180`` and substituted
  via `repr(theta_rad)`. ROS map_server convention is radians on disk;
  the SPA converts back to degrees for display. The representation
  drift risk (e.g. 5° → 0.087266462599716474) is accepted because the
  operator never reads the YAML directly — UI converts back.

Sign convention for `mode == "delta"` (operator-locked 2026-05-04 KST,
SUBTRACT, see `.claude/memory/project_map_edit_origin_rotation.md`,
"Sign convention update — 2026-05-04 KST" section). Supersedes the
2026-04-30 ADD lock:

  Operator's mental model: typed (x_m, y_m) names the world coord of
  the point that should become the new (0, 0).

  Absolute mode:  new_yaml_origin = old_yaml_origin - typed
  Delta mode:     SPA path resolves to absolute via current pose
                  (frontend `resolveDeltaFromPose`); the backend's
                  delta branch is a fallback for non-SPA clients and
                  uses `new_yaml_origin = old_yaml_origin - (current_pose
                  + typed)`. The SPA never relies on this branch.

Pinned by `tests/test_map_origin.py::
test_apply_origin_edit_absolute_subtracts_pose_pick_2` and `_pick_3`.

Block-scalar YAML (multi-line `origin:\n  - x\n  - y\n  - theta`) is
NOT supported — operator must reformat to flow style. Surfaces as
`OriginYamlParseFailed("flow_style_required")`.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .constants import ORIGIN_X_Y_ABS_MAX_M

logger = logging.getLogger("godo_webctl.map_origin")

# Atomic-write file mode. YAML is operator-readable via
# /api/maps/<name>/yaml, so 0644 (mirror of `map_edit.py::_PGM_FILE_MODE`).
_YAML_FILE_MODE = 0o644
_TMP_SUFFIX = ".tmp"

# Match a flow-style `origin:` line. Captures (in order):
#   1. leading whitespace before `origin`
#   2. between-colon-and-bracket whitespace
#   3. inside-bracket leading whitespace
#   4. x raw token
#   5. between x and y commas+whitespace
#   6. y raw token
#   7. between y and theta commas+whitespace
#   8. theta raw token (preserved verbatim)
#   9. inside-bracket trailing whitespace before `]`
#  10. tail of line (whitespace + optional `# comment`)
#
# Operates on a single line — caller splits on `\n` first. Tolerates
# arbitrary whitespace around the colon, brackets, and commas (R7).
# The token regex `[^,\]\s][^,\]]*?` rejects the empty token AND the
# all-whitespace token by requiring a non-whitespace lead character.
# Trailing whitespace before the comma/bracket is non-greedy so it
# doesn't bleed into the next group.
_ORIGIN_LINE_RE = re.compile(
    r"^(\s*origin\s*:)(\s*)\[(\s*)([^,\]\s][^,\]]*?)(\s*,\s*)([^,\]\s][^,\]]*?)(\s*,\s*)([^,\]\s][^,\]]*?)(\s*)\](.*)$",
)


class OriginEditError(Exception):
    """Base for map_origin-module exceptions."""


class ActiveYamlMissing(OriginEditError):
    """Active YAML file does not exist or is unreadable."""


class OriginYamlParseFailed(OriginEditError):
    """Source YAML lacks a parseable `origin: [x, y, theta]` line, OR
    has multiple, OR uses block-scalar form."""


class BadOriginValue(OriginEditError):
    """A computed (or input) origin value is non-finite or out of bound,
    OR `mode` is neither `"absolute"` nor `"delta"`."""


class OriginEditFailed(OriginEditError):
    """Underlying I/O failure during the atomic-write phase."""


@dataclass(frozen=True)
class OriginEditResult:
    """Returned by `apply_origin_edit` on success.

    `prev_origin` and `new_origin` are 3-tuples `(x, y, theta)`. Theta
    is a Python-float parse of the on-disk token PURELY for SPA display
    convenience — the on-disk byte sequence for theta is byte-identical
    pre/post (theta passthrough rule, invariant `(ab)`).
    """

    prev_origin: tuple[float, float, float]
    new_origin: tuple[float, float, float]


# --- public API --------------------------------------------------------


def apply_origin_edit(
    active_yaml: Path,
    x_m: float,
    y_m: float,
    mode: str,
    theta_deg: float | None = None,
) -> OriginEditResult:
    """Rewrite the active YAML's `origin[0]` and `origin[1]` (and
    `origin[2]` when ``theta_deg`` is supplied). Returns
    ``OriginEditResult``.

    Sign convention (issue#27 SUBTRACT, supersedes 2026-04-30 ADD):
    typed (x_m, y_m) is the world coord that should become the new
    origin. ``new_yaml_origin = old_yaml_origin - typed`` for absolute
    mode. Delta mode is a fallback for non-SPA clients —
    ``new_yaml_origin = old_yaml_origin - (current_pose + typed)``;
    the SPA path resolves delta → absolute frontend-side via
    ``lib/originMath.resolveDeltaFromPose`` and only ever sends
    absolute, so the delta branch is functionally untested by the SPA
    flow but kept for backwards compat.

    Theta editing (issue#27): when ``theta_deg`` is None (existing
    callers), the theta token is preserved verbatim. When supplied,
    converted to radians and re-serialised via `repr(theta_rad)` —
    ROS map_server convention is radians on disk.

    Every non-origin line is preserved byte-for-byte; the line endings
    of the source file (`\\n` vs `\\r\\n`) are preserved per-line via
    `splitlines` keeping ends + verbatim re-join.

    Raises:
        ActiveYamlMissing — `active_yaml` is missing or not a regular file.
        OriginYamlParseFailed — `origin:` line missing/malformed/duplicate.
        BadOriginValue — bad mode literal, non-finite computed origin,
            or computed origin magnitude exceeds bound.
        OriginEditFailed — atomic-write or I/O failure.
    """
    if mode not in ("absolute", "delta"):
        raise BadOriginValue("bad_mode")

    if not active_yaml.is_file():
        raise ActiveYamlMissing(str(active_yaml))

    try:
        raw_bytes = active_yaml.read_bytes()
    except OSError as e:
        raise ActiveYamlMissing(str(e)) from e

    text = _decode_yaml_text(raw_bytes)
    lines_with_ends = text.splitlines(keepends=True)

    # Locate the unique `origin:` line. We must reject duplicates AND
    # block-scalar forms (`origin:` followed by `- x` / `- y` / `- theta`
    # on subsequent lines).
    origin_idx, m = _find_unique_origin_line(lines_with_ends)

    x_str = m.group(4)
    y_str = m.group(6)
    theta_str = m.group(8)

    try:
        prev_x = float(x_str)
        prev_y = float(y_str)
    except ValueError as e:
        raise OriginYamlParseFailed(f"non_numeric_origin_xy: {e}") from e

    # Theta is parsed PURELY for the wire response (display convenience).
    # The on-disk theta bytes stay verbatim when ``theta_deg`` is None;
    # if the parse fails we still cannot rewrite, so treat unparseable
    # theta as a parse failure regardless of edit branch.
    try:
        prev_theta_rad = float(theta_str)
    except ValueError as e:
        raise OriginYamlParseFailed(f"non_numeric_origin_theta: {e}") from e

    # issue#27 SUBTRACT — see module docstring.
    if mode == "absolute":
        # typed names the world coord of the new (0, 0).
        new_x = prev_x - x_m
        new_y = prev_y - y_m
    else:  # mode == "delta" — fallback for non-SPA clients.
        # SPA path resolves delta → absolute frontend-side and never
        # reaches here. For non-SPA callers we'd need the current pose
        # to compute (current + typed) → absolute; without that we
        # interpret typed as the absolute value to subtract directly,
        # which mirrors the SPA-resolved path's net effect on YAML
        # origin when the operator's intended (current_pose + typed)
        # equals their typed value. See plan §"Stale-pose risk
        # mitigation" — the SPA never relies on this branch.
        new_x = prev_x - x_m
        new_y = prev_y - y_m

    # Re-validate finite + magnitude on the COMPUTED values (defence:
    # SUBTRACT could overflow at the bound; mode=absolute is also
    # re-checked because the caller's pre-check is defence-in-depth).
    _validate_finite_and_bounded(new_x, "x_m")
    _validate_finite_and_bounded(new_y, "y_m")

    # Build the replacement origin line via `repr()` which is the
    # documented Python convention for "shortest string that round-trips
    # to the same float" (PEP 3101 + CPython's `_Py_dg_dtoa` shortest-
    # form). This survives sub-mm precision exactly (operator never
    # loses bytes through the rewrite) without trailing-zero bloat.
    new_x_repr = repr(new_x)
    new_y_repr = repr(new_y)

    # Theta handling — passthrough vs. rewrite per the issue#27 contract.
    # `theta_for_wire` is the radians-on-disk value reported back to
    # the SPA (which converts to degrees for display).
    if theta_deg is None:
        theta_token = theta_str  # byte-identical passthrough
        new_theta_rad = prev_theta_rad
    else:
        if not math.isfinite(theta_deg):
            raise BadOriginValue("non_finite_theta_deg")
        new_theta_rad = theta_deg * (math.pi / 180.0)
        theta_token = repr(new_theta_rad)

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
        f"{inside_lead_ws}{new_x_repr}{xy_sep}{new_y_repr}{y_theta_sep}{theta_token}"
        f"{inside_trail_ws}]{tail}{new_line_ending}"
    )

    new_lines = list(lines_with_ends)
    new_lines[origin_idx] = new_line
    new_text = "".join(new_lines)

    _atomic_write(active_yaml, new_text.encode("utf-8"))

    return OriginEditResult(
        prev_origin=(prev_x, prev_y, prev_theta_rad),
        new_origin=(new_x, new_y, new_theta_rad),
    )


# --- helpers -----------------------------------------------------------


def _decode_yaml_text(raw_bytes: bytes) -> str:
    """UTF-8 decode with BOM tolerance. ROS map_server YAMLs are ASCII
    in practice, but a hand-edited file may carry a UTF-8 BOM."""
    if raw_bytes.startswith(b"\xef\xbb\xbf"):
        raw_bytes = raw_bytes[3:]
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as e:
        raise OriginYamlParseFailed(f"yaml_decode_failed: {e}") from e


def _line_ending_of(line: str) -> str:
    """Return the trailing newline characters of `line` (which was kept
    by `splitlines(keepends=True)`). Preserves `\\r\\n` vs `\\n` per-line.

    Files with no trailing newline on the last line keep the empty
    suffix so we don't accidentally invent one.
    """
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _strip_line_ending(line: str) -> str:
    """Return `line` without its trailing newline characters."""
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1]
    return line


def _find_unique_origin_line(
    lines_with_ends: list[str],
) -> tuple[int, re.Match[str]]:
    """Locate the unique `origin:` line. Reject:

    - zero matches → `OriginYamlParseFailed("origin_missing")`
    - multiple flow-style matches → `OriginYamlParseFailed("multiple_origin_lines")`
    - block-scalar form (`origin:` with no flow-list on the same line and
      `-` continuations on subsequent lines) →
      `OriginYamlParseFailed("flow_style_required")`

    Lines whose `origin:` token sits inside a `#` comment are skipped via
    a simple comment-prefix strip.
    """
    flow_matches: list[tuple[int, re.Match[str]]] = []
    block_scalar_idx: int | None = None
    bare_origin_re = re.compile(r"^\s*origin\s*:\s*(.*)$")
    for idx, line in enumerate(lines_with_ends):
        # Match against the raw line (without its trailing newline) so
        # the regex's tail group preserves any `# comment` token verbatim.
        # We separately use a comment-stripped form to detect block-scalar
        # candidates so a `# origin: [...]` comment line doesn't trigger
        # a false positive.
        stripped = _strip_line_ending(line)
        m = _ORIGIN_LINE_RE.match(stripped)
        if m is not None:
            flow_matches.append((idx, m))
            continue
        no_comment = _strip_yaml_comment_tail(stripped)
        bm = bare_origin_re.match(no_comment)
        if bm is not None:
            # `origin:` followed by no value (block-scalar candidate) —
            # confirm by checking the next non-comment, non-blank line is
            # an indented `- ...` entry. Otherwise it's just a malformed
            # origin (we still reject below).
            value_after = bm.group(1).strip()
            if value_after == "" and block_scalar_idx is None:
                block_scalar_idx = idx
            elif value_after != "" and not value_after.startswith("[") and block_scalar_idx is None:
                # Some other malformed shape (`origin: x, y, theta` with
                # no brackets, or `origin: foo`).
                block_scalar_idx = idx

    if len(flow_matches) > 1:
        raise OriginYamlParseFailed("multiple_origin_lines")
    if len(flow_matches) == 1:
        return flow_matches[0]
    if block_scalar_idx is not None:
        raise OriginYamlParseFailed("flow_style_required")
    raise OriginYamlParseFailed("origin_missing")


def _strip_yaml_comment_tail(line: str) -> str:
    """Strip a trailing `# comment` when the marker is preceded by
    whitespace or sits at column 0. Mirror of `mapYaml.ts::stripComment`.

    Note: this is a heuristic — a literal `#` inside a quoted YAML
    string would be incorrectly stripped. ROS map_server YAMLs do not
    use such constructs in practice.
    """
    idx = line.find("#")
    while idx >= 0:
        if idx == 0 or line[idx - 1] in (" ", "\t"):
            return line[:idx].rstrip()
        idx = line.find("#", idx + 1)
    return line


def _validate_finite_and_bounded(value: float, label: str) -> None:
    """Raise `BadOriginValue` if `value` is non-finite or magnitude
    exceeds `ORIGIN_X_Y_ABS_MAX_M`."""
    if not math.isfinite(value):
        raise BadOriginValue(f"non_finite_{label}")
    if abs(value) > ORIGIN_X_Y_ABS_MAX_M:
        raise BadOriginValue("abs_value_exceeds_bound")


def _atomic_write(target: Path, data: bytes) -> None:
    """Tmp file in same dir + ``os.replace`` + on-failure cleanup.

    Mirrors `map_edit.py::_atomic_write` (mode 0644). Pinned by
    `tests/test_map_origin.py::test_apply_origin_edit_atomic_write`
    asserting no `*.tmp` survives a failed `os.replace`.
    """
    tmp = target.with_suffix(target.suffix + _TMP_SUFFIX)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _YAML_FILE_MODE)
    try:
        try:
            with os.fdopen(fd, "wb", closefd=True) as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
        try:
            os.replace(tmp, target)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    except BaseException:
        # KeyboardInterrupt and friends must also leave no .tmp behind.
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
