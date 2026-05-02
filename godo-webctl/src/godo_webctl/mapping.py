"""
issue#14 — Mapping pipeline mode coordinator.

Single source of truth for "is mapping in progress?" Webctl owns this
state (D1) — the C++ tracker UDS surface is NOT extended. State is
persisted to ``<cfg.mapping_runtime_dir>/state.json`` (atomic
tmp+rename) so a webctl restart mid-mapping reconciles cleanly with
``docker inspect`` (M3 — `started_at` preserved across reconcile).

State machine (see plan §10):

    Idle ─► Starting ─► Running ─► Stopping ─► Idle
                ╲           ╲           ╲
                 ╲           ╲           ╲ stop_timeout
                  ╲           ╲           ╲
                   ╲           ╲           ▼
                    ╲           ▼          Failed
                     ╲          Failed (crash)
                      ▼
                      Failed (image_missing /
                              tracker_stop_failed /
                              container_start_timeout)

Public API:
    - ``MappingState`` enum
    - ``MappingStatus`` dataclass (mirrors `protocol.MAPPING_STATUS_FIELDS`)
    - ``start(name, cfg)`` — Idle → Starting (with side-effects)
    - ``stop(cfg)`` — Running/Starting/Failed → Idle/Stopping
    - ``status(cfg)`` — read current state with `docker inspect` reconcile
    - ``preview_path(cfg, name)`` — realpath-contained preview PGM path
    - ``journal_tail(cfg, n)`` — last N journal lines for the active unit
    - ``monitor_snapshot(cfg)`` — one-shot Docker stats + df + du

Concurrency: webctl runs single-worker (invariant (e)). All transitions
serial. Defence-in-depth ``flock`` on ``<runtime_dir>/.lock`` so a future
multi-worker writer cannot interleave start/stop. The state.json single-
writer rule is webctl uvicorn worker; reads from elsewhere are tolerated.
"""

from __future__ import annotations

import contextlib
import enum
import errno
import fcntl
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import services as services_mod
from . import webctl_toml as webctl_toml_mod
from .config import Settings
from .constants import (
    MAPPING_CONTAINER_NAME,
    MAPPING_CONTAINER_START_TIMEOUT_S,
    MAPPING_CP210X_RECOVER_ENV_FILENAME,
    MAPPING_CP210X_RECOVER_TIMEOUT_S,
    MAPPING_DOCKER_INSPECT_POLL_S,
    MAPPING_DOCKER_INSPECT_TIMEOUT_S,
    MAPPING_DOCKER_STATS_TIMEOUT_S,
    MAPPING_JOURNAL_TAIL_DEFAULT_N,
    MAPPING_JOURNAL_TAIL_MAX_N,
    MAPPING_NAME_MAX_LEN,
    MAPPING_NAME_REGEX,
    MAPPING_PREVIEW_SUBDIR,
    MAPPING_RESERVED_NAMES,
    MAPPING_STATE_REREAD_INTERVAL_S,
    MAPPING_UNIT_NAME,
)
from .protocol import (
    PRECHECK_CHECK_FIELDS,
    PRECHECK_CHECK_NAMES,
    PRECHECK_DISK_FREE_MIN_MB,
)

# issue#16 — sysfs USB path validator. Format `<bus>-<port[.port]*>` per
# Linux USB sysfs INTERFACE notation: `<bus>-<port-chain>:<config>.<intf>`
# (e.g. "1-1.4:1.0", "3-2:1.0", "2-1.4.1:2.3"). The cp210x driver is a
# USB interface driver — its `/sys/bus/usb/drivers/cp210x/{bind,unbind}`
# files require interface notation, NOT bare device notation
# (`<bus>-<port-chain>` like `1-1.4`). Issue#16 HIL hot-fix v4
# (2026-05-02 KST): v1/v2/v3 stripped the `:<config>.<intf>` suffix and
# the kernel rejected the resulting bare device name with `write error:
# No such device`. Fix: keep the whole interface segment.
_USB_PATH_REGEX: re.Pattern[str] = re.compile(r"^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$")

# issue#16 — name of the systemd oneshot unit that runs the cp210x
# unbind/rebind helper script. Mirrors the polkit rule (d) in
# `production/RPi5/systemd/49-godo-systemctl.rules`.
_CP210X_RECOVER_UNIT: str = "godo-cp210x-recover.service"

logger = logging.getLogger("godo_webctl.mapping")


# --- State enum + dataclass ----------------------------------------------


class MappingState(enum.StrEnum):
    """Canonical state-machine values. ``StrEnum`` keeps JSON shape
    identical to the protocol mirror without manual conversions."""

    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


@dataclass(frozen=True)
class MappingStatus:
    """Wire shape of GET /api/mapping/status. Field order matches
    ``protocol.MAPPING_STATUS_FIELDS`` exactly."""

    state: MappingState
    map_name: str | None
    container_id_short: str | None
    started_at: str | None  # ISO 8601 UTC
    error_detail: str | None
    journal_tail_available: bool

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = asdict(self)
        # Convert enum to its string value for JSON.
        d["state"] = self.state.value
        return d


# --- Exception hierarchy -------------------------------------------------


class MappingError(Exception):
    """Base for all mapping coordinator errors."""


class InvalidName(MappingError):
    """Name fails MAPPING_NAME_REGEX or is reserved."""


class NameAlreadyExists(MappingError):
    """A `<name>.pgm` or `<name>.yaml` already exists in maps_dir."""


class TrackerStopFailed(MappingError):
    """`systemctl stop godo-tracker` returned non-zero."""


class ImageMissing(MappingError):
    """`docker image inspect <tag>` returned non-zero (image not built)."""


class DockerUnavailable(MappingError):
    """Docker daemon unreachable / permission denied on docker.sock."""


class ContainerStartTimeout(MappingError):
    """Container did not reach `running` within MAPPING_CONTAINER_START_TIMEOUT_S."""


class ContainerStopTimeout(MappingError):
    """Container did not exit within MAPPING_CONTAINER_STOP_TIMEOUT_S."""


class NoActiveMapping(MappingError):
    """Operator stopped/queried while state == Idle."""


class MappingAlreadyActive(MappingError):
    """A second start request arrived while state ∈ {Starting, Running, Stopping}."""


class StateFileCorrupt(MappingError):
    """state.json could not be parsed; recovery is to delete + restart Idle."""


# --- issue#16 — cp210x recovery exceptions -------------------------------


class CP210xRecoveryFailed(MappingError):
    """`systemctl start godo-cp210x-recover.service` returned non-zero,
    OR the env file write failed mid-flight. Webctl maps to 500."""


class LidarPortNotResolvable(MappingError):
    """Could not resolve `cfg.serial.lidar_port` to a sysfs USB path
    (the symlink target was malformed, the regex rejected the output,
    or the device file was missing). Webctl maps to 400 — operator
    needs to either re-plug the LiDAR or fix the lidar_port config
    before retry."""


# --- Validation ----------------------------------------------------------


