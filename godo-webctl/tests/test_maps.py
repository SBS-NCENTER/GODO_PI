"""
Pure-function tests for `godo_webctl.maps`.

Covers:
- `validate_name` accepts/rejects per `MAPS_NAME_REGEX`.
- `pgm_for`/`yaml_for` realpath containment (Mode-A M1).
- `list_pairs` filters partial uploads, the active symlink, and
  unrelated files.
- `set_active` swaps both symlinks atomically; sweeps stale tmp
  leftovers (Mode-A M3); two-syscall create-then-replace per Mode-A M2;
  rejects reserved name `"active"` and unknown maps.
- Crash-mid-yaml-swap leaves a `.active.*.yaml.tmp` leftover that the
  next `set_active` sweeps (Mode-A TB1 + M3 pin).
- Concurrent activate is serialized by flock with arrival-order pinned
  (Mode-A TB3) — thread B blocks ≥ 40 ms behind thread A's 50 ms sleep,
  thread B's name wins, no `.active.*.tmp` leftovers.
- `delete_pair` refuses on the active map (`MapIsActive`) and unknown
  maps (`MapNotFound`).
- `migrate_legacy_active` is idempotent and copies + symlinks correctly.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from godo_webctl import maps as M
from godo_webctl.constants import MAPS_ACTIVATE_LOCK_BASENAME, MAPS_ACTIVE_BASENAME

# Per Mode-A test-discipline: rejection corpus uses STRING LITERALS, not
# parametrize, so each failure message names exactly which input
# violated. That also keeps a future "fold the cases together" tidy-up
# from accidentally collapsing distinct contracts into one assertion.

_NAME_GOOD = "studio_v1"
_NAME_GOOD_OTHER = "studio_v2"


def _write_pgm(p: Path, fill: int = 128) -> None:
    p.write_bytes(b"P5\n4 4\n255\n" + bytes([fill] * 16))


def _write_yaml(p: Path, image_basename: str) -> None:
    p.write_text(f"image: {image_basename}\nresolution: 0.05\norigin: [0,0,0]\n")


def _make_pair(maps_dir: Path, name: str, fill: int = 128) -> None:
    pgm = maps_dir / f"{name}.pgm"
    yaml = maps_dir / f"{name}.yaml"
    _write_pgm(pgm, fill=fill)
    _write_yaml(yaml, f"{name}.pgm")


# --- validate_name -----------------------------------------------------


def test_validate_name_accepts_basic_stem() -> None:
    M.validate_name(_NAME_GOOD)
    M.validate_name("a")
    M.validate_name("a" * 64)
    M.validate_name("2026-04-28_v3")


def test_validate_name_rejects_empty() -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name("")


def test_validate_name_rejects_too_long() -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name("a" * 65)


def test_validate_name_rejects_dot_traversal() -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name("../etc/passwd")


def test_validate_name_rejects_slash() -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name("foo/bar")


def test_validate_name_accepts_dot_inside_stem() -> None:
    # 2026-04-29: dot is now allowed mid-stem so operators can use
    # date-style names like "04.29_1". Leading dot remains rejected.
    M.validate_name("04.29_1")
    M.validate_name("foo.pgm")  # silly but valid; SPA may warn about ext


def test_validate_name_accepts_parens() -> None:
    M.validate_name("studio(1)")
    M.validate_name("backup(test)")


def test_validate_name_rejects_hidden_dot_prefix() -> None:
    with pytest.raises(M.InvalidName):
        M.validate_name(".hidden")


def test_validate_name_accepts_reserved_active_at_regex_layer() -> None:
    # The reserved-name check is at the public-function layer, NOT inside
    # validate_name itself. Pinning this contract lets a future caller
    # (e.g. read_active_name) call validate_name without spuriously
    # rejecting the reserved string.
    M.validate_name("active")


# --- pgm_for / yaml_for / is_pair_present ------------------------------


def test_pgm_for_returns_path_inside_maps_dir(tmp_path: Path) -> None:
    p = M.pgm_for(tmp_path, _NAME_GOOD)
    assert p == tmp_path / "studio_v1.pgm"


def test_yaml_for_returns_path_inside_maps_dir(tmp_path: Path) -> None:
    p = M.yaml_for(tmp_path, _NAME_GOOD)
    assert p == tmp_path / "studio_v1.yaml"


def test_realpath_containment_rejects_symlink_targeting_outside_maps_dir(
    tmp_path: Path,
) -> None:
    # Mode-A M1: a malicious symlink whose name passes the regex but whose
    # TARGET escapes maps_dir must be rejected at the maps.py layer, not
    # at the renderer. Without the realpath check, render_pgm_to_png
    # would happily read /etc/passwd (or any file the webctl uid can
    # read).
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    outside = tmp_path / "outside.pgm"
    outside.write_bytes(b"P5\n1 1\n255\n\x00")
    bad = maps_dir / "evil.pgm"
    bad.symlink_to(outside)
    with pytest.raises(M.InvalidName) as ei:
        M.pgm_for(maps_dir, "evil")
    assert "path_outside_maps_dir" in str(ei.value)


def test_is_pair_present_true_when_both_files_exist(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    assert M.is_pair_present(tmp_path, _NAME_GOOD) is True


def test_is_pair_present_false_when_yaml_missing(tmp_path: Path) -> None:
    pgm = tmp_path / f"{_NAME_GOOD}.pgm"
    _write_pgm(pgm)
    # yaml deliberately absent
    assert M.is_pair_present(tmp_path, _NAME_GOOD) is False


def test_is_pair_present_false_when_pgm_missing(tmp_path: Path) -> None:
    yaml = tmp_path / f"{_NAME_GOOD}.yaml"
    _write_yaml(yaml, f"{_NAME_GOOD}.pgm")
    assert M.is_pair_present(tmp_path, _NAME_GOOD) is False


# --- list_pairs --------------------------------------------------------


def test_list_pairs_empty_dir_returns_empty(tmp_path: Path) -> None:
    assert M.list_pairs(tmp_path) == []


def test_list_pairs_two_pairs_with_active_flag(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)
    M.set_active(tmp_path, _NAME_GOOD)
    entries = M.list_pairs(tmp_path)
    assert [e.name for e in entries] == [_NAME_GOOD, _NAME_GOOD_OTHER]
    assert entries[0].is_active is True
    assert entries[1].is_active is False


def test_list_pairs_skips_partial_pgm_only(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    # Partial upload — pgm without yaml sibling
    _write_pgm(tmp_path / "studio_v3.pgm")
    entries = M.list_pairs(tmp_path)
    assert [e.name for e in entries] == [_NAME_GOOD]


def test_list_pairs_raises_when_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(M.MapsDirMissing):
        M.list_pairs(tmp_path / "no-such-dir")


def test_list_pairs_skips_active_symlink_target_from_listing(
    tmp_path: Path,
) -> None:
    # `active.pgm` is a symlink — list_pairs should never emit a
    # `MapEntry(name="active", ...)` row.
    _make_pair(tmp_path, _NAME_GOOD)
    M.set_active(tmp_path, _NAME_GOOD)
    entries = M.list_pairs(tmp_path)
    assert all(e.name != MAPS_ACTIVE_BASENAME for e in entries)


# --- read_active_name --------------------------------------------------


def test_read_active_name_returns_none_when_no_symlink(tmp_path: Path) -> None:
    assert M.read_active_name(tmp_path) is None


def test_read_active_name_returns_stem_after_set_active(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    M.set_active(tmp_path, _NAME_GOOD)
    assert M.read_active_name(tmp_path) == _NAME_GOOD


def test_read_active_name_returns_none_for_target_without_pgm_suffix(
    tmp_path: Path,
) -> None:
    # Hand-edited symlink whose basename does not end in `.pgm` —
    # operator broke things via SSH. We return None rather than raise.
    link = tmp_path / "active.pgm"
    link.symlink_to("studio_v1.txt")
    assert M.read_active_name(tmp_path) is None


def test_read_active_name_returns_none_for_target_with_bad_stem(
    tmp_path: Path,
) -> None:
    # Symlink target's stem fails MAPS_NAME_REGEX (e.g. starts with a
    # dot, or contains a forbidden char like whitespace). Returns None
    # rather than raising.
    link = tmp_path / "active.pgm"
    link.symlink_to(".hidden.pgm")
    assert M.read_active_name(tmp_path) is None


# --- set_active happy + reserved + missing -----------------------------


def test_set_active_creates_both_symlinks(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    M.set_active(tmp_path, _NAME_GOOD)
    assert os.readlink(tmp_path / "active.pgm") == "studio_v1.pgm"
    assert os.readlink(tmp_path / "active.yaml") == "studio_v1.yaml"


def test_set_active_repoints_both_symlinks(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)
    M.set_active(tmp_path, _NAME_GOOD)
    M.set_active(tmp_path, _NAME_GOOD_OTHER)
    assert os.readlink(tmp_path / "active.pgm") == "studio_v2.pgm"
    assert os.readlink(tmp_path / "active.yaml") == "studio_v2.yaml"


def test_set_active_rejects_unknown_name(tmp_path: Path) -> None:
    with pytest.raises(M.MapNotFound):
        M.set_active(tmp_path, "no_such_map")


def test_set_active_rejects_reserved_active_name(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    with pytest.raises(M.InvalidName) as ei:
        M.set_active(tmp_path, MAPS_ACTIVE_BASENAME)
    assert "reserved_name" in str(ei.value)


def test_set_active_rejects_invalid_regex_name(tmp_path: Path) -> None:
    with pytest.raises(M.InvalidName):
        M.set_active(tmp_path, "../etc")


def test_set_active_rejects_when_maps_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(M.MapsDirMissing):
        M.set_active(tmp_path / "ghost", _NAME_GOOD)


# --- M3: sweep stale tmp leftovers ------------------------------------


def test_set_active_sweeps_stale_tmp_leftovers(tmp_path: Path) -> None:
    # Pre-seed two stale tmp symlinks (as if a prior crashed swap left
    # them) then call set_active and verify they are gone afterwards.
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)
    stale_a = tmp_path / ".active.deadbeef.pgm.tmp"
    stale_b = tmp_path / ".active.cafebabe.yaml.tmp"
    stale_a.symlink_to("studio_v1.pgm")
    stale_b.symlink_to("studio_v1.yaml")
    M.set_active(tmp_path, _NAME_GOOD_OTHER)
    assert not stale_a.exists()
    assert not stale_b.exists()
    # And the swap itself succeeded.
    assert os.readlink(tmp_path / "active.pgm") == "studio_v2.pgm"


# --- Crash-mid-swap (TB1) ---------------------------------------------


def test_set_active_crash_mid_yaml_swap_leaves_recoverable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mode-A TB1: simulate os.replace raising AFTER the PGM swap and
    # BEFORE the YAML swap commits. Assert (a) PGM new, YAML untouched,
    # (b) lock released (next set_active works), (c) leftover tmp
    # symlinks get swept by the next set_active (M3).
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)
    M.set_active(tmp_path, _NAME_GOOD)

    real_replace = os.replace
    state = {"calls": 0}

    def flaky_replace(src: object, dst: object) -> None:
        state["calls"] += 1
        if state["calls"] == 2:
            # The 2nd replace is the YAML swap; raise after the PGM
            # swap has already succeeded.
            raise OSError(28, "ENOSPC simulated")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError):
        M.set_active(tmp_path, _NAME_GOOD_OTHER)
    monkeypatch.setattr(os, "replace", real_replace)

    # PGM swapped to v2, YAML still v1 (mismatched pair — operator's
    # next attempt fixes it).
    assert os.readlink(tmp_path / "active.pgm") == "studio_v2.pgm"
    assert os.readlink(tmp_path / "active.yaml") == "studio_v1.yaml"

    # Lock released: another set_active completes and sweeps the leftover.
    M.set_active(tmp_path, _NAME_GOOD_OTHER)
    assert os.readlink(tmp_path / "active.pgm") == "studio_v2.pgm"
    assert os.readlink(tmp_path / "active.yaml") == "studio_v2.yaml"
    leftovers = list(tmp_path.glob(".active.*.tmp"))
    assert leftovers == []


# --- TB3: concurrent activate serialized under flock --------------------


def test_set_active_serializes_under_flock(tmp_path: Path) -> None:
    # Mode-A TB3: thread A holds the flock for ~50 ms (we force this by
    # having it call an instrumented set_active that sleeps after
    # acquiring the lock); thread B starts 1 ms later. Assertions:
    #   (a) thread B's call returns ≥ 40 ms after start (proves it
    #       blocked on the flock), and
    #   (b) thread B's name wins (last-writer-wins under flock — B
    #       acquires after A releases), and
    #   (c) no .active.*.tmp leftovers remain.
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)

    # Thread A holds the SAME flock the implementation uses, then makes
    # its set_active call go through. Thread B, started after A has the
    # lock, MUST block on it.
    import fcntl

    a_holding = threading.Event()
    a_release_ok = threading.Event()
    b_done_at: list[float] = []
    b_started_at: list[float] = []
    b_error: list[BaseException] = []

    def thread_a() -> None:
        lock_path = tmp_path / MAPS_ACTIVATE_LOCK_BASENAME
        fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            a_holding.set()
            # Hold for 50 ms, then release.
            time.sleep(0.05)
            a_release_ok.set()
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def thread_b() -> None:
        # Wait until A holds the lock, plus 1 ms cushion, then call
        # set_active. The call should block on A's flock for the
        # remainder of A's hold window (~40 ms minimum).
        a_holding.wait(timeout=2.0)
        time.sleep(0.001)
        b_started_at.append(time.monotonic())
        try:
            M.set_active(tmp_path, _NAME_GOOD_OTHER)
        except BaseException as e:  # noqa: BLE001
            b_error.append(e)
        b_done_at.append(time.monotonic())

    ta = threading.Thread(target=thread_a)
    tb = threading.Thread(target=thread_b)
    ta.start()
    tb.start()
    ta.join(timeout=3.0)
    tb.join(timeout=3.0)

    assert not b_error, b_error
    assert b_started_at and b_done_at
    elapsed = b_done_at[0] - b_started_at[0]
    # Allow a 10 ms slop on the 50 ms hold window.
    assert elapsed >= 0.04, f"thread B did not block: elapsed={elapsed:.3f}s"
    # B is the only one that called set_active; it must have won.
    assert M.read_active_name(tmp_path) == _NAME_GOOD_OTHER
    # And no .active.*.tmp leftovers.
    leftovers = list(tmp_path.glob(".active.*.tmp"))
    assert leftovers == []
    # Sanity: a_release_ok was actually set (proving A reached its sleep).
    assert a_release_ok.is_set()


# --- delete_pair --------------------------------------------------------


def test_delete_pair_removes_both_files(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    _make_pair(tmp_path, _NAME_GOOD_OTHER)
    M.set_active(tmp_path, _NAME_GOOD)
    M.delete_pair(tmp_path, _NAME_GOOD_OTHER)
    assert not (tmp_path / "studio_v2.pgm").exists()
    assert not (tmp_path / "studio_v2.yaml").exists()


def test_delete_pair_refuses_active_map(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    M.set_active(tmp_path, _NAME_GOOD)
    with pytest.raises(M.MapIsActive):
        M.delete_pair(tmp_path, _NAME_GOOD)
    # Files must still be there.
    assert (tmp_path / "studio_v1.pgm").exists()
    assert (tmp_path / "studio_v1.yaml").exists()


def test_delete_pair_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(M.MapNotFound):
        M.delete_pair(tmp_path, "no_such_map")


def test_delete_pair_rejects_reserved_active_name(tmp_path: Path) -> None:
    with pytest.raises(M.InvalidName):
        M.delete_pair(tmp_path, MAPS_ACTIVE_BASENAME)


# --- migrate_legacy_active ---------------------------------------------


def test_migrate_legacy_active_copies_and_symlinks(tmp_path: Path) -> None:
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_pgm = legacy_dir / "studio_v1.pgm"
    legacy_yaml = legacy_dir / "studio_v1.yaml"
    _write_pgm(legacy_pgm)
    _write_yaml(legacy_yaml, "studio_v1.pgm")

    maps_dir = tmp_path / "maps"
    ran = M.migrate_legacy_active(maps_dir, legacy_pgm)
    assert ran is True
    assert (maps_dir / "studio_v1.pgm").exists()
    assert (maps_dir / "studio_v1.yaml").exists()
    assert os.readlink(maps_dir / "active.pgm") == "studio_v1.pgm"
    assert os.readlink(maps_dir / "active.yaml") == "studio_v1.yaml"


def test_migrate_legacy_active_inside_maps_dir_only_links(tmp_path: Path) -> None:
    # `legacy_pgm` is already in `maps_dir` — should not copy, only
    # create symlinks.
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir()
    _make_pair(maps_dir, _NAME_GOOD)
    legacy_pgm = maps_dir / "studio_v1.pgm"
    ran = M.migrate_legacy_active(maps_dir, legacy_pgm)
    assert ran is True
    assert os.readlink(maps_dir / "active.pgm") == "studio_v1.pgm"


def test_migrate_legacy_active_idempotent(tmp_path: Path) -> None:
    # First call migrates; second call sees existing active.pgm and
    # returns False without altering anything.
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    legacy_pgm = legacy_dir / "studio_v1.pgm"
    legacy_yaml = legacy_dir / "studio_v1.yaml"
    _write_pgm(legacy_pgm)
    _write_yaml(legacy_yaml, "studio_v1.pgm")

    maps_dir = tmp_path / "maps"
    assert M.migrate_legacy_active(maps_dir, legacy_pgm) is True
    assert M.migrate_legacy_active(maps_dir, legacy_pgm) is False


# --- MapEntry.to_dict (Mode-A N3 wire format) -------------------------


def test_map_entry_to_dict_uses_mtime_unix_float(tmp_path: Path) -> None:
    _make_pair(tmp_path, _NAME_GOOD)
    entries = M.list_pairs(tmp_path)
    assert len(entries) == 1
    d = entries[0].to_dict()
    # Operator UX 2026-05-02 KST: width_px / height_px / resolution_m
    # added so the SPA Map list can render `W×H px (X.X×Y.Y m)`.
    assert set(d.keys()) == {
        "name",
        "size_bytes",
        "mtime_unix",
        "is_active",
        "width_px",
        "height_px",
        "resolution_m",
    }
    assert isinstance(d["mtime_unix"], float)
    # Sanity: mtime_unix should be within a few seconds of now.
    assert abs(float(d["mtime_unix"]) - time.time()) < 60.0


# --- read_yaml_resolution (Operator UX 2026-05-02 KST) -----------------


def test_read_yaml_resolution_typical(tmp_path: Path) -> None:
    """Standard slam_toolbox YAML carries `resolution: <float>`."""
    p = tmp_path / "x.yaml"
    p.write_text(
        "image: x.pgm\nresolution: 0.025\norigin: [0, 0, 0]\n"
        "occupied_thresh: 0.65\nfree_thresh: 0.196\nnegate: 0\n",
    )
    assert M.read_yaml_resolution(p) == 0.025


def test_read_yaml_resolution_legacy_quarter(tmp_path: Path) -> None:
    """Pre-issue#13-cand maps carry `resolution: 0.05`."""
    p = tmp_path / "x.yaml"
    p.write_text("image: x.pgm\nresolution: 0.050\norigin: [0,0,0]\n")
    assert M.read_yaml_resolution(p) == 0.05


