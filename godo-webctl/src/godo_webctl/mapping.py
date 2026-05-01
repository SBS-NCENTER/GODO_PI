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
import secrets
import subprocess
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import services as services_mod
from . import webctl_toml as webctl_toml_mod
from .config import Settings
from .constants import (
    MAPPING_CONTAINER_NAME,
    MAPPING_CONTAINER_START_TIMEOUT_S,
    MAPPING_CONTAINER_STOP_TIMEOUT_S,
    MAPPING_DOCKER_INSPECT_POLL_S,
    MAPPING_DOCKER_INSPECT_TIMEOUT_S,
    MAPPING_DOCKER_STATS_TIMEOUT_S,
    MAPPING_JOURNAL_TAIL_DEFAULT_N,
    MAPPING_JOURNAL_TAIL_MAX_N,
    MAPPING_NAME_MAX_LEN,
    MAPPING_NAME_REGEX,
    MAPPING_PREVIEW_SUBDIR,
    MAPPING_RESERVED_NAMES,
    MAPPING_UNIT_NAME,
)

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
        # Container gone — was Running/Starting/Stopping but inspect
        # returns None or "exited". Transition to Failed for Running
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

    Side-effects:
      1. Validate name (regex + reserved + containment).
      2. Refuse if state ∈ {Starting, Running, Stopping, Failed}.
      3. Refuse if `<name>.pgm` already exists (canonical maps dir).
      4. Pre-flight `docker image inspect <tag>`.
      5. systemctl stop godo-tracker.
      6. Resolve LiDAR port from tracker.toml [serial] lidar_port.
      7. Atomic-write `active.env`.
      8. systemctl start godo-mapping@active.service.
      9. Poll `docker inspect` until `running` or timeout.

    On any failure between steps 5 and 9, transition to Failed with
    error_detail. The tracker stays stopped (operator restarts via
    System tab per L2).
    """
    validate_name(name)
    canonical_pgm = cfg.maps_dir / f"{name}.pgm"
    if canonical_pgm.exists():
        raise NameAlreadyExists(name)

    with _coordinator_flock(cfg):
        current = _load_state(cfg)
        if current.state != MappingState.IDLE:
            raise MappingAlreadyActive(current.state.value)

        # Pre-flight: image present?
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
            _save_state(cfg, failed_status)
            raise

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
            _save_state(cfg, failed_status)
            raise

        # Step 4: poll `docker inspect` until State.Status == "running".
        elapsed = 0.0
        import time

        while elapsed < MAPPING_CONTAINER_START_TIMEOUT_S:
            inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
            if inspect == "running":
                short_id = _docker_inspect_container_id_short(
                    cfg,
                    MAPPING_CONTAINER_NAME,
                )
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
            time.sleep(MAPPING_DOCKER_INSPECT_POLL_S)
            elapsed += MAPPING_DOCKER_INSPECT_POLL_S

        # Timeout — defensive cleanup + Failed.
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
        _save_state(cfg, failed_status)
        raise ContainerStartTimeout(
            f"timeout after {MAPPING_CONTAINER_START_TIMEOUT_S}s",
        )


def stop(cfg: Settings) -> MappingStatus:
    """Running → Stopping → Idle. Failed → Idle (acknowledge).
    Starting → Stopping → Idle (operator abort, m10).

    Idle → 404 NoActiveMapping.
    Stopping → idempotent return of current state (200).
    """
    with _coordinator_flock(cfg):
        current = _load_state(cfg)
        if current.state == MappingState.IDLE:
            raise NoActiveMapping()
        if current.state == MappingState.STOPPING:
            return current
        if current.state == MappingState.FAILED:
            # Acknowledge: defensive `docker rm -f`; remove preview;
            # transition to Idle.
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

        # Starting or Running: transition to Stopping, then call
        # systemctl stop and poll for container exit.
        stopping_status = MappingStatus(
            state=MappingState.STOPPING,
            map_name=current.map_name,
            container_id_short=current.container_id_short,
            started_at=current.started_at,  # M3: preserved
            error_detail=None,
            journal_tail_available=False,
        )
        _save_state(cfg, stopping_status)

        try:
            _run_systemctl_stop_mapping(cfg)
        except Exception as e:  # noqa: BLE001 — we log + continue to poll
            logger.warning("systemctl stop godo-mapping returned: %s", e)

        # Poll for container exit (gone / exited).
        import time

        elapsed = 0.0
        while elapsed < MAPPING_CONTAINER_STOP_TIMEOUT_S:
            inspect = _docker_inspect_state(cfg, MAPPING_CONTAINER_NAME)
            if inspect is None or inspect == "exited":
                # Clean stop. If we were Starting (no save yet), no
                # canonical PGM is expected on disk. Either way, Idle.
                new_status = _idle_status()
                _save_state(cfg, new_status)
                return new_status
            time.sleep(MAPPING_DOCKER_INSPECT_POLL_S)
            elapsed += MAPPING_DOCKER_INSPECT_POLL_S

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
        _save_state(cfg, failed_status)
        raise ContainerStopTimeout(
            f"timeout after {MAPPING_CONTAINER_STOP_TIMEOUT_S}s",
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
