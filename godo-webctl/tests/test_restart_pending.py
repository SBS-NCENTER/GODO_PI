"""
Track B-CONFIG (PR-CONFIG-β) — `restart_pending.is_pending` semantics.
"""

from __future__ import annotations

import os
from pathlib import Path

from godo_webctl import restart_pending


def test_returns_false_when_path_missing(tmp_path: Path) -> None:
    flag = tmp_path / "no_such_flag"
    assert restart_pending.is_pending(flag) is False


def test_returns_true_when_file_exists(tmp_path: Path) -> None:
    flag = tmp_path / "rp"
    flag.write_text("")  # empty file is fine; presence is sufficient
    assert restart_pending.is_pending(flag) is True


def test_returns_true_with_content(tmp_path: Path) -> None:
    """Tracker writes ``YYYY-MM-DDTHH:MM:SS\\n`` payload; we only check
    presence, content is informational."""
    flag = tmp_path / "rp"
    flag.write_text("2026-04-29T10:00:00\n")
    assert restart_pending.is_pending(flag) is True


def test_fail_closed_on_oserror(tmp_path: Path, monkeypatch) -> None:
    """If `Path.exists()` raises (e.g. EPERM on a pristine deployment
    without /var/lib/godo permissions), the helper returns False rather
    than letting the OS error propagate."""
    flag = tmp_path / "rp"

    def _raise(_self: Path) -> bool:
        raise OSError("EPERM")

    monkeypatch.setattr(Path, "exists", _raise)
    assert restart_pending.is_pending(flag) is False


def test_returns_false_for_directory(tmp_path: Path) -> None:
    """A directory at the flag path is also "exists" — that's the
    documented operator-visible behaviour. We pin it so future
    operators reading the test know about the tier-stricter check
    needed if they ever want to reject directories."""
    d = tmp_path / "dir"
    d.mkdir()
    # Path.exists() returns True for directories — same as files.
    assert restart_pending.is_pending(d) is True
    # Belt-and-suspenders: stat works.
    assert os.path.exists(d)