def test_read_yaml_resolution_with_inline_comment(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("resolution: 0.10  # 10cm/cell coarse\n")
    assert M.read_yaml_resolution(p) == 0.10


def test_read_yaml_resolution_missing_returns_none(tmp_path: Path) -> None:
    """Operator UX must NOT fail list_pairs when a YAML is malformed —
    return None and let the SPA show '—' for the dimension cell."""
    p = tmp_path / "x.yaml"
    p.write_text("image: x.pgm\norigin: [0,0,0]\n")
    assert M.read_yaml_resolution(p) is None


def test_read_yaml_resolution_non_numeric_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "x.yaml"
    p.write_text("resolution: not-a-number\n")
    assert M.read_yaml_resolution(p) is None


def test_read_yaml_resolution_missing_file_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "ghost.yaml"
    assert M.read_yaml_resolution(p) is None


def test_list_pairs_carries_dimensions_and_resolution(tmp_path: Path) -> None:
    """End-to-end: list_pairs populates width_px / height_px /
    resolution_m on every entry; the to_dict() exposes them."""
    _make_pair(tmp_path, _NAME_GOOD)
    entries = M.list_pairs(tmp_path)
    assert len(entries) == 1
    e = entries[0]
    # _write_pgm makes a 4×4 fill; _write_yaml uses resolution: 0.05.
    assert e.width_px == 4
    assert e.height_px == 4
    assert e.resolution_m == 0.05
    d = e.to_dict()
    assert d["width_px"] == 4
    assert d["height_px"] == 4
    assert d["resolution_m"] == 0.05


def test_list_pairs_tolerates_malformed_yaml_resolution(tmp_path: Path) -> None:
    """A YAML without a parseable `resolution:` line yields
    resolution_m=None — list_pairs still returns the entry."""
    pgm = tmp_path / f"{_NAME_GOOD}.pgm"
    yaml = tmp_path / f"{_NAME_GOOD}.yaml"
    pgm.write_bytes(b"P5\n8 8\n255\n" + bytes([0] * 64))
    yaml.write_text("image: x.pgm\norigin: [0,0,0]\n")  # no resolution line
    entries = M.list_pairs(tmp_path)
    assert len(entries) == 1
    assert entries[0].width_px == 8
    assert entries[0].height_px == 8
    assert entries[0].resolution_m is None


# --- read_pgm_dimensions (Track D scale fix) --------------------------


def test_read_pgm_dimensions_standard_header(tmp_path: Path) -> None:
    p = tmp_path / "x.pgm"
    p.write_bytes(b"P5\n200 100\n255\n" + bytes([0] * 100))
    assert M.read_pgm_dimensions(p) == (200, 100)


def test_read_pgm_dimensions_with_comment_line(tmp_path: Path) -> None:
    # Netpbm allows comment lines between magic and dimensions.
    p = tmp_path / "x.pgm"
    p.write_bytes(b"P5\n# created by slam_toolbox\n40 30\n255\n" + bytes([0] * 50))
    assert M.read_pgm_dimensions(p) == (40, 30)


def test_read_pgm_dimensions_zero_byte_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "empty.pgm"
    p.write_bytes(b"")
    with pytest.raises(M.PgmHeaderInvalid) as exc:
        M.read_pgm_dimensions(p)
    assert "missing_p5_magic" in str(exc.value)


def test_read_pgm_dimensions_no_p5_magic_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.pgm"
    p.write_bytes(b"NOTP5\n40 30\n255\n")
    with pytest.raises(M.PgmHeaderInvalid):
        M.read_pgm_dimensions(p)


def test_read_pgm_dimensions_non_numeric_width_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.pgm"
    p.write_bytes(b"P5\nabc 30\n255\n")
    with pytest.raises(M.PgmHeaderInvalid) as exc:
        M.read_pgm_dimensions(p)
    assert "non_numeric" in str(exc.value)


def test_read_pgm_dimensions_caps_read_at_pgm_header_max_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mode-A T4: byte-bound pin. The function must consume at most
    ``PGM_HEADER_MAX_BYTES`` from the file regardless of total size, so
    a 1 GB sparse PGM does not stream pixel data through Python.
    """
    from godo_webctl.constants import PGM_HEADER_MAX_BYTES

    p = tmp_path / "huge.pgm"
    # Sparse: 1 GB of zero pixels after a tiny header. `truncate` allocates
    # near-zero blocks on every filesystem GODO targets (ext4 / btrfs /
    # tmpfs on RPi 5 + CI). On a non-sparse FS (FAT32, some ZFS configs)
    # this would balloon to 1 GB — out of scope; we never deploy on those.
    header = b"P5\n200 100\n255\n"
    with p.open("wb") as f:
        f.write(header)
        f.truncate(len(header) + (1 << 30))

    # Spy on Path.open so we can record the read() byte counts.
    real_open = Path.open
    read_sizes: list[int] = []

    def spy_open(self: Path, *args: object, **kwargs: object) -> object:
        f = real_open(self, *args, **kwargs)
        real_read = f.read

        def spy_read(n: int = -1) -> bytes:
            read_sizes.append(n)
            return real_read(n)

        f.read = spy_read  # type: ignore[method-assign]
        return f

    monkeypatch.setattr(Path, "open", spy_open)

    assert M.read_pgm_dimensions(p) == (200, 100)
    # Exactly one read() call, capped at PGM_HEADER_MAX_BYTES.
    assert read_sizes == [PGM_HEADER_MAX_BYTES]


# --- issue#28 — pristine vs derived classification --------------------


def test_is_pristine_classifies_basic_name() -> None:
    assert M.is_pristine("chroma") is True
    assert M.is_pristine("studio_v1") is True


def test_is_pristine_classifies_derived_name() -> None:
    assert M.is_pristine("chroma.20260504-143012-foo") is False
    assert M.is_pristine("studio_v1.20260101-000000-bar") is False


def test_is_pristine_rejects_derived_lookalike() -> None:
    """C7-adjacent: a hand-edited name that LOOKS derived but lacks the
    full 8-6-memo triple stays classified as pristine. Critical because
    the operator might name a manual experimental save `chroma.notes`
    — that should be treated as its own pristine, not a phantom variant
    of `chroma`."""
    assert M.is_pristine("chroma.notes") is True
    assert M.is_pristine("chroma.2026") is True
    assert M.is_pristine("chroma.20260504-foo") is True


def test_derived_base_returns_pristine_root() -> None:
    assert M.derived_base("chroma.20260504-143012-foo") == "chroma"


def test_derived_base_returns_none_for_pristine() -> None:
    assert M.derived_base("chroma") is None


def test_validate_memo_accepts_letters_digits_dash_underscore() -> None:
    M.validate_memo("foo")
    M.validate_memo("foo_bar")
    M.validate_memo("foo-bar-1")
    M.validate_memo("a")


def test_validate_memo_rejects_dot() -> None:
    with pytest.raises(M.InvalidMemo):
        M.validate_memo("foo.bar")


def test_validate_memo_rejects_spaces() -> None:
    with pytest.raises(M.InvalidMemo):
        M.validate_memo("foo bar")


def test_validate_memo_rejects_empty() -> None:
    with pytest.raises(M.InvalidMemo):
        M.validate_memo("")


def test_validate_memo_rejects_too_long() -> None:
    with pytest.raises(M.InvalidMemo):
        M.validate_memo("a" * 33)


def test_derive_name_uses_provided_ts() -> None:
    name = M.derive_name("chroma", "wallcal01", ts="20260504-143000")
    assert name == "chroma.20260504-143000-wallcal01"


def test_derive_name_validates_memo() -> None:
    with pytest.raises(M.InvalidMemo):
        M.derive_name("chroma", "bad memo", ts="20260504-143000")


def test_derive_name_validates_base() -> None:
    with pytest.raises(M.InvalidName):
        M.derive_name(".hidden", "memo", ts="20260504-143000")


# --- issue#28 — list_pairs_grouped ------------------------------------


def test_list_pairs_grouped_pristine_with_no_variants(tmp_path: Path) -> None:
    """Zero-children case (test-gap fold)."""
    _make_pair(tmp_path, "chroma")
    groups = M.list_pairs_grouped(tmp_path)
    assert len(groups) == 1
    assert groups[0].base == "chroma"
    assert groups[0].pristine is not None
    assert groups[0].variants == []


def test_list_pairs_grouped_indents_variants(tmp_path: Path) -> None:
    _make_pair(tmp_path, "chroma")
    _make_pair(tmp_path, "chroma.20260504-143000-wallcal01")
    _make_pair(tmp_path, "chroma.20260504-150000-wallcal02")
    groups = M.list_pairs_grouped(tmp_path)
    assert len(groups) == 1
    g = groups[0]
    assert g.base == "chroma"
    assert g.pristine is not None
    assert [v.name for v in g.variants] == [
        "chroma.20260504-143000-wallcal01",
        "chroma.20260504-150000-wallcal02",
    ]


def test_list_pairs_grouped_orphan_variant_is_listed(tmp_path: Path) -> None:
    """If the operator hand-removed the pristine but kept derived,
    surface the group with `pristine=None` so the SPA can warn."""
    _make_pair(tmp_path, "chroma.20260504-143000-foo")
    groups = M.list_pairs_grouped(tmp_path)
    assert len(groups) == 1
    g = groups[0]
    assert g.base == "chroma"
    assert g.pristine is None
    assert [v.name for v in g.variants] == ["chroma.20260504-143000-foo"]