def validate_name(name: str) -> None:
    """Raise InvalidName if `name` is empty, too long, regex-rejected, or reserved.

    Reserved-name check runs FIRST so the error message disambiguates
    `"."` / `".."` / `"active"` from a generic regex miss.
    """
    if name in MAPPING_RESERVED_NAMES:
        raise InvalidName(f"reserved_name: {name!r}")
    if not name:
        raise InvalidName("empty_name")
    if len(name) > MAPPING_NAME_MAX_LEN:
        raise InvalidName(f"name_too_long: {len(name)} > {MAPPING_NAME_MAX_LEN}")
    if not MAPPING_NAME_REGEX.match(name):
        raise InvalidName(f"invalid_name: {name!r}")


def _check_inside_maps_dir(result: Path, maps_dir: Path) -> None:
    """realpath containment — never `assert` (production may run with -O)."""
    real_result = os.path.realpath(result)
    real_root = os.path.realpath(maps_dir)
    if not real_result.startswith(real_root + os.sep):
        raise InvalidName("path_outside_maps_dir")


def preview_path(cfg: Settings, name: str) -> Path:
    """Return the realpath-contained `<name>.pgm` under `.preview/`.

    Raises InvalidName on regex / reserved / containment failure.
    """
    validate_name(name)
    out = cfg.maps_dir / MAPPING_PREVIEW_SUBDIR / f"{name}.pgm"
    _check_inside_maps_dir(out, cfg.maps_dir)
    return out


# --- State persistence ---------------------------------------------------


def _state_file_path(cfg: Settings) -> Path:
    return cfg.mapping_runtime_dir / "state.json"


def _runtime_lock_path(cfg: Settings) -> Path:
    return cfg.mapping_runtime_dir / ".lock"


def _envfile_path(cfg: Settings) -> Path:
    # D4: instance name fixed to `active`; the unit's
    # EnvironmentFile=/run/godo/mapping/%i.env resolves to active.env.
    return cfg.mapping_runtime_dir / "active.env"


def _ensure_runtime_dir(cfg: Settings) -> None:
    """Create `mapping_runtime_dir` lazily (M2 fix — /run is tmpfs).

    webctl is launched with `ReadWritePaths=/run/godo` so this mkdir
    succeeds without elevation. Mode 0o750 keeps the envfile (which
    contains LIDAR_DEV / IMAGE_TAG only — no secrets — but defence in
    depth is cheap) readable by the systemd unit's User=ncenter.
    """
    cfg.mapping_runtime_dir.mkdir(parents=True, exist_ok=True, mode=0o750)


def _load_state(cfg: Settings) -> MappingStatus:
    """Read state.json or default to Idle. Corrupt JSON raises
    StateFileCorrupt; the app handler maps to 500 with explicit detail.

    Boundary contract (M3): `started_at` is preserved verbatim; never
    rewritten by this loader.
    """
    p = _state_file_path(cfg)
    if not p.exists():
        return _idle_status()
    try:
        raw = p.read_text("utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        raise StateFileCorrupt(f"failed to parse {p}: {e}") from e
    state_str = data.get("state")
    if state_str not in {s.value for s in MappingState}:
        raise StateFileCorrupt(f"unknown state: {state_str!r}")
    return MappingStatus(
        state=MappingState(state_str),
        map_name=data.get("map_name"),
        container_id_short=data.get("container_id_short"),
        started_at=data.get("started_at"),
        error_detail=data.get("error_detail"),
        journal_tail_available=bool(data.get("journal_tail_available", False)),
    )


def _save_state(cfg: Settings, status: MappingStatus) -> None:
    """Atomic write of state.json. Caller is the SOLE writer (webctl
    uvicorn single-worker)."""
    _ensure_runtime_dir(cfg)
    target = _state_file_path(cfg)
    tmp_name = f".state.{secrets.token_hex(4)}.json.tmp"
    tmp = cfg.mapping_runtime_dir / tmp_name
    body = json.dumps(status.to_dict(), ensure_ascii=False, separators=(",", ":"))
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _idle_status() -> MappingStatus:
    return MappingStatus(
        state=MappingState.IDLE,
        map_name=None,
        container_id_short=None,
        started_at=None,
        error_detail=None,
        journal_tail_available=False,
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Tracker-owned [serial] section reader -------------------------------


def _resolve_lidar_port(cfg: Settings) -> str:
    """Read the tracker-owned `[serial] lidar_port` key (canonical dotted
    name `serial.lidar_port`, verified at
    `production/RPi5/src/core/config_schema.hpp:120`).

    Falls back to the schema default when the file/section is absent.
    Re-raises WebctlTomlError on malformed TOML so the start handler
    can surface a clear error instead of silently using the default.
    """
    section = webctl_toml_mod.read_tracker_serial_section(cfg.tracker_toml_path)
    return section.lidar_port


# --- Subprocess wrappers --------------------------------------------------


def _run_subprocess(
    argv: list[str],
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    """Thin wrapper around subprocess.run that translates timeout +
    PermissionError uniformly. Caller handles non-zero returncode."""
    try:
        return subprocess.run(  # noqa: S603 — argv is a list, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise DockerUnavailable(f"timeout: {' '.join(argv[:3])}") from e
    except PermissionError as e:
        raise DockerUnavailable(f"permission_denied: {e}") from e
    except FileNotFoundError as e:
        raise DockerUnavailable(f"binary_not_found: {argv[0]}") from e


def _docker_inspect_state(cfg: Settings, container: str) -> str | None:
    """Returns the State.Status string ("running", "exited", ...) or None
    if no such container."""
    argv = [
        str(cfg.docker_bin),
        "inspect",
        "--format",
        "{{.State.Status}}",
        container,
    ]
    proc = _run_subprocess(argv, MAPPING_DOCKER_INSPECT_TIMEOUT_S)
    if proc.returncode != 0:
        # Distinguish "no such container" (success-shape) from real failure.
        if "No such" in proc.stderr or "no such" in proc.stderr.lower():
            return None
        # Permission denied → docker_unavailable not "container missing".
        if "permission denied" in proc.stderr.lower():
            raise DockerUnavailable(proc.stderr.strip())
        # Anything else: treat as "container does not exist" defensively;
        # the start path's polling will retry.
        return None
    return proc.stdout.strip() or None


def _docker_inspect_container_id_short(cfg: Settings, container: str) -> str | None:
    argv = [
        str(cfg.docker_bin),
        "inspect",
        "--format",
        "{{.Id}}",
        container,
    ]
    proc = _run_subprocess(argv, MAPPING_DOCKER_INSPECT_TIMEOUT_S)
    if proc.returncode != 0:
        return None
    full_id = proc.stdout.strip()
    return full_id[:12] if full_id else None


def _docker_image_inspect(cfg: Settings, tag: str) -> bool:
    """Returns True if the image exists locally."""
    argv = [str(cfg.docker_bin), "image", "inspect", tag]
    proc = _run_subprocess(argv, MAPPING_DOCKER_INSPECT_TIMEOUT_S)
    if proc.returncode == 0:
        return True
    err = (proc.stderr or "").lower()
    if "no such image" in err or "not found" in err:
        return False
    if "permission denied" in err:
        raise DockerUnavailable(proc.stderr.strip())
    # Other failures: treat as missing for the explicit 412 path.
    return False


def _docker_stats_oneshot(cfg: Settings, container: str) -> dict[str, Any] | None:
    """Returns parsed `docker stats --no-stream --format '{{json .}}'`
    output or None when the container is gone."""
    argv = [
        str(cfg.docker_bin),
        "stats",
        "--no-stream",
        "--format",
        "{{json .}}",
        container,
    ]
    proc = _run_subprocess(argv, MAPPING_DOCKER_STATS_TIMEOUT_S)
    if proc.returncode != 0:
        # Container not running / not present → graceful None.
        if "no such" in (proc.stderr or "").lower():
            return None
        if "permission denied" in (proc.stderr or "").lower():
            raise DockerUnavailable(proc.stderr.strip())
        return None
    line = proc.stdout.strip().splitlines()
    if not line:
        return None
    try:
        return json.loads(line[0])
    except json.JSONDecodeError:
        return None


# --- Envfile writer (atomic) ---------------------------------------------


def _write_run_envfile(cfg: Settings, name: str, lidar_port: str, image_tag: str) -> None:
    """Atomic-write `<runtime_dir>/active.env` for the systemd unit's
    EnvironmentFile= directive. Creates the parent dir on first call."""
    _ensure_runtime_dir(cfg)
    target = _envfile_path(cfg)
    tmp_name = f".active.{secrets.token_hex(4)}.env.tmp"
    tmp = cfg.mapping_runtime_dir / tmp_name
    body = (
        f"MAP_NAME={name}\n"
        f"LIDAR_DEV={lidar_port}\n"
        f"IMAGE_TAG={image_tag}\n"
    )
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


# --- Defence-in-depth flock ----------------------------------------------


@contextlib.contextmanager
def _coordinator_flock(cfg: Settings) -> Any:
    """fcntl.flock(LOCK_EX | LOCK_NB) — second start while one is in
    flight raises MappingAlreadyActive (mapped to 409 by the handler).
    Defence-in-depth in case a future writer enables multi-worker."""
    _ensure_runtime_dir(cfg)
    lock_path = _runtime_lock_path(cfg)
    fd = os.open(str(lock_path), os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise MappingAlreadyActive("flock_held") from e
        try:
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


# --- Public API ----------------------------------------------------------


def status(cfg: Settings) -> MappingStatus:
    """Read state.json and reconcile against `docker inspect`.

    M3 — `started_at` is NEVER rewritten on reconcile; it stays as the
    original Idle→Starting transition timestamp so
    ``journalctl --since=<started_at>`` keeps surfacing the launch
    window's logs after a webctl restart.
    """
    try:
        s = _load_state(cfg)
    except StateFileCorrupt:
        # Recovery: log + return Idle. The state file is intentionally
        # left in place so the operator can inspect it; the handler maps
        # this to 500 with explicit detail. We log so the journal trail
        # has the parse error.
        logger.exception("state.json corrupt; returning Idle")
        return _idle_status()

    if s.state in (MappingState.STARTING, MappingState.RUNNING, MappingState.STOPPING):
        # Reconcile: ask Docker for the container's actual state.
        try:
            inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
        except DockerUnavailable:
            # Docker daemon down — keep the persisted view. The SPA's
            # banner remains visible so the operator knows mapping was
            # in progress; manual `docker rm` recovery is the path.
            return s
        if inspect == "running":
            # In-flight; persisted state stays as-is.
            if s.state == MappingState.STOPPING:
                # Mid-stop; keep waiting.
                return s
            # Could be Starting (just reached running) or Running.
            # If state was Starting, transition to Running here so a
            # subsequent operator click sees the right disabled-state.
            if s.state == MappingState.STARTING:
                short_id = _docker_inspect_container_id_short(cfg, MAPPING_CONTAINER_NAME)
                new_status = MappingStatus(
                    state=MappingState.RUNNING,
                    map_name=s.map_name,
                    container_id_short=short_id or s.container_id_short,
                    started_at=s.started_at,  # M3: preserved
                    error_detail=None,
                    journal_tail_available=False,
                )
                _save_state(cfg, new_status)
                return new_status
            return s
        # issue#16 HIL hot-fix v6 (2026-05-02 KST) — Docker reports
        # "created" briefly between `docker run` and the entrypoint
        # actually executing, and "restarting" during a Restart= cycle.
        # Both are in-flight transient states, NOT "container gone".
        # Pre-v6 the reconcile collapsed any non-"running" inspect to
        # the gone-branch and wrote Failed("webctl_lost_view_post_crash"),
        # which races with Phase-2 polling on a cold start (operator t6
        # 22:54:47 KST 2026-05-02: 1Hz status polling caught the
        # "created" window before entrypoint reached "running" → false
        # Failed even though the container ran for >5 min healthily).
        #
        # Fix: keep persisted state for these transient values; the next
        # status() tick (or start()'s own Phase-2 polling) will reconcile
        # to "running" once the entrypoint executes. We do NOT silently
        # transition Starting→Running here, because that's start()'s job
        # under the coordinator flock — status() is read-mostly.
        if inspect in ("created", "restarting"):
            return s
        # Container gone — inspect returns None or "exited"/"dead"/
        # "removing"/"paused". Transition to Failed for Running
        # ("crashed") OR Idle for Stopping (clean stop) — but we cannot
        # tell from inspect-None alone whether a Stopping path was clean
        # vs aborted. Conservative: Stopping → Idle (no container is the
        # success-shape for stop), Running/Starting → Failed.
        if s.state == MappingState.STOPPING:
            new_status = _idle_status()
            _save_state(cfg, new_status)
            return new_status
        new_status = MappingStatus(
            state=MappingState.FAILED,
            map_name=s.map_name,
            container_id_short=s.container_id_short,
            started_at=s.started_at,  # M3: preserved for journal --since
            error_detail="webctl_lost_view_post_crash",
            journal_tail_available=True,
        )
        _save_state(cfg, new_status)
        return new_status
    return s


def start(name: str, cfg: Settings) -> MappingStatus:
    """Idle → Starting → Running (synchronous wait for `docker inspect == running`).

    issue#14 Maj-2 — refactored into 3 phases so a concurrent ``stop()``
    can interrupt a hung ``start()`` without blocking on a 409
    ``MappingAlreadyActive`` (the old code held ``_coordinator_flock``
    for the entire body, including the 8-s polling loop).

    Phase 1 (under flock): validate name + image pre-flight + state gate
    + write ``state.json`` ``{state: Starting, started_at: now()}``.
    Release flock.

    Phase 2 (no flock): tracker stop + write run envfile + systemctl
    start godo-mapping@active + poll ``docker inspect`` for ``running``.
    Each polling tick re-reads ``state.json``; if ``state == Stopping``
    (concurrent ``stop()`` fired), abort the polling loop and return —
    do NOT overwrite Stopping with Running.

    Phase 3 (under flock): re-check state.json. If still Starting,
    transition to Running and persist. If state changed to Stopping
    while we were polling, leave as-is (the concurrent ``stop()`` owns
    the transition).
    """
    import time

    validate_name(name)
    canonical_pgm = cfg.maps_dir / f"{name}.pgm"
    if canonical_pgm.exists():
        raise NameAlreadyExists(name)

    # --- Phase 1 (under flock) ---------------------------------------
    # State write + pre-flight only. NO subprocess work, NO polling,
    # NO long-running side-effects. The flock release at the end of
    # this block is what lets a concurrent stop() succeed mid-polling.
    with _coordinator_flock(cfg):
        current = _load_state(cfg)
        if current.state != MappingState.IDLE:
            raise MappingAlreadyActive(current.state.value)

        # Pre-flight: image present? Quick subprocess (~ms) — fine
        # under the flock. The expensive bits (tracker stop, systemctl
        # start, polling) all live in Phase 2.
        if not _docker_image_inspect(cfg, cfg.mapping_image_tag):
            raise ImageMissing(cfg.mapping_image_tag)

        # Persist Starting BEFORE side-effects so a webctl crash mid-
        # systemctl-start surfaces as a reconciled Failed on the next
        # boot.
        starting_status = MappingStatus(
            state=MappingState.STARTING,
            map_name=name,
            container_id_short=None,
            started_at=_utc_now_iso(),  # ONLY Idle→Starting writes a fresh now()
            error_detail=None,
            journal_tail_available=False,
        )
        _save_state(cfg, starting_status)
    # Flock released here. Concurrent stop() can now acquire it.

    # --- Phase 2 (no flock) ------------------------------------------
    # Side-effects: tracker stop, envfile write, systemctl start,
    # docker-inspect polling. We re-read state.json each polling tick;
    # if a concurrent stop() flipped it to Stopping, we abort early.

    # Step 1: stop the tracker. services.control raises various
    # exceptions; we map them to TrackerStopFailed for the SPA.
    try:
        services_mod.control("godo-tracker", "stop")
    except services_mod.ServicesError as e:
        failed_status = MappingStatus(
            state=MappingState.FAILED,
            map_name=name,
            container_id_short=None,
            started_at=starting_status.started_at,
            error_detail=f"tracker_stop_failed: {e}",
            journal_tail_available=False,
        )
        with _coordinator_flock(cfg):
            # Re-check: if a concurrent stop() ran, don't clobber its
            # transition.
            cur = _load_state(cfg)
            if cur.state == MappingState.STARTING:
                _save_state(cfg, failed_status)
        raise TrackerStopFailed(str(e)) from e

    # Step 2: resolve lidar_port + write envfile.
    try:
        lidar_port = _resolve_lidar_port(cfg)
    except webctl_toml_mod.WebctlTomlError as e:
        failed_status = MappingStatus(
            state=MappingState.FAILED,
            map_name=name,
            container_id_short=None,
            started_at=starting_status.started_at,
            error_detail=f"tracker_toml_parse_failed: {e}",
            journal_tail_available=False,
        )
        with _coordinator_flock(cfg):
            cur = _load_state(cfg)
            if cur.state == MappingState.STARTING:
                _save_state(cfg, failed_status)
        raise TrackerStopFailed(str(e)) from e
    try:
        _write_run_envfile(cfg, name, lidar_port, cfg.mapping_image_tag)
    except OSError as e:
        failed_status = MappingStatus(
            state=MappingState.FAILED,
            map_name=name,
            container_id_short=None,
            started_at=starting_status.started_at,
            error_detail=f"envfile_write_failed: {e}",
            journal_tail_available=False,
        )
        with _coordinator_flock(cfg):
            cur = _load_state(cfg)
            if cur.state == MappingState.STARTING:
                _save_state(cfg, failed_status)
        raise

    # Step 2.5: cp210x auto-recovery (issue#16 HIL hot-fix v5,
    # 2026-05-02 KST). Operator HIL on PR #69 surfaced two issues with
    # v2..v4's unconditional recovery:
    #
    #   (1) When the LiDAR is already healthy, unbind/rebind disrupts a
    #       working USB CDC link — operator quote 2026-05-02 evening:
    #       "지금 정상 상태인데 매번 recovery가 도네".
    #   (2) The recovery cycle adds ~1.5 s latency to every Start, even
    #       when not needed.
    #
    # v5 gate: only fire `recover_cp210x()` when `_check_lidar_readable()`
    # reports `ok=False`. The lidar_readable check probes `open()` on the
    # device file — a successful open means cp210x is bound and the
    # control endpoint responds; recovery would only churn it. A failed
    # open is the exact symptom recovery exists to fix (cp210x stale
    # state, sysfs in pending unbind, permission flap).
    #
    # The original cp210x stale state from v2's HIL evidence (`failed
    # set request 0x12 status: -110` after tracker stop) presents AS a
    # lidar_readable failure: the open() either ENODEV or hangs past
    # the O_NONBLOCK probe. So the gate correctly catches it.
    #
    # Best-effort: never fail Start because of recovery. If recovery
    # fails (polkit denied, helper missing, sysfs write rejected), the
    # original failure mode (rplidar timeout inside container) is
    # what we'd hit anyway — no worse than the pre-fix baseline.
    # Operator can disable via `[webctl] mapping_auto_recover_lidar =
    # false` in tracker.toml. Long-term path: issue#17 (GPIO UART
    # direct connection) removes the cp210x USB stack entirely.
    if cfg.mapping_auto_recover_lidar:
        lidar_check = _check_lidar_readable(cfg)
        if lidar_check.ok is True:
            logger.debug(
                "mapping.start: lidar_readable ok (%s), skipping cp210x recovery",
                lidar_check.value,
            )
        else:
            logger.info(
                "mapping.start: lidar_readable failed (%s), firing cp210x recovery",
                lidar_check.detail,
            )
            try:
                recover_cp210x(cfg)
            except (CP210xRecoveryFailed, LidarPortNotResolvable, OSError) as e:
                logger.warning(
                    "mapping.start: cp210x auto-recovery failed (best-effort, continuing): %s",
                    e,
                )

    # Step 3: systemctl start godo-mapping@active.service.
    # Polkit grants this verb (systemd PR-2 polkit rule extension).
    try:
        _run_systemctl_start_mapping(cfg)
    except (services_mod.ServicesError, DockerUnavailable, OSError) as e:
        failed_status = MappingStatus(
            state=MappingState.FAILED,
            map_name=name,
            container_id_short=None,
            started_at=starting_status.started_at,
            error_detail=f"systemctl_start_failed: {e}",
            journal_tail_available=True,
        )
        with _coordinator_flock(cfg):
            cur = _load_state(cfg)
            if cur.state == MappingState.STARTING:
                _save_state(cfg, failed_status)
        raise

    # Step 4: poll `docker inspect` until State.Status == "running".
    # Maj-2 critical: re-read state.json each tick to detect a concurrent
    # stop() that flipped Starting → Stopping outside our flock. If we
    # see Stopping mid-poll, abort the loop without writing Running —
    # the concurrent stop() owns the rest of the transition.
    elapsed = 0.0
    while elapsed < MAPPING_CONTAINER_START_TIMEOUT_S:
        inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
        if inspect == "running":
            # Container reached running. Commit to Running iff state.json
            # is still Starting (Phase 3 — under flock).
            short_id = _docker_inspect_container_id_short(
                cfg,
                MAPPING_CONTAINER_NAME,
            )
            with _coordinator_flock(cfg):
                # Mn3 fix (2026-05-02 KST) — defensive read mirrors the
                # Phase-2 polling loop semantic. If state.json is briefly
                # corrupt at this moment (FS hiccup, mid-write race that
                # _save_state's atomic os.replace SHOULD already prevent
                # but a future bug or external rm could break), the safest
                # action is to YIELD — log the corruption but do NOT
                # overwrite, since we cannot prove the operator has not
                # initiated a stop. The next status() call will re-derive
                # via _docker_inspect_state and either reconcile to
                # Running or to Failed("webctl_lost_view_post_crash").
                try:
                    cur = _load_state(cfg)
                except StateFileCorrupt as e:
                    logger.warning(
                        "mapping.start Phase 3: state.json corrupt; "
                        "yielding without overwriting Running. Detail: %s",
                        e,
                    )
                    return starting_status
                if cur.state != MappingState.STARTING:
                    # Concurrent stop() won the race; respect its transition.
                    return cur
                running_status = MappingStatus(
                    state=MappingState.RUNNING,
                    map_name=name,
                    container_id_short=short_id,
                    started_at=starting_status.started_at,
                    error_detail=None,
                    journal_tail_available=False,
                )
                _save_state(cfg, running_status)
                return running_status
        # Re-read state.json: did a concurrent stop() fire?
        try:
            cur_view = _load_state(cfg)
        except StateFileCorrupt:
            # Defensive: if the file is corrupt mid-polling, treat as
            # "no concurrent stop view" and keep polling.
            cur_view = starting_status
        if cur_view.state == MappingState.STOPPING:
            # Concurrent stop() owns the rest of the transition; bail
            # out cleanly without writing Running. Do NOT raise — stop()
            # will wait for container exit + write Idle.
            logger.info("start: concurrent stop detected mid-polling; "
                        "yielding to stop()")
            return cur_view
        time.sleep(MAPPING_STATE_REREAD_INTERVAL_S)
        elapsed += MAPPING_STATE_REREAD_INTERVAL_S

    # Timeout — defensive cleanup + Failed (Phase 3 under flock).
    with contextlib.suppress(Exception):
        _run_systemctl_stop_mapping(cfg)
    failed_status = MappingStatus(
        state=MappingState.FAILED,
        map_name=name,
        container_id_short=None,
        started_at=starting_status.started_at,
        error_detail="container_start_timeout",
        journal_tail_available=True,
    )
    with _coordinator_flock(cfg):
        cur = _load_state(cfg)
        if cur.state == MappingState.STARTING:
            _save_state(cfg, failed_status)
    raise ContainerStartTimeout(
        f"timeout after {MAPPING_CONTAINER_START_TIMEOUT_S}s",
    )


def stop(cfg: Settings) -> MappingStatus:
    """Running → Stopping → Idle. Failed → Idle (acknowledge).
    Starting → Stopping → Idle (operator abort, m10).

    Idle → 404 NoActiveMapping.
    Stopping → idempotent return of current state (200).

    issue#14 Maj-2 — refactored into 3 phases so a concurrent
    ``start()`` does not block this call. Phase 1 (under flock) writes
    Stopping; Phase 2 (no flock) runs systemctl stop + polls for
    container exit; Phase 3 (under flock) writes Idle.
    """
    import time

    # --- Phase 1 (under flock) ---------------------------------------
    # State decision + state write only. Acknowledge-Failed path runs
    # entirely here (no polling needed; the container is already gone).
    with _coordinator_flock(cfg):
        current = _load_state(cfg)
        if current.state == MappingState.IDLE:
            raise NoActiveMapping()
        if current.state == MappingState.STOPPING:
            return current
        if current.state == MappingState.FAILED:
            # Acknowledge: defensive `docker rm -f`; remove preview;
            # transition to Idle. Subprocess work IS held under the
            # flock here because there's nothing for a concurrent
            # caller to interrupt — the container is already gone and
            # no Phase-2 polling will run.
            with contextlib.suppress(Exception):
                _run_subprocess(
                    [str(cfg.docker_bin), "rm", "-f", MAPPING_CONTAINER_NAME],
                    MAPPING_DOCKER_INSPECT_TIMEOUT_S,
                )
            if current.map_name is not None:
                with contextlib.suppress(Exception):
                    p = preview_path(cfg, current.map_name)
                    if p.exists():
                        p.unlink()
            new_status = _idle_status()
            _save_state(cfg, new_status)
            return new_status

        # Starting or Running: transition to Stopping under flock so a
        # concurrent start()'s Phase-2 polling sees the new state on
        # its next state-reread tick.
        stopping_status = MappingStatus(
            state=MappingState.STOPPING,
            map_name=current.map_name,
            container_id_short=current.container_id_short,
            started_at=current.started_at,  # M3: preserved
            error_detail=None,
            journal_tail_available=False,
        )
        _save_state(cfg, stopping_status)
    # Flock released here. A concurrent start() that's in its Phase-2
    # polling loop will see the Stopping state on its next tick and
    # bail out without writing Running.

    # --- Phase 2 (no flock) ------------------------------------------
    # systemctl stop + poll for container exit.
    try:
        _run_systemctl_stop_mapping(cfg)
    except Exception as e:  # noqa: BLE001 — we log + continue to poll
        logger.warning("systemctl stop godo-mapping returned: %s", e)

    # Poll for container exit (gone / exited). issue#14 Maj-1 fold:
    # the deadline is now operator-tunable via
    # `webctl.mapping_webctl_stop_timeout_s` → cfg field. The raw
    # constant `MAPPING_CONTAINER_STOP_TIMEOUT_S` is the FALLBACK
    # default that lands in Settings when the [webctl] section is
    # silent (see config.py + webctl_toml.py).
    deadline_s = cfg.mapping_webctl_stop_timeout_s
    elapsed = 0.0
    container_exited = False
    while elapsed < deadline_s:
        inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
        if inspect is None or inspect == "exited":
            container_exited = True
            break
        time.sleep(MAPPING_DOCKER_INSPECT_POLL_S)
        elapsed += MAPPING_DOCKER_INSPECT_POLL_S

    # --- Phase 3 (under flock) ---------------------------------------
    if container_exited:
        # Clean stop. If we were Starting (no canonical PGM saved),
        # nothing to clean. Either way: Idle.
        with _coordinator_flock(cfg):
            new_status = _idle_status()
            _save_state(cfg, new_status)
        return new_status

    # Stop timeout — force-kill + Failed (preserve partial PGM per L11).
    with contextlib.suppress(Exception):
        _run_subprocess(
            [str(cfg.docker_bin), "kill", MAPPING_CONTAINER_NAME],
            MAPPING_DOCKER_INSPECT_TIMEOUT_S,
        )
    failed_status = MappingStatus(
        state=MappingState.FAILED,
        map_name=current.map_name,
        container_id_short=current.container_id_short,
        started_at=current.started_at,
        error_detail="container_stop_timeout",
        journal_tail_available=True,
    )
    with _coordinator_flock(cfg):
        _save_state(cfg, failed_status)
    raise ContainerStopTimeout(
        f"timeout after {deadline_s}s",
    )


def _run_systemctl_start_mapping(cfg: Settings) -> None:
    """systemctl start godo-mapping@active.service — wraps the timeout +
    permission paths uniformly. Caller maps to TrackerStopFailed-style
    Failed transitions if non-zero."""
    argv = ["systemctl", "start", "--no-pager", MAPPING_UNIT_NAME]
    proc = _run_subprocess(argv, services_mod.SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        raise services_mod.CommandFailed(proc.returncode, proc.stderr)


def _run_systemctl_stop_mapping(cfg: Settings) -> None:
    argv = ["systemctl", "stop", "--no-pager", MAPPING_UNIT_NAME]
    proc = _run_subprocess(argv, services_mod.SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        raise services_mod.CommandFailed(proc.returncode, proc.stderr)


# --- journal_tail / monitor_snapshot --------------------------------------


def journal_tail(cfg: Settings, n: int = MAPPING_JOURNAL_TAIL_DEFAULT_N) -> list[str]:
    """`journalctl -u godo-mapping@active.service -n <n> --since=<started_at>`.

    Filters by current state's `started_at` so only the active session's
    lines surface (defence against showing yesterday's failed run).
    Returns [] when no started_at (Idle).
    """
    if n <= 0:
        raise ValueError(f"n must be positive: {n}")
    if n > MAPPING_JOURNAL_TAIL_MAX_N:
        n = MAPPING_JOURNAL_TAIL_MAX_N
    s = status(cfg)
    if s.started_at is None:
        return []
    argv = [
        "journalctl",
        "-u",
        MAPPING_UNIT_NAME,
        "-n",
        str(n),
        "--no-pager",
        "--output=cat",
        f"--since={_iso_to_journal_since(s.started_at)}",
    ]
    proc = _run_subprocess(argv, services_mod.SUBPROCESS_TIMEOUT_S)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line]


def _iso_to_journal_since(iso_utc: str) -> str:
    """`journalctl --since=` accepts free-form date strings; the ISO-8601
    UTC stamp we emit is one of them. We pass it through verbatim — the
    `Z` suffix is interpreted as UTC by systemd 257 (Trixie)."""
    return iso_utc


def monitor_snapshot(cfg: Settings) -> dict[str, Any]:
    """One-shot Docker monitor frame. SSE producer in mapping_sse.py
    fans this out. Returns the wire shape pinned by
    `protocol.MAPPING_MONITOR_FIELDS`.

    Subprocess failures degrade gracefully: a missing docker stats
    yields `valid=False` with the relevant fields nulled; df / du
    failures null the corresponding bytes fields but keep the rest.
    """
    import time

    out: dict[str, Any] = {
        "valid": True,
        "container_id_short": None,
        "container_state": "no_active",
        "container_cpu_pct": None,
        "container_mem_bytes": None,
        "container_net_rx_bytes": None,
        "container_net_tx_bytes": None,
        "var_lib_godo_disk_avail_bytes": None,
        "var_lib_godo_disk_total_bytes": None,
        "in_progress_map_size_bytes": None,
        "published_mono_ns": time.monotonic_ns(),
    }
    try:
        inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
    except DockerUnavailable as e:
        out["valid"] = False
        out["container_state"] = "no_active"
        logger.debug("monitor_snapshot docker_unavailable: %s", e)
        return out

    if inspect is None:
        out["container_state"] = "no_active"
        return out
    if inspect != "running":
        out["container_state"] = "exited"
        return out

    out["container_state"] = "running"
    out["container_id_short"] = _docker_inspect_container_id_short(
        cfg,
        MAPPING_CONTAINER_NAME,
    )

    # Compose container CPU / mem / net from `docker stats`.
    stats = _docker_stats_oneshot(cfg, MAPPING_CONTAINER_NAME)
    if stats is not None:
        out["container_cpu_pct"] = _parse_pct(stats.get("CPUPerc"))
        out["container_mem_bytes"] = _parse_mem_usage(stats.get("MemUsage"))
        rx, tx = _parse_net_io(stats.get("NetIO"))
        out["container_net_rx_bytes"] = rx
        out["container_net_tx_bytes"] = tx

    # Disk free for /var/lib/godo (where the maps land).
    avail, total = _df_bytes(cfg.maps_dir)
    out["var_lib_godo_disk_avail_bytes"] = avail
    out["var_lib_godo_disk_total_bytes"] = total

    # In-progress preview file size — `du -sb` on the SINGLE PGM file
    # (not a directory) so traversal cost is bounded.
    s = status(cfg)
    if s.map_name is not None:
        with contextlib.suppress(Exception):
            preview = preview_path(cfg, s.map_name)
            if preview.exists():
                out["in_progress_map_size_bytes"] = preview.stat().st_size

    return out


def _parse_pct(raw: Any) -> float | None:
    """Parse '38.20%' → 38.2. None on malformed input."""
    if not isinstance(raw, str) or not raw:
        return None
    s = raw.strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_mem_usage(raw: Any) -> int | None:
    """Parse '432.4MiB / 7.42GiB' → 453_058_560 (MiB → bytes).
    None on malformed input.
    """
    if not isinstance(raw, str) or not raw:
        return None
    parts = raw.split("/")
    if not parts:
        return None
    used = parts[0].strip()
    return _parse_humanize_bytes(used)


def _parse_humanize_bytes(s: str) -> int | None:
    """Parse `{number}{unit}` strings emitted by `docker stats` like
    '432.4MiB', '1.2GB', '512B'. None on malformed input."""
    if not s:
        return None
    units = {
        "B": 1,
        "KB": 1000,
        "KIB": 1024,
        "MB": 1000**2,
        "MIB": 1024**2,
        "GB": 1000**3,
        "GIB": 1024**3,
        "TB": 1000**4,
        "TIB": 1024**4,
    }
    # Walk back to find the unit boundary.
    i = len(s)
    while i > 0 and not s[i - 1].isdigit() and s[i - 1] != ".":
        i -= 1
    num_part = s[:i].strip()
    unit_part = s[i:].strip().upper()
    try:
        value = float(num_part)
    except ValueError:
        return None
    mult = units.get(unit_part)
    if mult is None:
        return None
    return int(value * mult)


def _parse_net_io(raw: Any) -> tuple[int | None, int | None]:
    """Parse '12.3kB / 4.5kB' → (12300, 4500). (None, None) on malformed."""
    if not isinstance(raw, str) or not raw:
        return (None, None)
    parts = raw.split("/")
    if len(parts) != 2:
        return (None, None)
    rx = _parse_humanize_bytes(parts[0].strip())
    tx = _parse_humanize_bytes(parts[1].strip())
    return (rx, tx)


def _df_bytes(path: Path) -> tuple[int | None, int | None]:
    """Returns (avail_bytes, total_bytes) via os.statvfs. None on error."""
    try:
        st = os.statvfs(str(path))
    except (FileNotFoundError, OSError) as e:
        if e.errno == errno.ENOENT:
            return (None, None)
        return (None, None)
    avail = st.f_bavail * st.f_frsize
    total = st.f_blocks * st.f_frsize
    return (avail, total)


# --- issue#16 — pre-check + cp210x recovery -------------------------------
# Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.
# The 6 checks form a fixed-order tuple (PRECHECK_CHECK_NAMES); the SPA
# polls 1 Hz and gates the Start button on `ready=True`. The operator
# triggers cp210x recovery manually via the SPA when `lidar_readable`
# fails — recovery is NOT automatic.


@dataclass(frozen=True)
class PrecheckRow:
    """One row of the precheck `checks` array. `value` carries scalar
    auxiliary info (disk MiB, image tag); `detail` carries the failure
    reason string. Both default to None and are emitted as JSON null on
    the wire so the SPA's row renderer has a fixed shape per row.

    `ok=None` is the "pending" state — only used by `name_available`
    when the operator hasn't typed a name yet. Pending rows count as
    not-ready (so Start stays disabled) but are not "failure" red ✗.
    """

    name: str
    ok: bool | None
    value: int | str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class PrecheckResult:
    """Wire shape of GET /api/mapping/precheck. Field order matches
    `protocol.PRECHECK_FIELDS` exactly."""

    ready: bool
    checks: list[PrecheckRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "checks": [
                {f: getattr(row, f) for f in PRECHECK_CHECK_FIELDS} for row in self.checks
            ],
        }


def _check_lidar_readable(cfg: Settings) -> PrecheckRow:
    """Probe that the LiDAR device file responds to ``open()``.

    Semantics (operator-confirmed during issue#16 HIL): this check is a
    "device file alive + permission OK" probe, NOT an "in use by anyone
    else?" probe. Linux's tty driver does NOT honour ``O_EXCL`` at open
    time (POSIX leaves the flag undefined without ``O_CREAT``; the
    kernel ignores it on character devices), so a successful open here
    only tells us the cp210x driver responded and the file permissions
    permit access — godo-tracker holding the port concurrently does
    NOT cause this open to fail.

    The "is it free?" semantics live in ``_check_tracker_stopped``:
    when godo-tracker is the holder, that row is ✗ and the operator
    must stop the tracker before mapping can start. The lidar_readable
    row catches the OTHER class of failure: cable pulled, driver not
    loaded, sysfs in stale state preventing any open.

    ``O_NONBLOCK`` is set so the open does not wait for modem-state
    (carrier-detect) on a USB-serial adapter — without it, opening a
    tty whose CD line is low can block until a 60-s carrier-detect
    timeout. We close immediately on success; this is non-destructive.
    """
    try:
        lidar_port = _resolve_lidar_port(cfg)
    except webctl_toml_mod.WebctlTomlError as e:
        return PrecheckRow(
            name="lidar_readable",
            ok=False,
            value=None,
            detail=f"tracker_toml_parse_failed: {e}",
        )
    try:
        fd = os.open(lidar_port, os.O_RDWR | os.O_NONBLOCK)
    except OSError as e:
        return PrecheckRow(
            name="lidar_readable",
            ok=False,
            value=lidar_port,
            detail=errno.errorcode.get(e.errno, str(e.errno)) if e.errno else str(e),
        )
    # Close defensively; if the descriptor disappeared (EBADF) treat as
    # failure rather than success, since the device may have been pulled
    # between open + close.
    try:
        os.close(fd)
    except OSError as e:
        return PrecheckRow(
            name="lidar_readable",
            ok=False,
            value=lidar_port,
            detail=f"close_failed: {e}",
        )
    return PrecheckRow(name="lidar_readable", ok=True, value=lidar_port, detail=None)


def _check_tracker_stopped(cfg: Settings) -> PrecheckRow:
    """`systemctl is-active godo-tracker.service` must return inactive
    or failed before mapping can start (the tracker holds the LiDAR FD
    in active state).
    """
    argv = ["systemctl", "is-active", "--no-pager", "godo-tracker.service"]
    try:
        proc = subprocess.run(  # noqa: S603 — argv is a list, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=services_mod.SUBPROCESS_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return PrecheckRow(
            name="tracker_stopped",
            ok=False,
            value=None,
            detail="systemctl_timeout",
        )
    state = proc.stdout.strip() or "unknown"
    if state in ("inactive", "failed"):
        return PrecheckRow(name="tracker_stopped", ok=True, value=state, detail=None)
    return PrecheckRow(name="tracker_stopped", ok=False, value=state, detail=state)


def _check_image_present(cfg: Settings) -> PrecheckRow:
    """Reuses `_docker_image_inspect` so the precheck and the start path
    agree byte-for-byte on what "image present" means."""
    tag = cfg.mapping_image_tag
    try:
        present = _docker_image_inspect(cfg, tag)
    except DockerUnavailable as e:
        return PrecheckRow(
            name="image_present",
            ok=False,
            value=tag,
            detail=f"docker_unavailable: {e}",
        )
    if present:
        return PrecheckRow(name="image_present", ok=True, value=tag, detail=None)
    return PrecheckRow(
        name="image_present",
        ok=False,
        value=tag,
        detail="run docker build",
    )


def _check_disk_space_mb(cfg: Settings) -> PrecheckRow:
    """`shutil.disk_usage(maps_dir).free // 1024**2`. Reports MiB so the
    SPA can render "9500 MiB available" inline."""
    try:
        usage = shutil.disk_usage(str(cfg.maps_dir))
    except (FileNotFoundError, OSError) as e:
        return PrecheckRow(
            name="disk_space_mb",
            ok=False,
            value=None,
            detail=f"disk_usage_failed: {e}",
        )
    avail_mb = usage.free // (1024 * 1024)
    if avail_mb >= PRECHECK_DISK_FREE_MIN_MB:
        return PrecheckRow(
            name="disk_space_mb",
            ok=True,
            value=avail_mb,
            detail=None,
        )
    return PrecheckRow(
        name="disk_space_mb",
        ok=False,
        value=avail_mb,
        detail=f"need_at_least_{PRECHECK_DISK_FREE_MIN_MB}_mb",
    )


def _check_name_available(cfg: Settings, name: str | None) -> PrecheckRow:
    """`name=None` (or empty) → `ok=None` (pending — operator typing).
    Otherwise validate against the regex + reserved set + canonical PGM
    existence. Returns ok=False with the failure reason on regex/exists.
    """
    if not name:
        return PrecheckRow(name="name_available", ok=None, value=None, detail=None)
    try:
        validate_name(name)
    except InvalidName as e:
        return PrecheckRow(
            name="name_available",
            ok=False,
            value=name,
            detail=str(e),
        )
    if (cfg.maps_dir / f"{name}.pgm").exists():
        return PrecheckRow(
            name="name_available",
            ok=False,
            value=name,
            detail="name_exists",
        )
    return PrecheckRow(name="name_available", ok=True, value=name, detail=None)


def _check_state_clean(cfg: Settings) -> PrecheckRow:
    """Webctl's `status()` does the docker-inspect reconcile; we leverage
    it so a stale Starting/Running/Stopping state has already been
    reconciled before we read it. Idle == clean."""
    try:
        s = status(cfg)
    except MappingError as e:
        return PrecheckRow(
            name="state_clean",
            ok=False,
            value=None,
            detail=f"status_failed: {e}",
        )
    if s.state == MappingState.IDLE:
        return PrecheckRow(name="state_clean", ok=True, value="idle", detail=None)
    return PrecheckRow(
        name="state_clean",
        ok=False,
        value=s.state.value,
        detail=s.state.value,
    )


def precheck(cfg: Settings, name: str | None = None) -> PrecheckResult:
    """Run all 6 checks in fixed PRECHECK_CHECK_NAMES order and return
    a `PrecheckResult`.

    `ready` is `True` only when EVERY row is `ok is True`. A row with
    `ok is None` (name_available pending) keeps `ready=False`.
    """
    rows: list[PrecheckRow] = [
        _check_lidar_readable(cfg),
        _check_tracker_stopped(cfg),
        _check_image_present(cfg),
        _check_disk_space_mb(cfg),
        _check_name_available(cfg, name),
        _check_state_clean(cfg),
    ]
    # Defensive — pin order against the wire-side tuple.
    if tuple(r.name for r in rows) != PRECHECK_CHECK_NAMES:
        raise RuntimeError(
            f"precheck row-order drift: {tuple(r.name for r in rows)} "
            f"!= {PRECHECK_CHECK_NAMES}",
        )
    ready = all(r.ok is True for r in rows)
    return PrecheckResult(ready=ready, checks=rows)


def _resolve_usb_sysfs_path(lidar_port: str) -> str:
    """Resolve `/dev/ttyUSBn` → sysfs USB INTERFACE notation
    (e.g. "1-1.4:1.0", "3-2:1.0").

    The cp210x driver's `/sys/bus/usb/drivers/cp210x/{bind,unbind}`
    sysfs files expect USB interface notation
    (`<bus>-<port-chain>:<config>.<intf>`), NOT the bare USB device
    notation (`<bus>-<port-chain>`). Writing a bare device path
    yields `write error: No such device` — the kernel reports it
    because no cp210x driver is bound to that path level.

    issue#16 HIL hot-fix v4 (2026-05-02 KST): v1/v2/v3 stripped the
    `:<config>.<intf>` suffix and the recovery oneshot failed at
    every actual invocation. Diagnostic: operator HIL on v3 deploy
    surfaced `firing for lidar_port=/dev/ttyUSB0 usb_path=3-2` ⇒
    helper ran ⇒ kernel rejected `3-2`. Fix: keep the whole
    interface segment.

    Algorithm: `realpath()` the kernel symlink to absolute, walk
    segments tail-to-root, return the first segment matching
    `_USB_PATH_REGEX` (interface notation with `:<config>.<intf>`).
    Raises `LidarPortNotResolvable` if no segment matches.
    """
    tty_basename = os.path.basename(lidar_port)
    if not tty_basename:
        raise LidarPortNotResolvable(f"empty_basename: {lidar_port!r}")
    sysfs_link = f"/sys/class/tty/{tty_basename}/device"
    try:
        # `realpath` resolves the symlink fully into an absolute path
        # rooted at /sys, even when the link is relative.
        real_path = os.path.realpath(sysfs_link)
    except OSError as e:
        raise LidarPortNotResolvable(f"realpath_failed: {sysfs_link}: {e}") from e
    if not real_path or not real_path.startswith("/sys/"):
        raise LidarPortNotResolvable(f"unexpected_realpath: {real_path!r}")
    # Walk segments from tail to root; first interface-notation match
    # is the cp210x interface we want to bind/unbind.
    for segment in reversed(real_path.split(os.sep)):
        if not segment:
            continue
        if _USB_PATH_REGEX.match(segment):
            return segment
    raise LidarPortNotResolvable(f"no_usb_interface_segment_in_path: {real_path!r}")


def _write_cp210x_envfile(cfg: Settings, usb_path: str) -> Path:
    """Atomic-write `/run/godo/cp210x-recover.env` carrying USB_PATH=<x>.

    Lives one directory ABOVE `mapping_runtime_dir` (= /run/godo) since
    the recovery unit is not mapping-instance scoped. The systemd unit's
    EnvironmentFile= directive points at this absolute path.
    """
    parent = cfg.mapping_runtime_dir.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    target = parent / MAPPING_CP210X_RECOVER_ENV_FILENAME
    tmp_name = f".cp210x.{secrets.token_hex(4)}.env.tmp"
    tmp = parent / tmp_name
    body = f"USB_PATH={usb_path}\n"
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise
    return target


def recover_cp210x(cfg: Settings) -> None:
    """Resolve the LiDAR sysfs USB path, write the recovery envfile,
    invoke `systemctl start godo-cp210x-recover.service`.

    Two callers (issue#16 HIL hot-fix v2):
      1. Operator-driven via `POST /api/mapping/recover-lidar` — the
         SPA's "🔧 LiDAR USB 복구" button when precheck shows
         `lidar_readable=False`.
      2. Automatic during `mapping.start()` Phase 2 Step 2.5 — fires
         unconditionally before the systemd unit boot whenever
         `cfg.mapping_auto_recover_lidar` is true (default `True`).

    Raises `LidarPortNotResolvable` (mapped to 400 on the manual
    endpoint; logged + swallowed on the auto-recovery path) on any
    path-resolve failure; raises `CP210xRecoveryFailed` (mapped to
    500 / logged + swallowed) on I/O / subprocess failure.
    """
    try:
        lidar_port = _resolve_lidar_port(cfg)
    except webctl_toml_mod.WebctlTomlError as e:
        raise LidarPortNotResolvable(f"tracker_toml_parse_failed: {e}") from e
    usb_path = _resolve_usb_sysfs_path(lidar_port)
    # issue#16 HIL hot-fix v3 — positive log so the operator can see in
    # `journalctl -u godo-webctl` that the recovery actually fired and
    # for which USB port. Without this the auto-recovery is invisible
    # on the happy path (the only existing log was a WARNING on
    # failure), making it impossible to tell "ran and succeeded" from
    # "never ran" via the journal.
    logger.info(
        "mapping.recover_cp210x: firing for lidar_port=%s usb_path=%s",
        lidar_port,
        usb_path,
    )
    try:
        _write_cp210x_envfile(cfg, usb_path)
    except OSError as e:
        raise CP210xRecoveryFailed(f"envfile_write_failed: {e}") from e
    argv = ["systemctl", "start", "--no-pager", _CP210X_RECOVER_UNIT]
    try:
        proc = subprocess.run(  # noqa: S603 — argv is a list, no shell
            argv,
            capture_output=True,
            text=True,
            timeout=MAPPING_CP210X_RECOVER_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise CP210xRecoveryFailed(f"systemctl_timeout: {e}") from e
    if proc.returncode != 0:
        raise CP210xRecoveryFailed(
            f"systemctl_start_failed: rc={proc.returncode} stderr={proc.stderr.strip()}",
        )
    logger.info("mapping.recover_cp210x: completed for usb_path=%s", usb_path)
