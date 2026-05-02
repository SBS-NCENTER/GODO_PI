# godo-webctl — codebase map

## Scope

Phase 4-3 operator HTTP for `godo_tracker_rt`. Single FastAPI process
(uvicorn, single worker), three endpoints + one static page, talks to the
tracker exclusively over the Phase 4-2 D Unix-domain JSON-lines socket.

Greenfield: no edits to `production/RPi5/`, `XR_FreeD_to_UDP/`, or any
SSOT doc.

## Directory layout

```text
godo-webctl/
├─ pyproject.toml
├─ uv.lock                            # committed (D9)
├─ .python-version                    # 3.13
├─ .gitignore
├─ README.md
├─ CODEBASE.md                        # ← this file
├─ /src/godo_webctl/
│   ├─ __init__.py                    # __version__
│   ├─ __main__.py                    # uvicorn entrypoint (workers=1)
│   ├─ protocol.py                    # UDS wire constants + canonical encoders
│   ├─ config.py                      # _DEFAULTS / _PARSERS / _ENV_TO_FIELD
│   ├─ uds_client.py                  # AF_UNIX SOCK_STREAM, sync API
│   ├─ backup.py                      # atomic .pgm + .yaml snapshot
│   ├─ app.py                         # FastAPI factory + 3 thin handlers
│   └─ /static/index.html             # vanilla-JS status page
├─ /tests/
│   ├─ conftest.py                    # fake_uds_server, tmp_socket_path, tmp_map_pair
│   ├─ test_protocol.py               # SSOT pinning
│   ├─ test_config.py                 # defaults + overrides + drift catch
│   ├─ test_uds_client.py             # 10 cases incl. M3 buffer-full
│   ├─ test_backup.py                 # atomicity + collision retry
│   ├─ test_app_integration.py        # FastAPI in-process, 9 cases
│   └─ test_app_hardware_tracker.py   # @pytest.mark.hardware_tracker (S9)
└─ /systemd/
    ├─ godo-webctl.service            # User=ncenter, StateDirectory=godo
    └─ godo-webctl.env.example
```

## Module map and responsibilities

| Module | Depends on | Responsibility |
| --- | --- | --- |
| `protocol.py` | stdlib | Pinned wire constants + canonical request encoders. Mirrors a subset of C++ Tier-1. |
| `config.py` | stdlib | `Settings` dataclass + `load_settings(env)`. Pure function. |
| `uds_client.py` | `protocol`, stdlib | Sync AF_UNIX client; typed exceptions; per-syscall timeout. |
| `backup.py` | `protocol`, stdlib | Two-phase atomic copy + bounded retry-on-rename. |
| `maps.py` | `constants`, stdlib | Pure-function multi-map primitives. SOLE owner of every FS touch in `cfg.maps_dir`. No FastAPI / Pillow / subprocess imports. |
| `map_backup.py` | stdlib | Pure-function map-backup history primitives. SOLE owner of FS touches in `cfg.backup_dir`; restore writer ALSO writes into `cfg.maps_dir` but does NOT import `maps.py` (Track E uncoupled-leaves discipline). |
| `app.py` | `config`, `uds_client`, `backup`, `protocol`, FastAPI | App factory, 3 thin route handlers, static mount. |
| `__main__.py` | `config`, `app`, uvicorn | Process entrypoint; `workers=1` hardcoded. |

Dependency graph (no back-edges):

```text
protocol.py ◄── uds_client.py ◄──┐
                                  ├── map_backup.py ◄── app.py ◄── __main__.py
backup.py    ◄───────────────────┤   (sole owner of cfg.backup_dir
config.py    ◄───────────────────┘    + restore writes to cfg.maps_dir)
```

## Invariants

### (a) UDS is the only tracker IPC

`uds_client.py` is the only module that talks to `godo_tracker_rt`. No
other module imports `socket`, opens files under `/run/godo/`, or
otherwise side-channels into the tracker process. Adding a second IPC
mechanism requires a planner-led design change.

### (b) Cross-language SSOT (no auto-sync)

`protocol.py` mirrors a subset of C++ Tier-1 from
`production/RPi5/src/core/{constants.hpp, rt_flags.hpp}` and
`production/RPi5/src/uds/{json_mini.cpp, uds_server.cpp}`. The pinned
constants and their C++ origins:

```text
Python (protocol.py)              C++ origin (wire-string site)
──────────────────────────        ─────────────────────────────────────
UDS_REQUEST_MAX_BYTES = 4096      constants.hpp:54
MODE_IDLE     = "Idle"            json_mini.cpp:119 (mode_to_string),
                                  json_mini.cpp:127 (parse_mode_arg)
MODE_ONESHOT  = "OneShot"         json_mini.cpp:120 + :128
MODE_LIVE     = "Live"            json_mini.cpp:121 + :129
CMD_PING      = "ping"            uds_server.cpp:201 (req.cmd compare)
CMD_GET_MODE  = "get_mode"        uds_server.cpp:206
CMD_SET_MODE  = "set_mode"        uds_server.cpp:212
CMD_GET_LAST_POSE = "get_last_pose"
                                  uds_server.cpp `get_last_pose` branch
                                  (Track B; uds_protocol.md §C.4)
LAST_POSE_FIELDS                  json_mini.cpp::format_ok_pose
  = ("valid","x_m","y_m",         (Track B; field-name SSOT is the
     "yaw_deg","xy_std_m",        printf format string itself; pinned
     "yaw_std_deg","iterations",  by tests/test_protocol.py
     "converged","forced",        ::test_last_pose_fields_match_cpp_source
     "published_mono_ns")         which regex-extracts from C++ source)
CMD_GET_LAST_SCAN = "get_last_scan"
                                  uds_server.cpp `get_last_scan` branch
                                  (Track D; uds_protocol.md §C.5)
LAST_SCAN_HEADER_FIELDS           rt_types.hpp::struct LastScan
  = ("valid","forced",            (Track D; field-NAME SSOT is the
     "pose_valid","iterations",   struct declaration in rt_types.hpp,
     "published_mono_ns",         NOT format_ok_scan — pinned by
     "pose_x_m","pose_y_m",       test_protocol.py::
     "pose_yaw_deg","n",          test_last_scan_header_fields_match_cpp_source
     "angles_deg","ranges_m")     which regex-extracts from rt_types.hpp)
LAST_SCAN_RANGES_MAX_PYTHON_MIRROR = 720
                                  core/constants.hpp::LAST_SCAN_RANGES_MAX
                                  (Track D; pinned by
                                  test_last_scan_ranges_max_python_mirror_matches_cpp)
LAST_SCAN_RESPONSE_CAP = 32768    uds_client._roundtrip pass-through;
                                  Track D wider read cap for
                                  get_last_scan (~14 KiB worst case)
CMD_GET_JITTER = "get_jitter"     uds_server.cpp `get_jitter` branch
                                  (PR-DIAG; uds_protocol.md §C.6)
CMD_GET_AMCL_RATE = "get_amcl_rate"
                                  uds_server.cpp `get_amcl_rate` branch
                                  (PR-DIAG, Mode-A M2 fold;
                                  uds_protocol.md §C.7)
JITTER_FIELDS                     rt_types.hpp::struct JitterSnapshot +
  = ("valid","p50_ns","p95_ns",   json_mini.cpp::format_ok_jitter
     "p99_ns","max_ns","mean_ns", (PR-DIAG; field-NAME SSOT is the
     "sample_count",              struct, field-ORDER SSOT is the
     "published_mono_ns")         format string. Pinned by
                                  test_jitter_struct_fields_match_cpp_source
                                  + test_jitter_fields_match_cpp_source.)
AMCL_RATE_FIELDS                  rt_types.hpp::struct AmclIterationRate
  = ("valid","hz",                + json_mini.cpp::format_ok_amcl_rate
     "last_iteration_mono_ns",    (PR-DIAG, Mode-A M2 fold; same dual-pin
     "total_iteration_count",     pattern as JITTER_FIELDS — pinned by
     "published_mono_ns")         test_amcl_rate_struct_fields_match_cpp_source
                                  + test_amcl_rate_fields_match_cpp_source.)
RESOURCES_FIELDS                  webctl-only (no C++ counterpart);
  = ("cpu_temp_c","mem_used_pct", pinned by test_resources_fields_pinned.
     "mem_total_bytes",
     "mem_avail_bytes",
     "disk_used_pct",
     "disk_total_bytes",
     "disk_avail_bytes",
     "published_mono_ns")
DIAG_FRAME_FIELDS                 SSE multiplexed payload top-level keys;
  = ("pose","jitter",             pinned by test_diag_frame_fields_pinned.
     "amcl_rate","resources")     Mode-A M2 fold renamed scan_rate →
                                  amcl_rate.
ERR_PARSE_ERROR = "parse_error"   uds_server.cpp:189,196
ERR_UNKNOWN_CMD = "unknown_cmd"   uds_server.cpp:225
ERR_BAD_MODE    = "bad_mode"      uds_server.cpp:215
```

Additional cross-language mirror: `backup._yaml_path_for` mirrors
`production/RPi5/src/localization/occupancy_grid.cpp::yaml_path_for`
(L253-258) — strip a trailing lowercase `.pgm`, append `.yaml`.

No auto-sync. `tests/test_protocol.py` pins literal Python values; any
Phase 4-2 follow-up that touches the UDS schema MUST update the C++ side
AND `protocol.py` AND `test_protocol.py` in the same commit.
Auto-sync alternatives (codegen, shared header) explicitly considered
and rejected for this surface size; revisit if Phase 4.5 grows the
schema substantially.

### (c) Thin route handlers

FastAPI route handlers in `app.py` are thin: each accepts the request,
calls EXACTLY ONE of (`uds_client.{set_mode|get_mode|ping}` via
`call_uds`, `backup.backup_map`), maps the result to the documented
response shape + `HTTPStatus`. No business logic, no nested control flow
beyond the documented error-mapping table.

### (d) HTTPStatus enums, never integer literals

`app.py` expresses HTTP status codes via `from http import HTTPStatus`
(`HTTPStatus.SERVICE_UNAVAILABLE`, `.GATEWAY_TIMEOUT`, `.BAD_GATEWAY`,
`.BAD_REQUEST`, `.NOT_FOUND`, `.INTERNAL_SERVER_ERROR`). Integer literals
are a code-review block.

### (e) `workers=1` and pidfile-enforced single-instance

`__main__.py` hardcodes `workers=1` in `uvicorn.run(...)` (single-client
tracker UDS — see `__main__.py` D11 comment) AND acquires
`fcntl.flock(LOCK_EX | LOCK_NB)` on `Settings.pidfile_path`
(default `/run/godo/godo-webctl.pid`) BEFORE `uvicorn.run`. A second
webctl invocation — same port or different — exits 1 with stderr
`godo-webctl already running with PID <pid>`. The lock path is
overridable via `GODO_WEBCTL_PIDFILE` for tests. Pinned by
`tests/test_main_lock.py`. See CLAUDE.md §6 "Single-instance
discipline".

### (f) `backup_map` single-writer + flock defense-in-depth

`backup_map` is single-writer at runtime via invariant (e); a second
concurrent invocation is now ALSO blocked at the FS layer by
`fcntl.flock(LOCK_EX | LOCK_NB)` on `<backup_dir>/.lock`. On contention
(only reachable if invariant (e) is broken) →
`BackupError("concurrent_backup_in_progress")`, mapped to HTTP 409.
The bounded `MAX_RENAME_ATTEMPTS=9` retry remains for back-to-back
calls in the same UTC second by a single writer. Pinned by
`test_backup_lock_acquired_and_released` +
`test_concurrent_backup_raises_concurrent_in_progress`.

### (g) `/run/godo/` is owned by `godo-tracker.service`

The webctl systemd unit assumes `/run/godo/` is created by
`godo-tracker.service` (`RuntimeDirectory=godo`). webctl's unit drops
its own `RuntimeDirectory=godo` to avoid co-ownership ambiguity. If the
tracker unit ever lands without that directive, webctl bring-up fails
until the dir exists.

### (h) Environment SSOT

`config._DEFAULTS` is the single source for both runtime defaults and
the README env-var table. `_PARSERS` and `_ENV_TO_FIELD` keep
`Settings` field names and per-field casts in lockstep; drift is caught
by `tests/test_config.py::test_defaults_match_settings` and
`::test_env_to_field_keys_match_defaults`.

### (i) JWT secret persistence

`cfg.jwt_secret_path` (default `/var/lib/godo/auth/jwt_secret`) holds
the HS256 signing secret. 32 random bytes auto-generated with mode
0600 on first webctl boot. The secret is read **once at startup** into
`app.state.jwt_secret`; `systemctl restart godo-webctl` re-reads from
disk and **rotates the secret, invalidating all extant operator
sessions**. There is no in-app rotation knob — the trade is intentional:
a stolen token cannot survive an operator-triggered service restart.

### (j) `users.json` is the credential SSOT (atomic writes only)

`cfg.users_file` (default `/var/lib/godo/auth/users.json`) is a small
JSON object `{username: {password_hash, role}}`. Writers acquire
`flock(LOCK_EX)` on the file FD and replace via tmp-file +
`os.replace` so a crash mid-write cannot corrupt the file. The CLI
helper `scripts/godo-webctl-passwd` uses the same `UserStore` writer
path, so the lock serialises the FastAPI app and the CLI together.

**Corruption recovery (per N2)**: on startup, if the file exists but
fails to parse OR fails schema validation, `godo_webctl.auth` logs at
ERROR (`auth.users_file_invalid`) and enters an **`auth-disabled`**
state — every login returns HTTP 503 with body
`{"err":"auth_unavailable", "detail":...}`, while `/api/health` and
unauthenticated routes continue to serve. This keeps B-LOCAL reachable
on the kiosk so the operator sees the failure. Recovery: edit the file
(or restore from backup) + `systemctl restart godo-webctl`.

### (k) `/api/local/*` is loopback-only

All `/api/local/*` routes attach `Depends(loopback_only)`. The gate
checks the actual TCP peer IP (`request.client.host`) against IPv4
`127.0.0.0/8` and IPv6 `::1`. **`X-Forwarded-For` is never honoured**
(no proxy in our deployment); flipping `cfg.chromium_loopback_only` to
False does not enable XFF trust either — the field exists only as a
future-proofing hook for a hypothetical proxy-fronted topology where
the loopback gate moves upstream.

### (l) SSE generators are cancel-safe + sleep-injectable

`sse.last_pose_stream` and `sse.services_stream` both:

- Accept a `sleep` callable (default `asyncio.sleep`) so unit tests
  inject a recorder/no-op generator and assert cadence by **the
  sequence of sleep durations**, not wall-clock elapsed time
  (per reviewer T3).
- Re-raise `asyncio.CancelledError` from inside the loop so the
  generator terminates cleanly within one virtual tick.
- Set `Cache-Control: no-cache` and `X-Accel-Buffering: no` on the
  `StreamingResponse` (per N5). A future maintainer adding nginx /
  Caddy in front of webctl will not have to re-discover the
  SSE-buffering footgun.

### (m) systemctl/journalctl argv lists are constants

`services.py` builds every subprocess argv as a Python LIST,
**never** an f-string interpolated shell string. `tests/test_services.py`
asserts the literal list (e.g. `mock.assert_called_once_with(["shutdown",
"-r", "+0"], ...)`); a writer who reverted to a shell-string call must
fail those tests. The whitelist of allowed service names lives in
`services.ALLOWED_SERVICES` (constant), so unknown svc strings are
rejected before reaching subprocess.

### (o) `maps.py` is the SOLE owner of `cfg.maps_dir` filesystem touches (Track E, PR-C)

Every path inside `cfg.maps_dir` (the multi-map directory) is read or
written through `maps.py`. `app.py` and tests use the `maps.*` public
API exclusively; `map_image.py` does NOT import `maps.py` (the cache
fix is internal to `map_image.py` via `os.path.realpath`). Keeping
these two leaves uncoupled means a future change to one cannot break
the other.

### (p) Active map is two relative symlinks under `flock` (Track E, PR-C)

`active.pgm` and `active.yaml` are **relative-target** symlinks living
inside `cfg.maps_dir`. Both swap together under one
`flock(LOCK_EX)` on `cfg.maps_dir/.activate.lock` per
`maps.set_active`. The atomic per-symlink swap is two syscalls:
`os.symlink(target, .active.<rand>.<ext>.tmp)` then
`os.replace(.active.<rand>.<ext>.tmp, active.<ext>)` — POSIX
`rename(2)` semantics, atomic on the same filesystem. `secrets.token_hex(8)`
gives a 64-bit collision space; no `mkstemp` dance. Stale `.active.*.tmp`
leftovers from a prior crashed swap are swept at the START of every
`set_active` (before creating the new tmp). Pinned by
`tests/test_maps.py::test_set_active_serializes_under_flock` and
`test_set_active_sweeps_stale_tmp_leftovers`.

### (q) Map-name regex is a Tier-1 constant; `realpath` containment runs everywhere (Track E, PR-C)

`MAPS_NAME_REGEX = ^[a-zA-Z0-9_()-][a-zA-Z0-9._()-]{0,63}$` lives in
`constants.py` (Tier-1). Allows letters, digits, `_`, `-`, `.`, `(`,
`)`; first char may NOT be `.` (rejects `..`, `.hidden`, and the
project's own `.activate.lock` reserved name). Max 64 chars. Every
public `maps.py` function that returns or operates on a path validates
the name AND runs `os.path.realpath(result).startswith(
os.path.realpath(maps_dir) + os.sep)` — explicit `if not …: raise
InvalidName("path_outside_maps_dir")`, NEVER `assert` (production may
run with `-O`). The reserved name `"active"` passes the regex but is
rejected at the public-function layer so an operator cannot upload a
regular `active.pgm` and confuse the resolver. Pinned by
`test_realpath_containment_rejects_symlink_targeting_outside_maps_dir`.

### (n) Read endpoints are anonymous; mutations require login (Track F)

The auth model splits cleanly along read-vs-write:

- **Anonymous-readable**: `/api/health`, `/api/last_pose`,
  `/api/last_pose/stream`, `/api/last_scan`, `/api/last_scan/stream`,
  `/api/map/image`, `/api/map/backup/list` (Track B-BACKUP), `/api/maps`,
  `/api/maps/<name>/image`, `/api/maps/<name>/yaml`, `/api/activity`,
  `/api/system/jitter` (PR-DIAG), `/api/system/amcl_rate` (PR-DIAG),
  `/api/system/resources` (PR-DIAG), `/api/diag/stream` (PR-DIAG,
  SSE @ 5 Hz), `/api/logs/tail` (PR-DIAG),
  `/api/system/services` (Track B-SYSTEM PR-2; 1 s TTL cache; env
  values redacted by substring allow-list), `/api/local/services`
  (loopback), `/api/local/services/stream` (loopback),
  `/api/local/journal/<name>` (loopback).
- **Login-gated mutations** (`Depends(require_admin)`): `/api/calibrate`,
  `/api/live`, `/api/map/backup`, `/api/map/backup/<ts>/restore`
  (Track B-BACKUP), `/api/map/edit` (Track B-MAPEDIT),
  `/api/map/origin` (Track B-MAPEDIT-2),
  `/api/maps/<name>/activate`, `DELETE /api/maps/<name>`,
  `/api/local/service/<name>/<action>` (loopback + admin),
  `/api/system/service/<name>/<action>` (admin-non-loopback;
  Track B-SYSTEM PR-2 §8 fold), `/api/system/reboot`, `/api/system/shutdown`.
- **Session-only routes** (`Depends(require_user)`): `/api/auth/me`,
  `/api/auth/refresh`, `/api/auth/logout`.

The split is enforced by ZERO `Depends(require_user)` on read-route
handlers — verified by `tests/test_app_integration.py::test_mutation_endpoints_unauth_return_401`
parametrized over every mutation path. Loopback gating runs strictly
before auth gating, so a non-loopback caller hitting `/api/local/*`
sees HTTP 403 `loopback_only` regardless of token validity. The SPA
mirrors this in `App.svelte` (no auth-redirect on the router) and
`api.ts` (a 401 only triggers a `/login` redirect when the caller had
a token — anon callers see the raw 401 instead of being bounced).

### (q) PR-DIAG — Resources cache is process-local + 1 s TTL

`resources.snapshot()` (`src/godo_webctl/resources.py`) maintains a
module-level `_cache: tuple[mono_ns, dict] | None`. Two calls within
the TTL window return the same dict object (cache hit); calls past TTL
return a fresh snapshot. Webctl runs single-uvicorn-worker per
invariant (e), so no inter-worker race. Pinned by
`test_resources.py::test_cache_hit_within_ttl` +
`test_cache_miss_after_ttl`.

### (r) PR-DIAG — Logs allow-list reuses `services.ALLOWED_SERVICES`

`logs.py` does NOT define a parallel allow-list — it imports
`services.ALLOWED_SERVICES` and re-exports the three exception types
(`UnknownService`, `CommandTimeout`, `CommandFailed`) so callers
catching `logs.UnknownService` AND `services.UnknownService` hit the
same handler. Drift is impossible by construction. Pinned by
`test_logs.py::test_logs_allow_list_is_services_allow_list` +
`test_exception_types_are_services_aliases`.

### (s) PR-DIAG — DiagFrame is multiplexed (nested), not flattened

`/api/diag/stream` emits a single SSE frame per tick whose payload is
a 4-key dict: `{pose, jitter, amcl_rate, resources}` (Mode-A M2 fold:
NOT `scan_rate`). Each sub-payload preserves its own
`published_mono_ns`; per-sub-panel freshness is gated SPA-side via
`_arrival_ms` (Track D Mode-A M2 + PR-DIAG N4 fold). Any single
sub-fetch failure becomes `{"valid": 0, "err": "..."}` for that key —
the OTHER three sub-payloads still emit. Pinned by
`tests/test_sse.py::test_diag_stream_*` (cadence + skip-pose-error +
skip-resources-error + all-four-fail-emits-all-sentinel).

### (t) Track B-BACKUP — `map_backup.py` is the SOLE owner of `cfg.backup_dir` filesystem touches

Every path inside `cfg.backup_dir` (the
`/var/lib/godo/map-backups/` directory) is read or operated on
through `map_backup.py`. `app.py` and tests use the `map_backup.*`
public API exclusively. The restore writer in `map_backup.py` ALSO
writes the restored pair into `cfg.maps_dir`, but does NOT import
`maps.py` — restore deliberately does not touch the `active.pgm` /
`active.yaml` symlinks (Option A semantics; operator activates
separately via `POST /api/maps/<name>/activate` + `godo-tracker`
restart). Concurrency-correctness inherits from invariant (e)
(single uvicorn worker = serial handler execution); no dedicated
concurrent test. Pinned by `tests/test_map_backup.py` and the
absence of any `from .maps import` line in `map_backup.py`.

### (u) Pidfile path is a Tier-2 config key

`Settings.pidfile_path` is the SOLE source of the lock path; no module
hardcodes a string. Default = `/run/godo/godo-webctl.pid`. Override via
`GODO_WEBCTL_PIDFILE`. Tests use `tmp_path / "godo-webctl.pid"` via
the autouse `_pidfile_path_autouse` fixture. Path MUST live on a local
FS — tmpfs `/run/godo` is the project default; NFS is unsupported
(flock semantics differ). Drift between `_DEFAULTS` / `_PARSERS` /
`_ENV_TO_FIELD` (per invariant (h)) is caught by
`tests/test_config.py::test_defaults_match_settings`.

### (v) Track B-SYSTEM PR-2 — `/api/system/services` is anon-readable + 1 s TTL + env redacted

`system_services.snapshot()` invokes `services.service_show()` over
`services.ALLOWED_SERVICES` (sorted for stable wire order) and caches
the projection for `SYSTEM_SERVICES_CACHE_TTL_S = 1.0 s`. Single
uvicorn worker (invariant (e)) ⇒ no inter-worker race. The wire payload
is `{services: SystemServiceEntry[]}` with `SYSTEM_SERVICES_FIELDS`
field order pinned in `protocol.py`. Each entry's `env_redacted`
substitutes `<redacted>` for any KEY whose name contains any of
`("SECRET","KEY","TOKEN","PASSWORD","PASSWD","CREDENTIAL")`
(case-insensitive substring). The redaction is defence-in-depth: the
SSOT is the systemd unit-file authoring discipline that keeps secrets
out of plain env vars. False-positives (`MOST_KEY_BUNDLES`) are
accepted — safe direction.

Per-service degradation (Mode-A M5 fold): when `services.service_show`
fails for one service (e.g. systemctl unavailable on a dev box), that
entry surfaces as `active_state="unknown"` with the rest of fields
nullable. The aggregate endpoint always returns 200; no 503 wire path.

Pinned by `tests/test_system_services.py` +
`tests/test_protocol.py::test_env_redaction_patterns_pinned` +
`tests/test_protocol.py::test_system_services_fields_pinned`.

### (w) Track B-SYSTEM PR-2 — `services.control()` refuses start/restart on `activating` and stop on `deactivating`

`services.control(svc, action)` performs an `is_active(svc)` pre-flight
read; if `action ∈ {start, restart}` and state == `activating`, or
`action == stop` and state == `deactivating`, raises
`ServiceTransitionInProgress`. Both `/api/local/service/<name>/<action>`
(loopback-admin) and `/api/system/service/<name>/<action>` (admin-non-
loopback per invariant (x)) share `services.control()` as the SOLE call
site, so the gate is inherited verbatim. The handler maps to HTTP 409 +
body `{ok: False, err: "service_starting"|"service_stopping",
detail: "<Korean string>"}` from `constants.SERVICE_TRANSITION_MESSAGES_KO`.

The Korean detail uses the **Korean reading convention** for romanized
service names — the syllable read aloud determines the 받침 / 조사 pair:
godo-tracker → 트래커 → 가; godo-webctl → 웹씨티엘 → 이;
godo-irq-pin → 아이알큐 핀 → 이.

The TOCTOU window between pre-flight and the would-be `systemctl
<action>` is acceptable because **systemd dedupes redundant
`restart`/`start` requests on a unit already in `activating` state**
— the second request is a no-op. The pre-flight gate exists to give the
operator a Korean-language warning, not as a hard atomic gate
(Mode-A M6 fold pin: this rationale cites systemd idempotency, NOT
invariant (e)). `BLOCKING_TRANSITION_STATES` is limited to
`{activating, deactivating}` deliberately — no service in
`ALLOWED_SERVICES` defines `ExecReload=`. A future writer who adds a
reloadable service must extend the set + integration test in the same
PR (Mode-A S7 fold).

Pinned by `tests/test_services.py::test_control_raises_*` +
`test_control_pre_flight_does_not_use_system_services_cache` (S2 fold:
`control()` calls `is_active()` directly, NEVER the cached snapshot)
and the integration tests asserting the exact Korean substring per
service in `tests/test_app_integration.py`.

### (y) Track D scale fix — `/api/maps/{name}/dimensions` reads PGM header without Pillow

`maps.read_pgm_dimensions(pgm_path)` parses the netpbm `P5` header
(magic + width/height tokens) reading at most `PGM_HEADER_MAX_BYTES = 64`
bytes from the file. The bound makes the function safe against a
pathologically large PGM (e.g., a 1 GB sparse file): we never stream
pixel data through Python.

`maps.py` raises `PgmHeaderInvalid` (a sibling of `InvalidName` /
`MapNotFound` / `MapIsActive` / `MapsDirMissing`) on malformed magic,
missing or non-numeric dimension tokens, or non-positive dimensions.
The class lives in `maps.py` rather than reverse-importing
`map_image.py::MapImageInvalid` — preserving `maps.py`'s Pillow-free
filesystem-primitives invariant per its module docstring (Mode-A T5
fold). `app.py::_map_maps_exc_to_response` maps `PgmHeaderInvalid` →
HTTP 500 with `{ok: False, err: "map_invalid"}` so the SPA's existing
`map_invalid` handler catches it.

The endpoint exists because PGM dimensions live in HEADER bytes, not
the YAML, so the SPA cannot extract them by parsing
`/api/maps/{name}/yaml`. The combined YAML (resolution + origin) +
dimensions (width + height) is what `mapMetadata` uses for
resolution-aware world↔canvas math (see godo-frontend/CODEBASE.md
invariant (x)).

Pinned by:

- `tests/test_maps.py::test_read_pgm_dimensions_*` (6 cases including
  the byte-bound spy per Mode-A T4 fold).
- `tests/test_app_integration.py::test_get_map_dimensions_*` (4 cases:
  happy + 404 + 400 + 500 malformed).

### (z) Track B-SYSTEM PR-B — process monitor + extended resources are stdlib-only `/proc` parsers

`processes.py` and `resources_extended.py` enumerate live PIDs and
read `/proc/stat` + `/proc/meminfo` + `os.statvfs` directly. **No
`subprocess` (no `ps -ef`, no `vcgencmd`). No `psutil`.** A future
writer reaching for either fails Mode-B.

Discipline rationale:

1. **Single-instance**: the new SSE generators run inside the existing
   webctl uvicorn worker (invariant (e)) — no new pidfile, no new
   daemon. Single-instance discipline is inherited.
2. **Anon-readable** (invariant (n)): both `/api/system/processes{,/stream}`
   and `/api/system/resources/extended{,/stream}` are read endpoints,
   no JWT required. `/proc/<pid>/cmdline` is already world-readable on
   Linux so this is not a new disclosure surface; operators should
   close the SPA Processes sub-tab on every client before running a
   transient command with secrets in argv (acknowledged limitation,
   deferred). See `processes.py` module docstring.
3. **All-PID classifier** (NOT whitelist filter): per operator decision
   2026-04-30 06:38 KST, every live PID surfaces with a wire-side
   `category ∈ {"general", "godo", "managed"}` field. Kernel threads
   (cmdline empty) are excluded from the row list — they would inflate
   the table to ~200 rows of `[ksoftirqd]`-style entries.
4. **Binary-vs-unit asymmetry pinned**:
   `protocol.MANAGED_PROCESS_NAMES` (process-name view) differs from
   `services.ALLOWED_SERVICES` (systemd-unit view) by exactly the
   substitution `godo-tracker → godo_tracker_rt`. The asymmetry is
   real (`godo-tracker.service` runs the `godo_tracker_rt` binary)
   and pinned by
   `tests/test_protocol.py::test_managed_process_names_cardinality`.
5. **`godo-webctl` argv exception**: matched via argv[1..] containing
   the `godo_webctl` token (because argv[0] is `python` / `uvicorn`).
   See `processes.parse_pid_cmdline` + tests
   `test_parse_pid_cmdline_godo_webctl_python_argv` /
   `test_parse_pid_cmdline_uvicorn_godo_webctl`.
6. **GPU intentionally out of scope** (operator decision): V3D
   `gpu_busy_percent` is unreliable on Trixie firmware (raspberrypi/linux
   #7230) and CPU temp is already surfaced by `RESOURCES_FIELDS.cpu_temp_c`.
   No `vcgencmd` / DRM sysfs reads in this PR. Re-evaluate when V3D
   busy% upstream lands.
7. **Cross-language SSOT** for the C++ subset of `GODO_PROCESS_NAMES`:
   regex-extracted `add_executable(<name>` lines from each
   `production/RPi5/src/*/CMakeLists.txt` must equal
   `{godo_tracker_rt, godo_freed_passthrough, godo_smoke, godo_jitter}`.
   A future writer adding a binary without updating the whitelist fails
   `tests/test_protocol.py::test_godo_process_names_match_cmake_executables`.
8. **`published_mono_ns` clock domain**: same as `RESOURCES_FIELDS` —
   webctl `time.monotonic_ns()` (Python clock domain), NOT C++
   tracker's CLOCK_MONOTONIC. SPA freshness uses arrival-wall-clock
   (`Date.now() - _arrival_ms` per frontend invariant (m)).

Pinned by:

- `tests/test_protocol.py::test_process_fields_pinned` (10 fields).
- `tests/test_protocol.py::test_processes_response_fields_pinned` (3 fields).
- `tests/test_protocol.py::test_extended_resources_fields_pinned` (6 fields).
- `tests/test_protocol.py::test_godo_process_names_match_cmake_executables`.
- `tests/test_protocol.py::test_managed_process_names_cardinality`.
- `tests/test_processes.py` (38 cases: parsers, paren-in-comm fixture,
  cpu_pct algebraic edges, classify, sampler first-tick / duplicate /
  user-resolve / kernel-thread).
- `tests/test_resources_extended.py` (20 cases: per-core delta, meminfo,
  disk pct, partial-failure resilience).
- `tests/test_sse.py::test_processes_stream_*` + `test_resources_extended_stream_*`.
- `tests/test_app_integration.py::test_get_system_processes_*` +
  `test_get_system_resources_extended_*`.

### (x) Track B-SYSTEM PR-2 — `POST /api/system/service/{name}/{action}` is admin-non-loopback

Mirrors the `/api/system/reboot` admin-non-loopback pattern:
`Depends(auth_mod.require_admin)`, NO `loopback_only`. JWT-authed admin
users from any origin (Tailscale, LAN, localhost) may invoke it. The
handler delegates to `services.control()`, so invariant (w)'s
pre-flight transition gate (HTTP 409 + Korean detail) is inherited
verbatim. The existing `/api/local/service/<name>/<action>`
(loopback-admin, kiosk path) stays unchanged — both endpoints share
`services.control()` underneath.

Full exception → status mapping (S2 fold, mirror of
`local_service_action`): `UnknownService` → 404,
`UnknownAction` → 400, `ServiceTransitionInProgress` → 409,
`CommandTimeout` → 504, `CommandFailed` → 500.

Successful invocations emit `activity_log.append("svc_<action>",
f"{name} by {claims.username}")` (S1 fold, mirror of
`local_service_action:932` / `system_reboot:995`).

Until Task #28 (polkit + systemctl unit-management) lands, the wrapped
`systemctl <action> <unit>` call returns `subprocess_failed` for
non-root invocations; the auth + transition layers nonetheless work,
and the integration suite uses a monkeypatched `services.control` to
assert the success path (TB1 fold pin: monkeypatch target is
`godo_webctl.services.control`, NOT `subprocess.run`). Pinned by
`tests/test_app_integration.py::test_post_system_service_*` (8 cases:
admin happy + anon 401 + user-role 403 + invalid action 400 + unknown
unit 404 + 409 transition + 504 timeout + 500 failed).

### (aa) `map_edit.py` is the SOLE owner of the mask→PGM transform (Track B-MAPEDIT, Phase 4.5 P2)

> Letter rationale: invariants (a)-(z) are all taken on main as of
> 2026-04-30 (Track D scale fix at (y), PR-B at (z)); the planner's
> `(y)` reservation in `plan_track_b_mapedit.md` §8 M1 was based on a
> pre-Track-D fold and the Track D close-out note already flagged the
> shift to (z) — which itself moved further to (aa) once PR-B landed.

Every byte written to a PGM file under `cfg.maps_dir` as a result of
`POST /api/map/edit` goes through `map_edit.apply_edit`. `app.py`
orchestrates the three-step sequence (backup-first, edit, restart-
pending-touch). `map_edit.py` does NOT import `maps.py` (Track E
uncoupled-leaves) — caller resolves the active realpath via
`maps.read_active_name` + `maps.pgm_for` and passes the `Path` in.
Concurrency-correctness inherits from invariant (e) (single uvicorn
worker = serial handler).

**Three-step sequence is contractual** (the writer must not reorder):

1. `backup.backup_map(active_pgm, cfg.backup_dir)` — backup-FIRST. A
   backup-failure aborts BEFORE the PGM is touched (R1 mitigation).
2. `map_edit.apply_edit(active_pgm, mask_bytes)` — atomic on-disk
   rewrite via tmp + `os.replace` (mode 0644). Mirrors
   `auth.py::_write_atomic` pattern. An edit-failure leaves the backup
   intact so the operator can manually restore.
3. `restart_pending.touch(cfg.restart_pending_path)` — LAST step. Never
   set on a failure path (anti-monotone partner). Tracker C++ has no
   awareness of edits; it reads PGM at boot only. Activation path is
   the operator-driven `systemctl restart godo-tracker` via either
   `/local` (loopback-admin kiosk path) or `/system` (admin-non-
   loopback, PR #27).

**Restart-pending sentinel ownership** is asymmetric: webctl OWNS the
write path via `restart_pending.touch()` (this PR adds the writer);
the tracker continues to OWN the clear path at boot via its existing
`clear_pending_flag()` (`production/RPi5/CODEBASE.md` invariant — set
during `Config::load()` boot sequence). Both processes run as user
`ncenter` (StateDirectory=godo), so the sentinel file's writers and
clearer share a uid — no cross-uid permission concern. The asymmetry
is contractual: webctl never clears, tracker never sets via this path
(the tracker's own `touch_pending_flag` writes the same file from a
different code path during `set_config`).

**Mask semantics** (R8 mitigation):

- Greyscale (mode "L"): pixel value `>= MAP_EDIT_PAINT_THRESHOLD` (128)
  means paint.
- RGBA / LA (with alpha channel): alpha `> 0` means paint.
- Anything else is converted to "L" first via `Image.convert("L")`.

**Body-size enforcement**: `app.py` checks `Content-Length`
header BEFORE reading the body (T2 fold pin — content-length check
runs BEFORE PNG decode, so an oversized garbage payload fails 413
distinctly from a shape-mismatch which fails 400 AFTER decode).
`map_edit.apply_edit` re-checks the byte length defence-in-depth.

**Activity log type literal**: `"map_edit"` (NOT `"map_edited"`) per
M2 fold — matches the imperative-style convention used by
`map_backup`, `map_activate`, `map_delete`, `svc_<action>`,
`calibrate`, `live_on/off`, `reboot`, `shutdown`, `login`.

Pinned by:

- `tests/test_map_edit.py::test_module_does_not_import_maps`,
- `tests/test_map_edit.py::test_apply_edit_atomic_write` (S3 fold —
  tmp cleanup on `os.replace` failure),
- `tests/test_map_edit.py::test_apply_edit_grey_threshold_boundary`
  (T1 fold — 127 NOT painted, 128 painted),
- `tests/test_app_integration.py::test_map_edit_backup_failure_aborts_pgm_untouched`,
- `tests/test_app_integration.py::test_map_edit_backup_ts_matches_disk_snapshot`
  (S1 fold — success-ordering pin),
- `tests/test_app_integration.py::test_map_edit_oversize_returns_413_without_decode`
  (T2 fold — content-length-before-decode pin),
- `tests/test_app_integration.py::test_map_edit_failure_leaves_no_restart_pending`
  (T3 fold — anti-monotone partner of `_touches_restart_pending`),
- `tests/test_app_integration.py::test_map_edit_appends_activity_log`
  (M2 fold — type literal `"map_edit"` pin).

### (ab) `map_origin.py` is the SOLE owner of the YAML origin metadata-rewrite (Track B-MAPEDIT-2, Phase 4.5 P2)

> Letter rationale: invariants (a)..(aa) are all taken on main as of
> 2026-04-30 (PR #39 closed at (aa) Track B-MAPEDIT); next free letter
> is (ab).

Every byte change to an active map's `origin:` line as a result of
`POST /api/map/origin` goes through `map_origin.apply_origin_edit`.
`app.py` orchestrates the three-step sequence (mirror of B-MAPEDIT
invariant `(aa)`):

1. `backup.backup_map(active_pgm, cfg.backup_dir)` — backup-FIRST.
   The PGM is unchanged but is included in the snapshot per
   `backup_map`'s pair contract (single backup helper covers both
   B-MAPEDIT and B-MAPEDIT-2 — uniform on-disk shape; switching to a
   YAML-only backup helper would break that invariant). Backup-failure
   aborts BEFORE the YAML rewrite (R1 mitigation).
2. `map_origin.apply_origin_edit(active_yaml, x_m, y_m, mode)` —
   line-level YAML rewrite via tmp + `os.replace` (mode 0644, mirror of
   `auth.py::_write_atomic` / `map_edit.py::_atomic_write`). On
   edit-failure the backup snapshot stays intact for manual recovery.
3. `restart_pending.touch(cfg.restart_pending_path)` — LAST step.
   Anti-monotone (never set on a failure path). Tracker C++ has no
   awareness of edits — it reads YAML at boot only via its existing
   `Config::load` path. Operator restarts via `/local` (loopback) or
   `/system` (admin-non-loopback, PR #27) to apply.

`map_origin.py` does NOT import `maps.py` (Track E uncoupled-leaves) —
caller resolves the active YAML realpath via `maps.read_active_name`
+ `maps.yaml_for` and passes the `Path` in. Concurrency-correctness
inherits from invariant (e) (single uvicorn worker = serial handler).

**Theta passthrough**: `origin[2]` (theta) is NEVER parsed-and-reformatted.
The token bytes between the second and third comma in the
`origin: [..]` list are preserved VERBATIM. This protects against
accidental drift when `repr(float)` reformats edge cases (e.g.
`1.5707963267948966 → 1.5707963267948965` round-trip). The wire
response `prev_origin[2]` / `new_origin[2]` carries a Python-float
parse PURELY for SPA display convenience; the on-disk theta token
stays byte-identical pre/post.

**PGM untouched**: only the YAML changes. The active PGM realpath's
bytes are byte-for-byte unchanged (pinned by the integration suite).

**Sign convention for `mode == "delta"` is ADD** (operator-locked
2026-04-30 KST, see `.claude/memory/project_map_edit_origin_rotation.md`):

  `new_origin = current_origin + (x_m, y_m)`

i.e. the typed `(x_m, y_m)` is the offset of the **new origin from
the current origin**. Operator phrasing: "실제 원점 위치는 여기서
(x, y)만큼 더 간 곳". A Mode-A reviewer caught the spec memory's
ambiguity (literal "subtract" wording vs. example "ADD" semantics);
operator confirmed ADD. SUBTRACT is wrong (would shift the origin by
2× the typed offset). Pinned by
`tests/test_map_origin.py::test_apply_origin_edit_delta_happy_path`,
`tests/test_app_integration.py::test_post_map_origin_admin_delta_happy_path`,
`tests/unit/originMath.test.ts::resolveDelta adds`.

**Block-scalar YAML form is rejected**: ROS map_server emits flow-style
`origin: [x, y, theta]`; if an operator hand-edits the file to use
the block-scalar form (`origin:\n  - x\n  - y\n  - theta`), the
rewriter raises `OriginYamlParseFailed("flow_style_required")` rather
than risking a partial-file edit. Operator must reformat or re-export
(README troubleshooting entry).

**`map_image.invalidate_cache()` is intentionally NOT called** (S4
fold dropped per Parent decision). The `/api/map/image` PNG cache key
is `PGM realpath + mtime`, both unchanged by an origin edit (origin
lives in YAML; the PNG is rendered from PGM bytes). Brush-edit's
`invalidate_cache()` call exists because brush-edit *does* rewrite
PGM bytes — there is no symmetric coupling here.

**Backup scope**: same `backup.backup_map(active_pgm, ...)` as
B-MAPEDIT. Because `backup_map` archives both `<stem>.pgm` and
`<stem>.yaml`, the on-disk snapshot includes a redundant PGM copy
(unchanged by this feature). Acceptable cost; uniform with brush-edit;
refactoring to a YAML-only backup helper is a future optimization,
not a blocker.

**Activity log type literal**: `"map_origin"` (NOT `"map_origin_edit"`,
NOT `"origin_set"`) — imperative-style convention shared with
`map_edit`, `map_backup`, `map_activate`, `map_delete`. Pinned by
`tests/test_app_integration.py::test_post_map_origin_appends_activity_log`
via literal-string equality (NOT `startswith` / `in`).

**Magnitude bound**: `ORIGIN_X_Y_ABS_MAX_M = 1_000.0` covers the
studio (~10 m) plus 100× headroom for shared-frame debug scenarios.
Values >1 km are flagged as operator typos (constants.py docstring
locks the rationale).

**Body-size envelope**: `bad_payload + detail=body_too_large` at 413
(M3 Option A — mirror of `PATCH /api/config` precedent at
`app.py:888-892`). No new top-level constant; the `body_too_large`
token sits in `detail` rather than `err`.

**`math.isfinite` is the load-bearing NaN/Inf check** (S5 fold).
Pydantic's `allow_inf_nan` is best-effort defence-in-depth — the
explicit `isfinite` check inside `apply_origin_edit` (and the
pre-handler check in `app.py`) is the contract.

Pinned by:

- `tests/test_map_origin.py::test_module_does_not_import_maps`,
- `tests/test_map_origin.py::test_apply_origin_edit_atomic_write`
  (S2 fold — `*.tmp` cleanup-on-failure),
- `tests/test_map_origin.py::test_apply_origin_edit_preserves_theta_byte_for_byte`
  (T2 fold — parametrized over `1.5e-3`, `-0.0`, high-precision token),
- `tests/test_map_origin.py::test_apply_origin_edit_preserves_other_yaml_keys_byte_for_byte`,
- `tests/test_map_origin.py::test_apply_origin_edit_origin_line_whitespace_variants`
  (T3 fold),
- `tests/test_map_origin.py::test_apply_origin_edit_preserves_crlf_line_endings`,
- `tests/test_app_integration.py::test_post_map_origin_backup_failure_aborts_yaml_untouched`,
- `tests/test_app_integration.py::test_post_map_origin_yaml_rewrite_failure_leaves_no_restart_pending`
  (S3 fold — anti-monotone partner of `_touches_restart_pending`),
- `tests/test_app_integration.py::test_post_map_origin_backup_ts_matches_disk_snapshot`
  (S1 fold — snapshot YAML reflects pre-edit origin bytes),
- `tests/test_app_integration.py::test_post_map_origin_appends_activity_log`
  (M5 fold — type literal `"map_origin"` pin),
- `tests/test_app_integration.py::test_post_map_origin_oversize_returns_413`
  (M3 fold — Option A envelope),
- `tests/test_app_integration.py::test_post_map_origin_locale_comma_string_returns_400`
  (T4 fold),
- `tests/test_protocol.py::test_origin_edit_response_fields_pinned`,
- `tests/test_protocol.py::test_origin_modes_pinned`.

### (ac) issue#12 — webctl-owned schema rows + tracker.toml SSOT

> Letter rationale: (a)..(ab) all in use as of 2026-04-30; next free
> letter is (ac).

issue#12 introduces a new ownership pattern at the tracker schema
boundary: rows whose **runtime consumer is godo-webctl rather than the
tracker itself**. Two current entries: `webctl.pose_stream_hz` /
`webctl.scan_stream_hz` (Int [1, 60], default 30 Hz, ReloadClass
Restart). Tracker stores them as first-class `Config` fields, the SPA
edits them via the same schema-driven Config tab as every other Tier-2
key, but no tracker logic path reads the value. webctl is the sole
consumer.

Cross-link: tracker side covers the Config-storage half via
`production/RPi5/CODEBASE.md` invariant `(r)`.

**Storage path (webctl-side)**:

1. webctl's settings dataclass gains `tracker_toml_path: Path`
   (default `/var/lib/godo/tracker.toml`, override via
   `GODO_WEBCTL_TRACKER_TOML_PATH` for tests).
2. `godo_webctl/webctl_toml.py` — leaf module (stdlib only) exporting
   one public function: `read_webctl_section(toml_path, env=None) ->
   WebctlSection`. Returns a typed NamedTuple of `(pose_stream_hz,
   scan_stream_hz)` after applying the precedence ladder env > TOML >
   default. Raises `WebctlTomlError` on malformed TOML / non-int /
   out-of-range; missing TOML file is NOT an error (returns defaults).
3. `godo_webctl/sse.py` — `last_pose_stream` and `last_scan_stream`
   resolve their per-tick sleep duration at stream open via
   `_resolve_pose_tick_s` / `_resolve_scan_tick_s` helpers that wrap
   `webctl_toml.read_webctl_section` in a try/except (falls back to
   schema defaults on `WebctlTomlError`). All other SSE producers
   (`services_stream`, `processes_stream`, `resources_extended_stream`,
   `diag_stream`) are UNCHANGED — operator-locked "지도 부분에만 적용".
4. `godo_webctl/__main__.py::main` — eager startup read (wrapped in
   try/except per Mode-A M6 / Parent A6) logs the resolved rates at
   INFO; on failure, logs WARNING and falls back to defaults so the
   service boots regardless.

**Constants live in `webctl_toml.py`, not `constants.py`** (Mode-A N5 /
Parent A8): the leaf-module dependency edge stays
`sse.py → webctl_toml.py → stdlib` with no back-edges.
`WEBCTL_POSE_STREAM_HZ_DEFAULT = 30`, `WEBCTL_SCAN_STREAM_HZ_DEFAULT =
30`, `WEBCTL_STREAM_HZ_MIN = 1`, `WEBCTL_STREAM_HZ_MAX = 60` are pinned
there and in `tests/test_webctl_toml.py::test_public_constants_pinned`.

**Atomic-rename safety**: the tracker writes `tracker.toml` via
`atomic_toml_writer.cpp` (`mkstemp + fsync + rename`). webctl's
`read_webctl_section` either sees the OLD or the NEW content — never a
partial file. R1 race window framing in the issue#12 plan is therefore
moot.

**Reload-class semantics**: `webctl.*` rows are Restart class. After
the operator edits via SPA Config tab, `restart_pending` fires (the
generic banner), and `systemctl restart godo-webctl` is the propagation
path (NOT godo-tracker — the tracker does not consume the value).
Per-key restart-target hints in the SPA banner are an out-of-scope
enhancement.

**Forward-compat**: `read_webctl_section` tolerates unknown keys inside
`[webctl]`. The tracker still rejects unknown keys at parse time via
`allowed_keys()`, so a typo never reaches webctl — but a future webctl
running against a NEW tracker.toml that adds `webctl.future_key` boots
without crash (only the keys this version knows are validated).

**Range validation responsibility**: the tracker validates `[1, 60]`
inside `apply_set` (Tier-2 schema row); webctl re-validates at the
reader to defence-in-depth a manually-edited tracker.toml that bypassed
the SPA. Defaults match byte-exactly between the two layers.

Pinned by:
- `tests/test_webctl_toml.py` — 28 cases covering precedence, range,
  type, missing-file, malformed-TOML, and forward-compat.
- `tests/test_sse.py::test_last_pose_stream_honours_toml_pose_stream_hz`
  + `test_last_scan_stream_honours_toml_scan_stream_hz` — TOML
  fixture-driven cadence injection (10 Hz → sleep ≈ 0.1 s; 20 Hz →
  sleep ≈ 0.05 s).
- `tests/test_sse.py::test_last_pose_stream_env_var_overrides_toml`
  — env > TOML precedence pin.
- `tests/test_sse.py::test_last_pose_stream_falls_back_on_toml_error`
  — Mode-A M6 / Parent A6 pin (out-of-range value does NOT crash the
  stream; default 30 Hz applies).
- `tests/test_sse.py::test_diag_stream_emits_one_frame_per_tick` —
  regression pin that `diag_stream` continues to use `SSE_TICK_S`,
  NOT the new webctl.* config-driven cadence.
- `tests/test_config.py::test_empty_env_uses_defaults` +
  `test_each_env_var_overrides_default` — `tracker_toml_path` parity
  in the `_DEFAULTS` / `_PARSERS` / `_ENV_TO_FIELD` triple-table.
- `tests/test_config_schema.py::test_load_schema_real_source_returns_48_rows`
  — webctl Python mirror reflects the new row count.
- `tests/test_config_schema_parity.py::test_webctl_rows_present` —
  C++ schema rows present, type Int, range [1, 60], default 30,
  Restart class.
- `tests/test_config_view.py::test_project_schema_view_real_source` —
  config view projection includes webctl.* rows.
- `tests/test_app_integration.py::test_get_config_schema_returns_48_rows`
  — `/api/config/schema` round-trip serves 48 rows including the two
  webctl.* entries.

### (ad) issue#14 — Mapping coordinator location + state.json SSOT

> Letter rationale: (a)..(ac) all in use as of 2026-05-01; next free
> letter is (ad).

`mapping.py` is the SOLE webctl-side writer of
`<cfg.mapping_runtime_dir>/state.json` and the SOLE caller of
`systemctl start|stop godo-mapping@active.service` from webctl. The
C++ tracker is NEVER notified of mapping mode through UDS — coordinator
state derives purely from `(state.json, docker inspect output)`. The
tracker is stopped during mapping; `/run/godo/ctl.sock` is therefore
unavailable, which is the existing tracker-down behaviour (webctl
returns 503 on UDS unreachable per invariant `(n)`).

**State machine** (5 states): Idle → Starting → Running → Stopping →
Idle (success), or Failed from any of {Starting, Running, Stopping}
(crash / timeout / image_missing / tracker_stop_failed). `mapping.stop`
on Failed is the operator's "acknowledge" verb that returns to Idle
+ defensive `docker rm -f` + preview-file cleanup.

**Boot-reconcile (M3)**: `_save_state` only writes a fresh `now()` as
`started_at` on the Idle→Starting transition. All other transitions
preserve the existing timestamp so a webctl restart mid-mapping
followed by `journalctl -u godo-mapping@active.service
--since=<started_at>` still surfaces the original launch window's logs.

**Concurrency**: webctl is single-uvicorn-worker (invariant `(e)`).
Every `start`/`stop` call acquires
`fcntl.flock(<runtime_dir>/.lock, LOCK_EX | LOCK_NB)` as a defence-in-
depth so a future writer adding workers cannot interleave transitions.
Concurrent `start` raises `MappingAlreadyActive` → 409.

**Tracker [serial] section reader**: `webctl_toml.read_tracker_serial_section()`
is the SSOT for the LiDAR USB device path passed to the container.
Reads tracker-owned `[serial] lidar_port` (canonical dotted name
`serial.lidar_port`, verified at
`production/RPi5/src/core/config_schema.hpp:120`). Operator-locked
SSOT discipline — webctl reads tracker keys but does NOT add
`serial_lidar_port` to `WebctlSection` (PR #63 lock-in).

Pinned by:
- `tests/test_mapping.py::test_state_json_round_trip_and_idle_default`
- `tests/test_mapping.py::test_status_reconcile_preserves_started_at_when_running`
- `tests/test_mapping.py::test_resolve_lidar_port_reads_tracker_serial_section`
- `tests/test_mapping.py::test_concurrent_start_returns_409_via_flock`

### (ae) issue#14 — Mapping monitor SSE producer lifecycle

`mapping_sse.py::_MonitorBroadcast` is a **process-singleton** ticker.
At most ONE asyncio task runs the per-tick monitor snapshot at any
given time, regardless of how many HTTP subscribers are connected.
Subscribers register a per-connection `asyncio.Queue` and the ticker
fans out the same `bytes` frame to every queue (broadcast pattern,
operator-locked M4 fix).

**Cost-bound**: subprocess invocations (`docker stats` / `df` / `du`
inside `monitor_snapshot`) happen once per tick (`MAPPING_MONITOR_TICK_S
= 1.0 s`), NOT once per tick × subscriber count. Without this, N=5
debug tabs would fork 5× `docker stats` per second on the same
container — the Docker daemon's first-call cold-path latency makes
the cost super-linear.

**Lifecycle** (S2 amendment — no fallback polling):
1. First subscriber: ticker task starts.
2. Per-tick: snapshot composed, broadcast to all queues.
3. `container_state ∈ {no_active, exited}`: emit one final frame,
   broadcast `b"__close__"`, ticker task exits. Subscribers' generators
   close cleanly.
4. Subscriber disconnects: queue removed from broadcast list. If
   subscriber count hits 0, ticker keeps running for
   `MAPPING_MONITOR_IDLE_GRACE_S = 5.0 s` to absorb tab-switch
   reconnects without thrash, then exits.

**Slow-client policy**: per-subscriber `asyncio.Queue(maxsize=8)`.
A subscriber whose queue fills (slow client) drops frames from the
ticker's perspective — never blocks the broadcast for everyone else.
The SPA's freshness gate surfaces the gap to the operator.

Pinned by:
- `tests/test_mapping_sse.py::test_singleton_ticker_one_snapshot_per_tick_regardless_of_subscriber_count`
  (5 concurrent subscribers × 3 ticks → exactly 3 snapshot invocations).
- `tests/test_mapping_sse.py::test_stream_self_terminates_when_container_exits_mid_stream`.

### (af) issue#14 — Mapping preview path SSOT + PNG re-encode

`mapping.preview_path(cfg, name)` is the SOLE producer of the realpath-
contained `<cfg.maps_dir>/.preview/<name>.pgm` path used by
`/api/mapping/preview`. The leading-dot subdirectory is hidden from
`maps.list_pairs` (which rejects leading-dot stems via
`MAPS_NAME_REGEX`) — the preview file never appears in Map > Overview.

The preview node inside the container (`godo-mapping/preview_node/preview_dumper.py`)
is the SOLE writer of these files; its atomic write (`tmp + os.replace`)
guarantees the SPA never sees a half-written PGM.

**D5 amendment**: webctl re-encodes the PGM to PNG via
`map_image.render_pgm_to_png` so the SPA renders without a custom
PGM decoder. The C5 leading-dot rejection means the preview file
never collides with a regular map — even if the operator names the
new map `studio_v1` and the canonical `studio_v1.pgm` ends up next to
`.preview/studio_v1.pgm` in the same directory tree.

Pinned by:
- `tests/test_mapping.py::test_preview_path_returns_canonical_path_under_maps_dir`
- `tests/test_mapping.py::test_preview_path_rejects_traversal_via_invalidname`
- `tests/test_app_integration.py::test_get_mapping_preview_returns_404_when_idle`

## Phase 4.5 follow-up candidates

- Deadline-based UDS timeout (single shared `monotonic()` budget per
  request, not per syscall). Would convert worst-case wall-clock from
  `~3 × timeout` to exactly `timeout`.
- `/api/config` GET/PATCH (Tier-2 reload-class table per `SYSTEM_DESIGN.md`).
- React frontend; SSE for `/api/health` to drop the 1 s polling cost.
- `SocketGroup=godo` in the tracker unit so webctl can run as a
  different uid.

## Change log

### 2026-05-02 16:30 KST — issue#14 round 2 + Mode-B fold + PR #66 hotfix bundle

#### Why

Round 1 (commit `9c44906`) shipped the mapping coordinator + endpoints
+ singleton-ticker SSE producer. Mode-B then surfaced 3 findings (C1
Settings/[webctl] wire dead, M1 cross-trio invariant missing, M2
System tab admin endpoint bypassed coordinator) + operator UX
follow-ups (state badge, frontend timeout for long-running endpoints,
Map zoom auto-fit must use actual canvas dims). PR #66 hotfix bundle
shipped in parallel: backup endpoint phantom failure (deprecated
`cfg.map_path` Track-E fallthrough), Config input clearing UX bug,
backup-flash banner, Apply no-op suppression, modified-key amber dot.

#### Added

- `src/godo_webctl/__main__.py::_augment_with_webctl_section()` (Mode-B
  C1 fix) — after `load_settings()`, binds the [webctl] TOML value
  for `mapping_webctl_stop_timeout_s` to the live `Settings` instance.
  Env precedence preserved (only overwrites when current value matches
  the bare module default = env did not fire). Pre-fix
  `cfg.mapping_webctl_stop_timeout_s` was env+default-only — operator
  edits via Config tab → tracker writes via `render_toml` → webctl
  never re-read it.
- `tests/test_main_settings_augmenter.py` (6 cases) — TOML override /
  env preservation / missing file / malformed / [webctl] missing /
  torn-ladder rejection.
- `src/godo_webctl/app.py::system_service_action` Mode-B M2(a) gate —
  when `name == MAPPING_UNIT_NAME.removesuffix(".service")` AND
  `mapping.status(cfg).state ∈ {Starting, Running, Stopping}`, return
  409 `mapping_pipeline_active` with Korean detail. Stops curl /
  second-tab admin from corrupting state.json mid-mapping.
- `tests/test_app_integration.py::test_post_system_service_godo_mapping_active_blocked_when_mapping_running`
  (3 actions × 409) + `..._allowed_when_mapping_idle`.
- `tests/test_config_schema_parity.py::test_constants_mapping_stop_timeout_matches_schema_default_repr`
  (Mode-B Mn2) — pins `MAPPING_CONTAINER_STOP_TIMEOUT_S` against the
  C++ schema row's `default_repr` so a drift fails CI rather than
  silently appearing at first install.
- `src/godo_webctl/protocol.py::DOCKER_MAPPING_PROCESS_NAMES` (Mode-B
  N1) — `frozenset({"docker", "dockerd", "containerd"})` + prefix
  match for `containerd-shim*`. `processes.classify_pid` now returns
  `"godo"` for these so the SPA ProcessTable bolds + accent-colors
  them (operator-confirmed: docker is only used for godo-mapping).
- `tests/test_processes.py::test_classify_pid_docker_family` (5 cases
  + negative no-false-positives).
- `src/godo_webctl/maps.py::MapEntry.{width_px,height_px,resolution_m}`
  (operator UX 2026-05-02) — added so SPA Map list can render
  `WxH px (X.X×Y.Y m)`. New helper `read_yaml_resolution` does a
  bounded read (`YAML_HEADER_MAX_BYTES = 512`) of the `resolution:`
  line. Either field `None` on malformed → graceful degradation
  (list_pairs still returns the entry).
- `tests/test_maps.py` (7 new cases) — typical / legacy / inline-comment
  / missing / non-numeric / missing-file / list_pairs end-to-end carry.

#### Changed

- `src/godo_webctl/mapping.py::start()` Phase 3 (Mode-B Mn3) — mirrors
  the Phase 2 defensive `try/except StateFileCorrupt` fallback. If
  state.json is briefly corrupt during the under-flock commit, log
  WARNING and YIELD (return `starting_status`) instead of raising
  through the FastAPI handler as a 500. Symmetric error handling
  with the Phase 2 polling loop.
- `src/godo_webctl/app.py::map_backup` (PR #66 Bug A) — was passing
  `cfg.map_path` (deprecated Track-E pre-symlink hook, default
  `/etc/godo/maps/studio_v1.pgm` which doesn't exist on hosts that
  never set `GODO_WEBCTL_MAP_PATH`). Migrated to the same
  `maps_dir/active.pgm` resolution as `/api/map/edit` and
  `/api/map/origin` (`maps.read_active_name` → `maps.pgm_for`). Pre-fix
  404 `map_path_not_found` semantics replaced with 503
  `active_map_missing` (matches sibling endpoints).
- `tests/test_app_integration.py::test_backup_uses_active_symlink_not_cfg_map_path_regression`
  pins the fix: decoy `cfg.map_path` set to a real file under a
  different name, the test asserts the backup still picks up the
  active symlink target.
- `src/godo_webctl/services.py::ALLOWED_SERVICES` extended with
  `godo-mapping@active` so System tab can READ its status (frontend
  disables the action buttons via UX, but the endpoint is reachable
  for the M2(a) escape-hatch curl path — also gated by the
  `system_service_action` 409 above).

#### Tests

- pytest 879 pass (excluding pre-existing `test_app_hardware_tracker.py`
  PR-A admin-gate breakage). 21 new cases this block (6 augmenter +
  2 hard-block + 1 schema-parity + 5 docker-family + 7 map-dimensions).
- ruff clean on touched files.

---

### 2026-05-01 23:21 KST — issue#14: SPA Mapping pipeline + monitor

Webctl now owns the full mode-coordinator state machine for the
SPA-driven SLAM mapping pipeline (D1). The C++ tracker UDS surface is
NOT extended — the coordinator's authoritative state is
``<mapping_runtime_dir>/state.json`` reconciled against
``docker inspect`` on every read.

#### Added

- `src/godo_webctl/mapping.py` — mode coordinator. Public surface
  `start(name, cfg)`, `stop(cfg)`, `status(cfg)`, `preview_path(cfg, name)`,
  `journal_tail(cfg, n)`, `monitor_snapshot(cfg)`. Exception hierarchy
  `MappingError` + 10 specific subclasses.
- `src/godo_webctl/mapping_sse.py` — singleton-ticker broadcast SSE
  producer for `/api/mapping/monitor/stream` (M4). One ticker task,
  per-subscriber `asyncio.Queue` fan-out; one snapshot invocation per
  tick regardless of N subscribers. Self-terminates on container exit
  (S2 — no fallback polling).
- 6 new endpoints in `app.py`:
  `POST /api/mapping/start` (admin),
  `POST /api/mapping/stop` (admin),
  `GET /api/mapping/status` (anon),
  `GET /api/mapping/preview` (anon, PNG via `map_image.render_pgm_to_png`),
  `GET /api/mapping/monitor/stream` (anon SSE),
  `GET /api/mapping/journal?n=…` (anon).
- L14 lock-out — `/api/calibrate`, `/api/live`, `/api/map/edit`,
  `/api/map/origin` return 409 `mapping_active` when
  `mapping.status().state ∈ {Starting, Running, Stopping}`.
- `webctl_toml.read_tracker_serial_section()` — sibling helper that
  reads tracker-owned `[serial] lidar_port` (canonical dotted name
  `serial.lidar_port`, verified at
  `production/RPi5/src/core/config_schema.hpp:120`). Does NOT add the
  key to `WebctlSection` — tracker-owned schema rows stay out of the
  webctl-namespaced dataclass per PR #63 lock-in.

#### Changed

- `config.py` — three new Settings fields: `mapping_runtime_dir`
  (default `/run/godo/mapping`), `mapping_image_tag` (default
  `godo-mapping:dev`), `docker_bin` (default `/usr/bin/docker`).
- `protocol.py` — added `MAPPING_STATE_*`, `MAPPING_STATUS_FIELDS`,
  `MAPPING_MONITOR_FIELDS`, 13 new error codes.
- `constants.py` — Tier-1 mapping constants (regex, name max len,
  reserved set, runtime dir default, container/unit names, image tag
  default, SSE tick + idle grace, container start/stop timeouts,
  docker subprocess timeouts, journal tail bounds).

#### Tests

- `tests/test_mapping.py` — 30 cases: state.json round-trip + corrupt
  recovery, validate_name matrix (regex + reserved + leading-dot C5
  pin), preview_path containment, lidar_port resolution from
  tracker.toml, envfile atomic write, full state machine
  Idle→Starting→Running happy path with mocked subprocess, image-
  missing pre-flight (state stays Idle), tracker-stop-failed → Failed,
  container_start_timeout → Failed + cleanup, abort path
  Starting→Stopping→Idle (m10), Failed→Idle acknowledge with preview
  cleanup, M3 boot-reconcile preserves `started_at`, monitor_snapshot
  composition + partial-failure degradation, humanize-bytes parser
  edge cases, journal_tail bounds + `--since` filter, flock defence.
- `tests/test_mapping_sse.py` — 5 cases: one frame per tick,
  self-terminate on Idle/exited, M4 singleton-ticker pin (5
  subscribers × 3 ticks → exactly 3 snapshot invocations), cancel-safe.
- `tests/test_app_integration.py` — 12 new cases covering the 6 new
  endpoints + L14 lock-out for `/api/calibrate`, `/api/live`,
  `/api/map/edit`, `/api/map/origin`.
- `tests/test_constants.py` — 22 mapping-constant pins including the
  M5 stop-timeout ordering invariant
  (`docker grace 10s < TimeoutStopSec 20s < webctl 25s`).
- `tests/test_protocol.py` — 5 mapping-protocol pins covering the
  state-string set, status-field tuple, monitor-field tuple, error-
  code values.
- `tests/test_webctl_toml.py` — 6 tracker-serial section pins
  (default-when-missing-file, default-when-missing-section, verbatim
  read, empty-string fallback, non-string rejection, malformed-TOML
  propagation).
- `tests/test_config.py` — extended for the 3 new Settings fields.

#### New invariants

`(ad) Mapping coordinator location` — `mapping.py` is the SOLE writer
of `<mapping_runtime_dir>/state.json` and the SOLE caller of
`systemctl start|stop godo-mapping@active.service` from webctl. The
tracker is NEVER notified of mapping mode through UDS; coordinator
state derives purely from the file + `docker inspect`. Boot-reconcile
preserves `started_at` (M3) so `journalctl --since=<started_at>`
keeps surfacing the original launch window's logs after a webctl
restart. Pinned by `tests/test_mapping.py::test_status_reconcile_*`.

`(ae) Mapping monitor SSE producer lifecycle` — `mapping_sse.py`
implements a process-singleton broadcast ticker. One asyncio task
runs per process at any given time; per-subscriber `asyncio.Queue`
fans out the same `bytes` frame. Subprocess cost is O(1) per tick
regardless of subscriber count (M4). Ticker self-terminates within
one tick of `container_state ∈ {no_active, exited}`; subscribers
freeze the last frame and show "중단됨" badge (S2). No fallback
HTTP polling. Pinned by
`tests/test_mapping_sse.py::test_singleton_ticker_one_snapshot_per_tick_regardless_of_subscriber_count`.

`(af) Mapping preview path SSOT + PNG re-encode` — `mapping.preview_path(cfg, name)`
is the SOLE producer of the realpath-contained
`<cfg.maps_dir>/.preview/<name>.pgm` path used by
`/api/mapping/preview`. The endpoint re-encodes via
`map_image.render_pgm_to_png` (D5 amendment) so the SPA renders PNG
without a custom decoder. The `.preview/` subdirectory's leading dot
keeps it out of `maps.list_pairs` (which rejects leading-dot names
via `MAPS_NAME_REGEX`). Pinned by realpath-containment tests in
`test_mapping.py`.

### 2026-05-01 18:07 KST — issue#5 default-flip + issue#12 latency defaults (combined PR)

Two operator-locked HIL follow-ups bundled into one PR; webctl owns the
runtime consumer side of issue#12 B2 (SSE pose+scan rate config-driven).

**What changed (webctl side)**:

- New leaf module `godo_webctl/webctl_toml.py` (~190 LOC + tests)
  exporting `read_webctl_section(toml_path, env=None) ->
  WebctlSection`. Precedence env > TOML > default; range validation
  [1, 60]; defaults 30 Hz / 30 Hz; raises `WebctlTomlError` on bad
  input. Constants pinned in this module per Mode-A N5 / Parent A8
  (NOT in `constants.py`) so the dep edge stays
  `sse.py → webctl_toml.py → stdlib`.
- `Settings` gains `tracker_toml_path: Path` (default
  `/var/lib/godo/tracker.toml`, override via
  `GODO_WEBCTL_TRACKER_TOML_PATH`). Wired through
  `_DEFAULTS` / `_PARSERS` / `_ENV_TO_FIELD`.
- `sse.py::last_pose_stream` and `last_scan_stream` resolve their
  per-tick sleep at stream open via two new private helpers
  (`_resolve_pose_tick_s`, `_resolve_scan_tick_s`) that wrap
  `webctl_toml.read_webctl_section` in a try/except (default fallback
  on `WebctlTomlError`).
- `sse.py::diag_stream`, `services_stream`, `processes_stream`,
  `resources_extended_stream` are UNCHANGED — operator-locked
  "지도 부분에만 적용".
- `__main__.py::main` calls a new `_log_resolved_sse_rates` helper that
  reads the section + logs INFO on success or WARNING on failure
  (Mode-A M6 / Parent A6: service must boot regardless of malformed
  tracker.toml).
- `config_schema.py::EXPECTED_ROW_COUNT` 46 → 48.

**Tests**:

- `tests/test_webctl_toml.py` — NEW, 28 cases.
- `tests/test_sse.py` — pose+scan default 30 Hz cadence pin (was
  5 Hz / `SSE_TICK_S` 0.2 s before issue#12); 4 new TOML/env injection
  cases; `diag_stream` regression pin that it still uses `SSE_TICK_S`.
- `tests/test_config.py` — `tracker_toml_path` parity check, default
  value pin.
- `tests/test_config_schema.py`, `test_config_schema_parity.py`,
  `test_config_view.py`, `test_app_integration.py` — row count 46 → 48
  + presence checks for the two `webctl.*` rows.

**Tracker side (cross-link)**: see `production/RPi5/CODEBASE.md`
invariant `(r)` and the dated change-log entry under the same date.

**New invariant**: `(ac)` "issue#12 — webctl-owned schema rows +
tracker.toml SSOT" — see body above.

### 2026-05-01 15:17 KST — issue#5: schema row count 42 → 46 (Live-carry mirror bump)

Leaf-only change-log entry per CLAUDE.md cascade rule. The C++ tracker
adds four Tier-2 keys for the Live pipelined-hint kernel (see
`production/RPi5/CODEBASE.md` invariant (q) + the dated entry under the
same date); webctl mirrors only the row-count assertions because the
regex parser auto-extracts new rows without code changes. No new
invariant; existing invariant (b) "Cross-language SSOT (no auto-sync)"
covers the parity contract.

#### Changed

- `src/godo_webctl/config_schema.py::EXPECTED_ROW_COUNT` 42 → 46. The
  regex parser auto-extracts the four new C++ rows
  (`amcl.live_carry_pose_as_hint` Bool-as-Int selector,
  `amcl.live_carry_schedule_m` schedule string,
  `amcl.live_carry_sigma_xy_m`, `amcl.live_carry_sigma_yaw_deg`) without
  parser-code change; only the row-count assertion needs to track the
  C++ static_assert. Module docstring example bumped in lockstep.
- `tests/test_config_schema.py` — `test_load_schema_real_source_returns_42_rows`
  → `..._46_rows`; `test_parse_rejects_short_row_count` synthetic
  fixture wrapper bumped 42 → 46.
- `tests/test_config_schema_parity.py` — `test_row_count_pinned_at_42`
  → `..._46`; `test_static_assert_in_cpp_says_42_too` →
  `..._46_too`; docstring header bumped.
- `tests/test_config_view.py::test_project_schema_view_real_source` —
  expected list length 42 → 46.
- `tests/test_app_integration.py` — `GET /api/config/schema` row-count
  assertion 42 → 46.

#### Test counts

- Backend: 683 passed, 1 deselected (unchanged; this PR adds zero new
  webctl-side tests — only the row-count literals shift to track the
  C++ schema's `static_assert`).

### 2026-04-30 14:37 KST — Track B-MAPEDIT-2 (Phase 4.5 P2) — origin pick (dual GUI + numeric input)

#### Added

- `src/godo_webctl/map_origin.py` — Sole-owner module for the YAML
  `origin:` line rewrite. `apply_origin_edit(active_yaml, x_m, y_m, mode)`
  reads the YAML text, locates the unique flow-style `origin: [x, y, theta]`
  line, rewrites ONLY `origin[0]` and `origin[1]` (theta + every other
  byte preserved), and writes atomically through tmp + `os.replace` (mode
  0644). Custom exceptions `OriginEditError`, `ActiveYamlMissing`,
  `OriginYamlParseFailed`, `BadOriginValue`, `OriginEditFailed`. Theta
  passthrough rule: theta token bytes are preserved VERBATIM (never
  parse + repr). Sign convention for `mode == "delta"` is ADD (operator-
  locked 2026-04-30 KST): `new = current + typed`. Block-scalar YAML form
  rejected with `flow_style_required`. Module discipline: does NOT import
  `maps.py` (Track E uncoupled-leaves).
- `src/godo_webctl/protocol.py` — `ERR_ORIGIN_BAD_VALUE`,
  `ERR_ORIGIN_YAML_PARSE_FAILED`, `ERR_ORIGIN_EDIT_FAILED`,
  `ERR_ACTIVE_YAML_MISSING`, `ORIGIN_EDIT_RESPONSE_FIELDS = ("ok",
  "backup_ts", "prev_origin", "new_origin", "restart_required")`,
  `ORIGIN_MODE_ABSOLUTE = "absolute"`, `ORIGIN_MODE_DELTA = "delta"`,
  `VALID_ORIGIN_MODES`. SPA mirror in `lib/protocol.ts`.
- `src/godo_webctl/constants.py` — `ORIGIN_BODY_MAX_BYTES = 256`
  (single-key JSON body cap), `ORIGIN_X_Y_ABS_MAX_M = 1_000.0` (magnitude
  bound covering studio + 100× headroom; rationale comment).
- `src/godo_webctl/app.py` — `OriginPatchBody` Pydantic class
  (`x_m: float`, `y_m: float`, `mode: Literal["absolute","delta"]`),
  `_map_origin_exc_to_response` shape mapper, `POST /api/map/origin`
  admin-gated handler. Three-step sequence (mirror of `/api/map/edit`):
  resolve active YAML via `maps.read_active_name + maps.yaml_for` →
  backup via `backup.backup_map(active_pgm, cfg.backup_dir)` (PGM
  unchanged but archived per `backup_map`'s pair contract) →
  `map_origin.apply_origin_edit(...)` → `restart_pending.touch(...)` →
  activity log `"map_origin"`. Body-size pre-check returns 413
  `bad_payload + detail=body_too_large` (mirror of `PATCH /api/config`
  precedent at app.py:888-892). NaN/Inf load-bearing check is
  `math.isfinite` (Pydantic's `allow_inf_nan` is best-effort defence-
  in-depth). `map_image.invalidate_cache()` is intentionally NOT called
  (PNG cache key is PGM realpath + mtime, both unchanged by an origin
  edit).
- `tests/test_map_origin.py` — 23 unit cases: absolute/delta happy paths,
  ADD sign-convention pin, theta passthrough parametrized over `1.5e-3`
  / `-0.0` / high-precision tokens, all-non-origin-lines byte-for-byte,
  inline comment preserved, missing/duplicate/block-scalar `origin:`
  rejection, atomic-write `*.tmp` cleanup-on-failure, bad-mode defence,
  module-discipline (no maps.py import), high-precision round-trip,
  whitespace variants (T3 fold), CRLF preservation, delta overflow.
- `tests/test_app_integration.py` — 15 new integration cases:
  admin/anon/viewer auth gating, absolute/delta happy paths, NaN/Inf
  rejection (S5), bad-mode 422-or-400, active-map-missing 503,
  backup-failure-aborts-yaml-untouched (R1), restart-pending
  touched-on-success and not-touched-on-failure (S3), activity log
  `"map_origin"` literal pin (M5), `backup_ts` matches snapshot AND
  snapshot YAML reflects pre-edit origin bytes (S1),
  oversize-returns-413 (M3 Option A), locale-comma-string-rejected
  (T4 fold).
- `tests/test_protocol.py` — `test_origin_error_codes_pinned`,
  `test_origin_edit_response_fields_pinned`, `test_origin_modes_pinned`
  (cross-language drift catches against `lib/protocol.ts`).
- `tests/test_constants.py` — `test_origin_body_max_bytes_pinned`,
  `test_origin_x_y_abs_max_m_pinned`.

#### Changed

- `tests/conftest.py::tmp_active_map_pair` — fixture YAML now writes
  `origin: [-1.5, -2.0, 0.0]` (instead of `[0, 0, 0]`) plus
  `mode: trinary` so origin-edit tests have a non-zero baseline to
  round-trip against. Existing `test_map_edit.py` tests do NOT inspect
  the YAML origin and continue to pass.
- `tests/conftest.py::read_active_yaml_origin` — new helper for
  round-trip assertions (re-parses on-disk YAML).

#### Invariants

- Added `(ab)`: `map_origin.py` is the SOLE owner of the YAML origin
  metadata-rewrite. Three-step sequence (backup → YAML rewrite →
  sentinel) is contractual; theta byte passthrough; ADD sign convention;
  block-scalar form rejected; activity log type literal `"map_origin"`.
- Extended `(n)` (admin-gated mutations): added `POST /api/map/origin`.

#### Test counts

- Backend: 671 tests (was 628 baseline; +43 new). Full suite
  `uv run pytest -m "not hardware_tracker"` green.

### 2026-04-30 11:30 KST — Track B-MAPEDIT (Phase 4.5 P2 Step 3) — brush-erase + auto-backup + restart-required

#### Added

- `src/godo_webctl/map_edit.py` — Sole-owner module for the mask→PGM
  transform. `apply_edit(active_pgm, mask_png_bytes)` decodes the
  multipart mask via Pillow, validates dimensions, rewrites painted
  cells to `MAP_EDIT_FREE_PIXEL_VALUE = 254`, and writes atomically
  through tmp + `os.replace` (mode 0644). Custom exceptions
  `MapEditError`, `ActiveMapMissing`, `MaskDecodeFailed`,
  `MaskShapeMismatch`, `MaskTooLarge`, `EditFailed`. ~290 LOC.
- `src/godo_webctl/restart_pending.py::touch(flag_path)` — webctl's
  new write path for the sentinel file at `cfg.restart_pending_path`.
  Atomic create-or-replace via tmp + `os.replace` (mode 0644). Writes
  an ISO-8601 UTC stamp body (informational; readers only check
  presence). Tracker remains the clear path at boot via its existing
  `clear_pending_flag()` — both processes run as uid `ncenter` so the
  cross-process write/read/clear cycle is permission-clean.
- `src/godo_webctl/app.py` — `_map_edit_exc_to_response` shape mapper
  + `POST /api/map/edit` route handler (admin-gated, multipart). The
  three-step sequence is contractual per invariant (aa):
  `backup_map` → `apply_edit` → `restart_pending.touch`.
  Content-length check runs BEFORE multipart decode (T2 fold).
- `src/godo_webctl/protocol.py` — `ERR_MASK_SHAPE_MISMATCH`,
  `ERR_MASK_TOO_LARGE`, `ERR_MASK_DECODE_FAILED`, `ERR_EDIT_FAILED`,
  `ERR_ACTIVE_MAP_MISSING`, `EDIT_RESPONSE_FIELDS = ("ok", "backup_ts",
  "pixels_changed", "restart_required")`.
- `src/godo_webctl/constants.py` — `MAP_EDIT_MASK_PNG_MAX_BYTES =
  4_194_304` (4 MiB), `MAP_EDIT_FREE_PIXEL_VALUE = 254`,
  `MAP_EDIT_PAINT_THRESHOLD = 128`.
- `tests/conftest.py` — `tmp_active_map_pair` fixture (8×8 PGM, all
  cells 100, with `active.{pgm,yaml}` symlinks) +
  `make_test_pgm_bytes` / `make_test_mask_png` helpers.
- `tests/test_map_edit.py` — 14 cases: empty/full/partial mask;
  dimensions mismatch; non-PNG decode failure; oversize;
  atomic-write failure (no leftover .tmp per S3 fold); active-pgm
  missing; header preserved; RGBA alpha-as-paint; constants drift
  catch; greyscale 128-threshold boundary (T1 fold); idempotent
  re-paint; module-discipline pin (no `from .maps`).
- `tests/test_restart_pending.py` — 3 cases for the new `touch()`
  writer: creates-from-missing, idempotent, atomic-no-partial.
- `tests/test_app_integration.py` — 11 cases for `POST /api/map/edit`:
  admin happy + anon 401 + viewer 403 + shape mismatch 400 +
  active-pgm missing 503 + backup-failure aborts (PGM mtime unchanged)
  + restart-pending sentinel created + activity log type
  literal `"map_edit"` (M2 fold) + S1 backup-ts disk match +
  T2 oversize 413 before decode + T3 failure leaves no restart-
  pending.
- `tests/test_protocol.py` — pins for `ERR_MASK_*` codes +
  `EDIT_RESPONSE_FIELDS` (S2 fold — `restart_required` literal value
  pin).
- `tests/test_constants.py` — pins for the three new `MAP_EDIT_*`
  constants.

#### Changed

- Invariant (n) extended: `POST /api/map/edit` added to the admin-
  gated mutations list.
- Invariant (aa) added: SOLE-owner discipline + three-step sequence
  + sentinel writer/reader split (M3 fold) + greyscale threshold +
  Pillow decode semantics + activity log type literal `"map_edit"`.

#### Removed

- (none)

#### Tests

- 594 → 628 hardware-free pytest (+34 from this PR; +14 unit map_edit,
  +3 restart_pending touch, +11 integration map_edit, +5 pin tests in
  protocol/constants, +1 fixture coverage).
- `ruff check` clean on PR paths (1 pre-existing E402 in
  `config_schema.py` is unchanged from main).
- `ruff format` applied across modified files (3 pre-existing
  unformatted files in `config_schema.py` / `services.py` /
  `test_services.py` are unchanged from main).
- `python-multipart` is NOT a new dependency: Starlette 1.0's
  built-in multipart parser handles `request.form()` for our
  single-part body.
- `pillow` is unchanged (already a transitive dep at v12.2.0 — N2
  fold confirmed).

#### Mode-A folds applied

- M1 (letter shift) — webctl invariant uses `(aa)` (NOT `(y)` as the
  plan reserved): on main `(y)` was taken by Track D (close-out note
  in CODEBASE.md change log already flagged this); `(z)` was then
  taken by PR-B; the next free letter at writer kickoff was `(aa)`.
  Recorded as a deviation in the writer's handoff report.
- M2 — activity log type literal is `"map_edit"` (imperative-style,
  matches existing convention).
- M3 — invariant (aa) prose includes the writer/reader split
  paragraph: webctl OWNS touch, tracker OWNS clear, both at uid
  `ncenter`.
- S1 — `test_map_edit_backup_ts_matches_disk_snapshot` integration
  case asserts the returned `backup_ts` is reflected in
  `/api/map/backup/list` and the on-disk backup directory holds the
  pre-edit bytes.
- S2 — `test_map_edit_admin_happy_path` asserts
  `resp["restart_required"] is True`; `test_edit_response_fields_pinned`
  pins the literal value via the tuple + a presence check.
- S3 — atomic write mirrors `auth.py::_write_atomic`;
  `test_apply_edit_atomic_write` asserts no `*.tmp` survives a
  failed `os.replace`.
- T1 — `test_apply_edit_grey_threshold_boundary` pins 127 NOT
  painted, 128 painted (with 200/0 controls).
- T2 — `test_map_edit_oversize_returns_413_without_decode` pins
  content-length-before-decode ordering.
- T3 — `test_map_edit_failure_leaves_no_restart_pending` is the
  anti-monotone partner of `_touches_restart_pending`.
- N1 — invariant (aa) prose cross-references PR #27's `/system`
  restart UX as an alternative to `/local` for non-loopback admins.
- N2 — `pyproject.toml` unchanged (Pillow already transitive).
- N3 — total LOC ~1050 across backend + frontend (within plan
  estimate, below the 1500 ceiling).

### 2026-04-30 14:00 KST — Track B-SYSTEM PR-B (backend) — process monitor + extended resources

#### Added

- `src/godo_webctl/processes.py` — stdlib `/proc` walker.
  `parse_proc_stat_total_jiffies`, `parse_pid_stat` (rfind-')')
  paren-handling), `parse_pid_status_rss_kb`, `parse_pid_status_uid`,
  `parse_pid_cmdline` (NUL-split + `godo-webctl` argv exception),
  `cpu_pct_from_deltas` (multi-core uncapped), `classify_pid`,
  `enumerate_all_pids`, `class ProcessSampler`. Module-level
  `_uid_cache` per Mode-A N2 fold. Module docstring carries an
  "Expected cost" stanza per Mode-A M9 fold (5–15 ms CPU per tick on
  cores 0–2, <2 MB resident). ~430 LOC.
- `src/godo_webctl/resources_extended.py` — stdlib per-core CPU delta
  + `/proc/meminfo` + `os.statvfs`. `class CoreJiffies`,
  `_read_cpu_per_core_jiffies`, `per_core_pct_from_deltas`,
  `_read_meminfo_total_avail`, `_read_disk_pct`,
  `class ResourcesExtendedSampler`. NO GPU paths (operator decision).
  Deliberately NOT re-export-merged with `resources.py` per Track E
  uncoupled-leaves discipline. ~225 LOC.
- `src/godo_webctl/protocol.py` —
  `GODO_PROCESS_NAMES` (5-element frozenset),
  `MANAGED_PROCESS_NAMES` (3-element frozenset),
  `PROCESS_FIELDS` (10 fields incl. `category`),
  `PROCESSES_RESPONSE_FIELDS` (3 fields),
  `EXTENDED_RESOURCES_FIELDS` (6 fields, GPU absent).
- `src/godo_webctl/constants.py` — `PROC_PATH`, `PROC_STAT_PATH`,
  `SSE_PROCESSES_TICK_S`, `SSE_RESOURCES_EXTENDED_TICK_S`.
- `src/godo_webctl/sse.py` — `processes_stream`, `resources_extended_stream`
  generators with per-subscriber sampler injection (mirror of
  `RecordingSleep` test pattern in `last_pose_stream`).
- `src/godo_webctl/app.py` — `_processes_view`, `_extended_resources_view`
  projections; 4 new GET handlers:
  `/api/system/processes`, `/api/system/processes/stream`,
  `/api/system/resources/extended`, `/api/system/resources/extended/stream`.
- `tests/test_processes.py` — 38 cases.
- `tests/test_resources_extended.py` — 20 cases.
- `tests/test_protocol.py` — 5 PR-B pin cases.
- `tests/test_sse.py` — 6 PR-B SSE cases.
- `tests/test_app_integration.py` — 9 PR-B integration cases (anon +
  admin + duplicate-alert propagation + per-row schema +
  query-params-ignored + 2 stream smokes + 2 resources cases).

#### Changed

- Invariant (z) added (see above).

#### Removed

- (none)

#### Tests

- 501 → 594 hardware-free pytest (+93 from this PR-B backend half;
  combined Python new cases 78 incl. the 15 sub-protocol/sse pins).
- `ruff check` clean on PR-B paths (one pre-existing E402 in
  `config_schema.py` unchanged).
- `ruff format` applied across modified files.

#### Mode-A folds applied

- Final fold (07:09 KST) — body's GPU references treated as dead text;
  six-field `EXTENDED_RESOURCES_FIELDS`. M3 — wire field is
  `category` everywhere. M4 — `enumerate_all_pids` (not
  `enumerate_godo_pids`); classifier consumes `GODO_PROCESS_NAMES` +
  `MANAGED_PROCESS_NAMES`. M7 — `(Web Content))` paren-in-comm
  fixture in `test_parse_pid_stat_handles_paren_in_comm`. M8 —
  three explicit cpu_pct edge tests
  (`zero_total_delta_returns_zero`,
  `negative_delta_floors_to_zero`,
  `does_not_clamp_at_100_for_multicore`). M9 — "Expected cost"
  stanzas in both module docstrings. N2 — module-level `_uid_cache`.
  N3 — `os.scandir` over `os.listdir`.

### 2026-04-30 17:30 KST — Track D scale + Y-flip fix

#### Added

- `src/godo_webctl/maps.py` — `read_pgm_dimensions(pgm_path)` pure
  function (parses netpbm `P5` header bytes only, no Pillow) and
  `class PgmHeaderInvalid(ValueError)` exception. ~55 LOC. Per Mode-A
  T5 fold: lives in `maps.py` (NOT a reverse import from
  `map_image.py::MapImageInvalid`) to preserve the Pillow-free
  filesystem-primitives invariant per the module docstring.
- `src/godo_webctl/constants.py` — `PGM_HEADER_MAX_BYTES = 64` (Tier-1).
- `src/godo_webctl/app.py` — `GET /api/maps/{name}/dimensions` handler
  returning `{width, height}`; `_map_maps_exc_to_response` arm extended
  for `PgmHeaderInvalid → 500 map_invalid`.
- `tests/test_maps.py` — 6 cases (`test_read_pgm_dimensions_*` —
  happy + comment-line + 0-byte + no-magic + non-numeric-width +
  byte-bound spy per Mode-A T4 fold).
- `tests/test_app_integration.py` — 4 cases for the dimensions
  endpoint (happy + 404 + 400 + 500 malformed PGM).

#### Changed

- Invariant (y) added (see above).

#### Removed

- (none)

#### Tests

- 491 → 501 hardware-free pytest (+10 from this PR). 1 hardware-marked
  smoke unchanged. ruff check + ruff format clean.

#### Mode-A folds applied

- M4: webctl invariant letter is `(y)` (Track D ships before
  B-MAPEDIT per NEXT_SESSION.md TL;DR ordering;
  `plan_track_b_mapedit.md` §8 M1's `(y)` reservation must shift to
  `(z)` at the B-MAPEDIT writer kickoff).
- T4: byte-bound test spies on `Path.open().read()` to assert
  exactly one read of `PGM_HEADER_MAX_BYTES` bytes against a 1 GB
  sparse PGM.
- T5: `PgmHeaderInvalid` lives in `maps.py`, not a reverse import of
  `map_image.py::MapImageInvalid`.

### 2026-04-29 — PR-1: Single-instance pidfile lock + backup flock

#### Added

- `src/godo_webctl/pidfile.py` — `PidFileLock` ctx-manager (open +
  `fcntl.flock(LOCK_EX | LOCK_NB)` + write own PID + `fsync`); `LockHeld`
  / `LockSetupError` exception types; `format_lock_held_message`
  diagnostic helper (uses `kill(pid, 0)` ONLY for stderr phrasing, NOT
  for the lock decision per Mode-A M4). Module boundary: imported ONLY
  by `__main__.main()`; `create_app()` does NOT depend on it.
- `src/godo_webctl/constants.py` — `BACKUP_LOCK_FILENAME = ".lock"`
  (defence-in-depth target inside `cfg.backup_dir`).
- `tests/test_pidfile.py` — 12 cases (10 per planner §5 + 2 bonus
  module-boundary pins: `test_create_app_does_not_acquire_lock`,
  `test_main_imports_pidfile_but_app_does_not`).
- `tests/test_main_lock.py` — 4 subprocess cases including the TB3
  timing assertion (second instance exits in < 2 s, well below uvicorn
  boot).

#### Changed

- `src/godo_webctl/config.py` — `Settings.pidfile_path: Path` field
  added; default `/run/godo/godo-webctl.pid`; env override
  `GODO_WEBCTL_PIDFILE`; three-table SSOT (`_DEFAULTS` / `_PARSERS` /
  `_ENV_TO_FIELD`) updated in lockstep.
- `src/godo_webctl/__main__.py` — acquires `PidFileLock` BEFORE
  `uvicorn.run`; on `LockHeld` exits 1 with documented stderr; on
  `LockSetupError` exits 1 with parent-dir diagnostic. Installs
  SIGTERM/SIGINT handlers that release the lock + exit 128+signum.
  Uvicorn's `capture_signals` re-raises captured signals after server
  shutdown, which then hits our handler — guarantees pidfile cleanup
  on graceful SIGTERM.
- `src/godo_webctl/backup.py` — wraps mkdir+copy+rename region in
  `fcntl.flock(LOCK_EX | LOCK_NB)` on `<backup_dir>/.lock`. On
  contention raises `BackupError("concurrent_backup_in_progress")`.
  Lock file persists between calls (file presence is NOT the signal —
  the kernel auto-releases lock state on FD close).
- `src/godo_webctl/app.py` — `_map_backup_exc_to_response` arm
  extended: `concurrent_backup_in_progress → HTTPStatus.CONFLICT (409)`
  with body `{ok: False, err: ..., detail: "다른 백업이 진행 중입니다."}`
  (Mode-A M3 fold).
- `tests/conftest.py` — autouse `_pidfile_path_autouse` fixture sets
  `GODO_WEBCTL_PIDFILE=tmp_path / "godo-webctl.pid"` for every test
  (Mode-A M5 + TB5 / TB6 pin: no test touches the production path,
  no inter-test lock state).
- `tests/test_backup.py` — 3 new cases: lock acquired-and-released,
  concurrent acquire raises `concurrent_backup_in_progress`, lock file
  persists but unlocked after call.
- `tests/test_config.py` — `pidfile_path` default + override pinned.
- `tests/test_app_integration.py` — `_settings_for(...)` accepts
  `pidfile_path`; new `test_backup_conflict_returns_409` integration
  test (Mode-A M3 fold).
- `tests/test_sse.py` — `_settings()` constructor extended with
  `pidfile_path` (drift-catch from the new dataclass field).
- `CODEBASE.md` — invariants (e), (f) replaced; (u) added.

#### Removed

- (none)

#### Tests

- 387 → 406 hardware-free pytest (+19 from this PR). 1 hardware-marked
  smoke unchanged. ruff check + ruff format clean.

#### Mode-A folds applied

- M1: tests under `production/RPi5/tests/` (plural, flat).
- M2: invariant (e) preserves the `__main__.py` D11 cross-reference.
- M3: `app.py` 409 mapping + integration test.
- M4: stale-PID is lock-only decision; `kill(pid, 0)` is diagnostic.
- M5: module boundary explicit (`pidfile.py` imported ONLY by
  `__main__`); autouse conftest fixture; `test_create_app_does_not_acquire_lock`.
- N1: invariant (u) cross-references existing (h) — no restated table.
- N4: pidfile content format pinned to `f"{os.getpid()}\n"`.
- N5: invariant (u) and CLAUDE.md call out NFS-unsupported.
- TB1: stale-PID test uses sentinel `2**31 - 1`.
- TB3: timing assertion in `test_second_invocation_exits_under_500ms`.
- TB5/TB6: autouse conftest fixture; per-test isolation documented.

### 2026-04-29 — Track D: Live LIDAR overlay (Phase 4.5+ P0.5)

#### Added

- `src/godo_webctl/protocol.py` — `CMD_GET_LAST_SCAN`,
  `LAST_SCAN_HEADER_FIELDS` (11-tuple), `LAST_SCAN_RANGES_MAX_PYTHON_MIRROR
  = 720`, `LAST_SCAN_RESPONSE_CAP = 32768`, `encode_get_last_scan()`.
- `src/godo_webctl/uds_client.py` — `UdsClient.get_last_scan(timeout)`;
  passes the wider response cap to `_recv_line` so 720-ray replies
  (~14 KiB) fit. The `_roundtrip` and `_recv_line` helpers gain an
  optional `response_cap` / `cap` keyword that only `get_last_scan`
  passes; all other commands keep the standard 4 KiB.
- `src/godo_webctl/sse.py` — `last_scan_stream(client, cfg, *, sleep)`
  async generator. Same 5 Hz cadence + heartbeat + cancel-safety as
  `last_pose_stream`.
- `src/godo_webctl/app.py` — `GET /api/last_scan` (anon, single-shot)
  and `GET /api/last_scan/stream` (anon, SSE @ 5 Hz). Both use
  `_last_scan_view(resp)` to project the UDS reply down to
  `LAST_SCAN_HEADER_FIELDS`. SSE handler creates a fresh per-subscriber
  `UdsClient` (mirror of `/api/last_pose/stream`).
- `tests/test_protocol.py` — 3 new pin tests:
  `test_cmd_get_last_scan_matches_cpp`,
  `test_encode_get_last_scan_byte_exact`,
  `test_last_scan_ranges_max_python_mirror_matches_cpp`,
  `test_last_scan_header_fields_match_cpp_source` (regex-extracts
  field names from `rt_types.hpp` per the planner override).
- `tests/test_uds_client.py` — 3 new cases (happy, server-rejected,
  response_too_large at the wider 32 KiB cap).
- `tests/test_sse.py` — 4 new cases for `last_scan_stream` (5 Hz,
  skip-on-error, keepalive, cancellation).
- `tests/test_app_integration.py` — 7 new cases for
  `/api/last_scan` and `/api/last_scan/stream`: field-set drift catch,
  anon=200, SSE anon=200, path-extras=404, tracker-unreachable=503,
  no-run-yet returns valid=0, server-emits-raw-polar (Mode-A TM5 pin).
  Plus `test_anon_read_endpoints_return_200` symmetric to the existing
  `test_mutation_endpoints_unauth_return_401`.

#### Changed

- Invariant (n) — anonymous-readable list extended with `/api/last_scan`
  and `/api/last_scan/stream`.

#### Tests

- 256 → 275 hardware-free pytest (+19 from this PR).
- `uv run ruff check` + `uv run ruff format --check` clean.

#### Notes

- The wire body emits raw polar (LiDAR-frame `angles_deg` / `ranges_m`)
  + the SCAN's anchor pose. The SPA does the world-frame transform
  using the anchor (NOT a parallel `/api/last_pose` SSE) per Mode-A
  TM5; this preserves the pose ↔ scan temporal correlation an operator
  needs for AMCL convergence debugging.
- LastScan field-name SSOT is `production/RPi5/src/core/rt_types.hpp::
  struct LastScan`; the wire ORDER is set by `format_ok_scan` in
  `json_mini.cpp`. The Python tuple matches the wire order.

### 2026-04-29 — Track E Mode-B folds (corpus parity + WARN pin)

#### Added

- `tests/test_app_integration.py` — 5 new cases:
  - `test_activate_dot_traversal_returns_400` and
    `test_activate_hidden_dot_returns_400` (Mode-B Nit #3): rejection
    corpus for `POST /api/maps/<name>/activate` mirrors the existing
    `image` / `yaml` corpus pattern at :969-1022. String literals (NOT
    parametrize). Routing-vs-handler outcomes (400 / 404 / 405) are
    all accepted as valid rejections per Mode-A TB1 discipline.
  - `test_delete_dot_traversal_returns_400` and
    `test_delete_hidden_dot_returns_400` (same, for DELETE).
  - `test_lifespan_warns_every_boot_when_map_path_set` (Mode-B Nit #4 /
    Q-OQ-E4): pins the `maps.legacy_map_path_in_use` WARNING firing
    on EVERY boot via Starlette `TestClient` lifespan + `caplog`.

#### Changed

- `CODEBASE.md` change-log entry below — `test_maps.py` count
  corrected from 41 to 40 (Mode-B Nit #2). The plan §"Concurrent
  activate" line 552 also listed a leftover-tmp-after-failure case;
  deterministic crash injection across threads via process-global
  monkeypatch is fragile, and the existing pair
  `test_set_active_serializes_under_flock` +
  `test_set_active_crash_mid_yaml_swap_leaves_recoverable_state`
  already pins both contracts.

#### Tests

- 256 hardware-free pytest cases (was 251; +5 from this fold). Net +82
  for Track E + folds combined.

### 2026-04-29 — Track E (PR-C): multi-map management

#### Added

- `src/godo_webctl/maps.py` — pure-function multi-map primitives
  (`validate_name`, `pgm_for`, `yaml_for`, `is_pair_present`,
  `list_pairs`, `read_active_name`, `set_active`, `delete_pair`,
  `migrate_legacy_active`). Custom exceptions `InvalidName`,
  `MapNotFound`, `MapIsActive`, `MapsDirMissing`. SOLE owner of every
  FS touch in `cfg.maps_dir` (invariant (o)).
- `src/godo_webctl/constants.py` — `MAPS_NAME_REGEX`,
  `MAPS_NAME_MAX_LEN = 64`, `MAPS_ACTIVE_BASENAME = "active"`,
  `MAPS_ACTIVATE_LOCK_BASENAME = ".activate.lock"`.
- `src/godo_webctl/protocol.py` — 4 new error-code mirrors
  (`ERR_INVALID_MAP_NAME`, `ERR_MAP_NOT_FOUND`, `ERR_MAP_IS_ACTIVE`,
  `ERR_MAPS_DIR_MISSING`) + `MAPS_NAME_REGEX_PATTERN_STR` for the SPA
  client-side validator.
- `src/godo_webctl/app.py` — 5 new endpoints:
  - `GET    /api/maps` (anon, Track F),
  - `GET    /api/maps/<name>/image` (anon),
  - `GET    /api/maps/<name>/yaml` (anon),
  - `POST   /api/maps/<name>/activate` (admin),
  - `DELETE /api/maps/<name>` (admin).
  + `_map_maps_exc_to_response` shape mapper kept local to `app.py`.
  + `lifespan` runs `maps.migrate_legacy_active` once on boot if
  `${maps_dir}/active.pgm` is missing AND `cfg.map_path` is set; logs
  WARN every boot (per Q-OQ-E4) until `cfg.map_path` is unset.
- `src/godo_webctl/map_image.py::invalidate_cache()` — public hook
  called by `app.py` after a successful activate so the next
  `/api/map/image` GET re-renders.
- `scripts/godo-maps-migrate` — operator one-shot bash that mirrors
  `migrate_legacy_active`; `ln -sfT` for the symlink swap (atomic).
- `tests/test_maps.py` — 40 cases. Includes path-traversal corpus
  (string literals, NOT parametrize), `realpath` containment pin (M1),
  stale-tmp sweep pin (M3), crash-mid-yaml-swap recovery,
  concurrent-activate flock serialization with arrival-order pinned (TB3).
  (The plan §"Concurrent activate" line 552 also listed a multi-thread
  no-leftover-tmp-after-failure case; deterministic crash injection
  across threads via process-global monkeypatch is fragile, and the
  combination of `test_set_active_serializes_under_flock` and
  `test_set_active_crash_mid_yaml_swap_leaves_recoverable_state` already
  pins both the serialisation contract and the leftover-sweep contract.)
- `tests/test_app_integration.py` — 22 new cases for the 5 endpoints
  + back-compat boot path. Per-endpoint rejection corpus, anon → 401
  on mutations, admin → 200 happy paths, delete-active → 409
  (named test, NOT folded into delete suite).
- `tests/test_map_image.py` —
  `test_cache_invalidates_on_symlink_target_change_same_mtime` (TB2:
  pins `_entry.path == os.path.realpath(target)` directly, NOT just
  PNG byte comparison) + `test_cache_invalidates_on_symlink_target_path_change`.
- `tests/conftest.py` — `tmp_maps_dir` fixture (two pairs +
  active symlinks).

#### Changed

- `src/godo_webctl/config.py` — added `maps_dir: Path` field to
  `Settings` (default `/var/lib/godo/maps`, env
  `GODO_WEBCTL_MAPS_DIR`). `map_path` retained, deprecated.
- `src/godo_webctl/map_image.py` — cache key migration to
  `(realpath, target_mtime_ns)` (Track E PR-C cache fix).
  Renamed `_reset_cache_for_tests` → `invalidate_cache` (public)
  with the old name kept as a back-compat alias for tests.
- `src/godo_webctl/app.py` — `/api/map/image` resolves through
  `${maps_dir}/active.pgm` (falls back to `cfg.map_path` for the
  one-release deprecation window).
- `systemd/godo-webctl.env.example` — added `GODO_WEBCTL_MAPS_DIR`
  block; flagged `GODO_WEBCTL_MAP_PATH` deprecated.
- `systemd/install.md` — new "Multi-map storage" section documenting
  the `install -d -m 0750` setup, mapping container volume mount, and
  the `EROFS` override for non-default `maps_dir` paths (M5).
- `README.md` — endpoint table extended with 5 new rows, env-var
  table extended, new "Multi-map management" section, troubleshooting
  entries for `EROFS`, `map_is_active`, and the every-boot deprecation
  WARN.
- `tests/conftest.py` — 1 new fixture; existing fixtures unchanged.
- `tests/test_constants.py` — 11 new pin tests.
- `tests/test_protocol.py` — 2 new mirror tests.
- `tests/test_config.py` — `maps_dir` added to drift assertions.
- `tests/test_sse.py` — `_settings()` constructor updated to include
  `maps_dir` (drift-catch from the new dataclass field).

#### Removed

- (none)

#### Tests

- 251 hardware-free pytest cases (was 174); +1 hardware-marked smoke
  unchanged. Net +77 from this PR.

#### Mode-A folds (verbatim)

All Mode-A reviewer findings (M1–M5, N1–N6, TB1–TB3, Q-OQ-E4 + E6)
folded; see the plan's "Mode-A fold (2026-04-29)" header.

### 2026-04-26 — Phase 4-3 initial scaffold

#### Added

- `pyproject.toml`, `.python-version`, `.gitignore` — UV project skeleton.
- `src/godo_webctl/__init__.py`, `__main__.py` — package + entrypoint.
- `src/godo_webctl/protocol.py` — UDS wire constants + canonical
  encoders (`encode_ping`, `encode_get_mode`, `encode_set_mode`),
  `MAX_RENAME_ATTEMPTS = 9`.
- `src/godo_webctl/config.py` — `Settings` dataclass + `load_settings`,
  paired `_DEFAULTS` / `_PARSERS` / `_ENV_TO_FIELD` tables.
- `src/godo_webctl/uds_client.py` — sync `UdsClient` with three terminal
  read-loop cases (newline / EOF / buffer-full → `UdsProtocolError`),
  exception hierarchy `UdsError → {UdsUnreachable, UdsTimeout,
  UdsProtocolError}`, `call_uds` async helper.
- `src/godo_webctl/backup.py` — `backup_map` (two-phase rename, retry on
  `EEXIST`/`ENOTEMPTY`, `mkdir(mode=0o750)`, `_yaml_path_for` mirror).
- `src/godo_webctl/app.py` — `create_app(settings)` factory, `/api/health`,
  `/api/calibrate`, `/api/map/backup`, static mount at `/`. All status
  codes via `HTTPStatus`; thin handlers per invariant (c).
- `src/godo_webctl/static/index.html` — vanilla-JS status page with
  Page Visibility API handbrake.
- `systemd/godo-webctl.service` — User=ncenter, StateDirectory=godo,
  hardening flags. No RuntimeDirectory=godo (owned by tracker).
- `systemd/godo-webctl.env.example` — all 7 env vars commented with
  defaults.
- `tests/conftest.py` — `fake_uds_server` (in-thread AF_UNIX listener,
  scriptable replies + raw replies + delay + request capture),
  `tmp_socket_path`, `tmp_map_pair`.
- `tests/test_protocol.py` — 10 SSOT pin tests including byte-exact
  encoder asserts.
- `tests/test_config.py` — 7 tests including `_DEFAULTS == parsed Settings`
  drift catch.
- `tests/test_uds_client.py` — 10 tests including M3 buffer-full
  (`response_too_large`) and EOF-before-newline.
- `tests/test_backup.py` — 11 tests including `_yaml_path_for` mirror,
  collision retry, mode bits.
- `tests/test_app_integration.py` — 9 in-process FastAPI tests covering
  all error-mapping branches of `/api/calibrate` plus byte-exact wire
  assertion (M4).
- `tests/test_app_hardware_tracker.py` — `@pytest.mark.hardware_tracker`
  smoke; polls a sequence (OneShot then Idle within 5 s).
- `README.md` — install (dev + news-pi01), env-var table, curl
  examples, calibrate semantics callout, restoring a backup,
  troubleshooting.

#### Changed

- (none — greenfield)

#### Removed

- (none)

#### Tests

- 47 hardware-free tests across 5 modules; 1 hardware-required smoke test
  collected behind `@pytest.mark.hardware_tracker`.

### 2026-04-28 — PR-A: P4.5 frontend backend foundations

#### Added

- `src/godo_webctl/constants.py` — webctl-internal Tier-1 (JWT
  algorithm + 6 h TTL, bcrypt cost factor 12, SSE 5/1 Hz cadence
  + 15 s heartbeat, map cache 5 min TTL, activity buffer size 50,
  journal tail default 30, relocated `MAX_RENAME_ATTEMPTS = 9`).
  Leaf module — imports nothing from the package. Pinned by
  `tests/test_constants.py`.
- `src/godo_webctl/auth.py` — bcrypt + PyJWT (HS256, 6 h TTL).
  `UserStore` with `flock(LOCK_EX)` + atomic `os.replace` writes,
  lazy-seed `ncenter`/`ncenter` admin, corruption recovery to HTTP
  503 instead of crashloop. `bootstrap(jwt_secret_path, users_file)`
  is the single startup entry point used by `app.py`; it composes
  `load_or_create_secret` (32 bytes, mode 0600) + `UserStore` build
  + `lazy_seed_default`. FastAPI `Depends(require_user)` and
  `Depends(require_admin)`; bearer header OR `?token=` query param.
- `src/godo_webctl/local_only.py` — loopback-only FastAPI dependency
  (8 cases per T5).
- `src/godo_webctl/activity.py` — bounded ring buffer (size 50).
- `src/godo_webctl/sse.py` — two async generators (`last_pose_stream`
  5 Hz, `services_stream` 1 Hz) with parameterized `sleep` for tests
  (T3) + `Cache-Control: no-cache` + `X-Accel-Buffering: no` headers
  (N5).
- `src/godo_webctl/map_image.py` — Pillow PGM → PNG with mtime-keyed
  in-process cache (TTL 5 min).
- `src/godo_webctl/services.py` — `systemctl is-active|start|stop|
  restart` and `journalctl -u <svc> -n <n>` wrappers, plus
  `system_reboot`/`system_shutdown`. ALL argv built as literal LISTS
  (T2). Whitelist of allowed services as a `frozenset` constant.
- `scripts/godo-webctl-passwd` — small bash+python CLI to set/update
  an operator account; uses the same `UserStore.set_password` path so
  `flock` + atomic write are honoured.
- `systemd/godo-local-window.service` — Chromium kiosk unit
  (`User=ncenter`, `WantedBy=graphical.target`, ExecStartPre polls
  `/api/health`, `--kiosk` locks navigation per N4, profile dir under
  `/run/user/%U` tmpfs per N3).
- `systemd/install.md` — install/verify steps for the new local-window
  unit.

#### Changed

- `src/godo_webctl/protocol.py` — REMOVED `MAX_RENAME_ATTEMPTS`
  (relocated to `constants.py`); file is now strictly cross-language
  wire SSOT.
- `src/godo_webctl/backup.py` — `MAX_RENAME_ATTEMPTS` import path
  switched to `.constants`.
- `src/godo_webctl/uds_client.py` — `UdsClient.get_last_pose` method
  added (the C++ side already provides the branch).
- `src/godo_webctl/config.py` — added 4 new `Settings` fields:
  `jwt_secret_path`, `users_file`, `spa_dist`, `chromium_loopback_only`.
  Paired `_DEFAULTS` / `_PARSERS` / `_ENV_TO_FIELD` updated.
- `src/godo_webctl/app.py` — wired 14 new endpoints + 2 SSE streams +
  pluggable static mount (legacy `static/` if `cfg.spa_dist` unset, SPA
  dist when set). All admin routes use `Depends(require_admin)`; all
  `/api/local/*` add `dependencies=[Depends(loopback_only)]`. Existing
  3 routes now require admin (calibrate, map/backup) or stay public
  (`/api/health`).
- `pyproject.toml` — added `bcrypt>=4.1`, `pyjwt>=2.8`,
  `pillow>=10.0`. Added per-file ruff ignores: B008 (FastAPI
  `Depends(...)` in defaults is the framework-canonical pattern) on
  `app.py` + `auth.py`, SIM117 on `tests/test_auth.py` (nested `with
  mock.patch / pytest.raises` keeps which raise is being asserted
  obvious).
- `systemd/godo-webctl.env.example` — appended 4 new env-var entries
  (commented with defaults).
- `README.md` — added Auth, SSE channels, Local-only routes sections;
  expanded curl examples to show login + bearer token flow.

#### Removed

- (none)

#### Tests

- `tests/test_constants.py` — 11 cases pinning every value in the new
  module.
- `tests/test_auth.py` — bcrypt cost factor pin + round-trip; JWT
  issue/verify/forged/expired/malformed; secret lazy-create with
  mode 0600; users.json corruption recovery (3 cases per N2);
  atomic-write triple per T4 (A: os.replace raises, B: f.write raises,
  C: concurrent writers serialised by flock); seed semantics; lookup
  bad password / unknown user; sanity bcrypt invocation. ~21 cases.
- `tests/test_local_only.py` — 8 cases per T5 (127.0.0.1, ::1,
  192.168.x, 10.x, fc00::/7 ULA, fe80::/10 link-local, request.client
  is None, X-Forwarded-For ignored).
- `tests/test_activity.py` — append/tail/order, capacity bound,
  concurrent producers, n clamping, capacity validation. 6 cases.
- `tests/test_sse.py` — virtual-clock cadence sequence (5 Hz + 1 Hz),
  keepalive after heartbeat window, cancellation propagation, UDS
  error → frame skipped + loop alive, response headers pinned. 7
  cases.
- `tests/test_map_image.py` — PGM → PNG round trip; cache hit; mtime
  invalidation; missing file 404; invalid file. 5 cases.
- `tests/test_services.py` — whitelist enforcement; argv list literal
  on every subprocess call (per T2 — including `["shutdown", "-r",
  "+0"]` and `["shutdown", "-h", "+0"]`); is-active status parsing;
  timeout → CommandTimeout; non-zero exit → CommandFailed. 20 cases.
- `tests/test_app_integration.py` — extended to ~33 cases. Existing
  3-route tests adjusted to log in first. New: auth happy/wrong/
  unknown/forged/expired; live admin-only; last_pose contract test
  asserting `tuple(body.keys()) == LAST_POSE_FIELDS` (T6 BE drift
  catch); SSE route wired with correct headers; loopback gate
  allow/deny; system reboot/shutdown invokes literal-argv subprocess;
  activity newest-first; map/image PNG bytes; corruption-recovery 503;
  spa_dist mount swap.
- `tests/test_protocol.py` — removed `test_max_rename_attempts_is_tier1`
  (moved to `test_constants.py`).
- `tests/test_config.py` — extended to 11 cases for the 4 new Settings
  fields.

Total: 161 hardware-free tests (was 55), +1 hardware-marked
(unchanged).

#### PR-B hand-off

The SPA bundle ships from `godo-frontend/dist/` and is mounted at `/`
when the `GODO_WEBCTL_SPA_DIST` env var is set (PR-B,
`feat/p4.5-frontend-pr-b-spa`). Absence of the env var falls back to the
legacy `static/index.html`.

### 2026-04-27 — Track B mirror: `get_last_pose` + `LAST_POSE_FIELDS`

#### Added

- `src/godo_webctl/protocol.py::CMD_GET_LAST_POSE` — wire command name.
- `src/godo_webctl/protocol.py::LAST_POSE_FIELDS` — sole Python mirror
  of the field-name tuple embedded in
  `production/RPi5/src/uds/json_mini.cpp::format_ok_pose`. Order is
  ABI-visible.
- `src/godo_webctl/protocol.py::encode_get_last_pose` — canonical wire
  encoder.
- `tests/test_protocol.py::test_last_pose_fields_match_cpp_source` —
  drift pin: reads the C++ source as text, regex-extracts field names
  from the snprintf format string, asserts byte-equal against
  `LAST_POSE_FIELDS`. Editing one side without the other fails this
  test.
- `tests/test_protocol.py::test_cmd_get_last_pose_matches_cpp` and
  `::test_encode_get_last_pose_byte_exact` — companion pins.

#### Changed

- Invariant (b) in this file extended: the 13-row Python ⟷ C++ mirror
  table now includes `CMD_GET_LAST_POSE` and `LAST_POSE_FIELDS`.

#### Removed

- (none)

#### Tests

- 3 new cases in `tests/test_protocol.py`. Total webctl test count:
  47 → 50 hardware-free; +1 hardware-required smoke (unchanged).

## 2026-04-29 — PR-DIAG (Track B-DIAG) — Diagnostics endpoints + SSE

### Added

- `src/godo_webctl/protocol.py` — new wire constants:
  - `CMD_GET_JITTER = "get_jitter"`,
    `CMD_GET_AMCL_RATE = "get_amcl_rate"` (Mode-A M2 fold renamed).
  - `JITTER_FIELDS` (8-tuple), `AMCL_RATE_FIELDS` (5-tuple) — regex
    pinned against C++ struct + format string.
  - `RESOURCES_FIELDS` (8-tuple, webctl-only — no C++ counterpart).
  - `DIAG_FRAME_FIELDS = ("pose","jitter","amcl_rate","resources")`.
  - `encode_get_jitter()` + `encode_get_amcl_rate()` byte-exact encoders.
- `src/godo_webctl/uds_client.py` — `UdsClient.get_jitter` +
  `get_amcl_rate` (standard 4 KiB read cap; small replies).
- `src/godo_webctl/resources.py` (NEW) — `snapshot()` reads
  `/sys/class/thermal/thermal_zone0/temp`, `/proc/meminfo`, and
  `os.statvfs(disk_check_path)`. Per-source try/except so missing
  thermal zone yields `cpu_temp_c=None` rather than 500. 1 s TTL cache.
  `_reset_cache_for_tests()` test seam.
- `src/godo_webctl/logs.py` (NEW) — `tail(unit, n)` wraps
  `journalctl --no-pager -n N -u <svc> --output=cat` via
  `subprocess.run`. Allow-list IS `services.ALLOWED_SERVICES` (re-export,
  not duplicate). Argv is a literal Python list. n>cap clamps to
  `LOGS_TAIL_MAX_N` with WARN log. Re-exports
  `UnknownService` / `CommandTimeout` / `CommandFailed` from services.
- `src/godo_webctl/sse.py` — `diag_stream(client, cfg, sleep=...)`:
  3 parallel UDS calls via `asyncio.gather` (bound on slowest, not sum)
  + `resources.snapshot()` on a worker thread; each sub-fetch failure
  becomes `{"valid": 0, "err": "<exc>"}` for that key — others still
  emit. Heartbeat + cancel-safe lifecycle mirrors
  `last_pose_stream`/`last_scan_stream`.
- `src/godo_webctl/app.py` — 5 new endpoints (all anon-readable per
  Track F):
  - `GET /api/system/jitter` (single-shot UDS call).
  - `GET /api/system/amcl_rate` (single-shot UDS call).
  - `GET /api/system/resources` (process-local 1 s cache; no UDS).
  - `GET /api/logs/tail?unit=<svc>&n=<int>` (FastAPI
    `Annotated[int, Query(ge=1, le=LOGS_TAIL_MAX_N)]` so out-of-range
    `n` surfaces as 422 from FastAPI's own validation BEFORE the handler
    body — Mode-B S1 fold; allow-list reuses `services.ALLOWED_SERVICES`).
  - `GET /api/diag/stream` (SSE @ 5 Hz; per-subscriber UdsClient).
  - Helpers: `_jitter_view` / `_amcl_rate_view` / `_resources_view` /
    `_map_logs_exc_to_response`.
- `src/godo_webctl/constants.py` — 5 new Tier-1 constants:
  `RESOURCES_CACHE_TTL_S = 1.0`, `LOGS_TAIL_MAX_N = 500`,
  `LOGS_TAIL_DEFAULT_N = 50`, `THERMAL_ZONE_PATH`, `MEMINFO_PATH`.
- `src/godo_webctl/config.py` — `Settings.disk_check_path: Path`
  (default `Path("/")`); `GODO_WEBCTL_DISK_CHECK_PATH` env override.

### Changed

- `tests/test_app_integration.py::_settings_for` — accepts
  `disk_check_path: Path | None`; the two ad-hoc Settings constructions
  in the migration tests now pass `disk_check_path=Path("/")`.
- `tests/test_sse.py::_settings()` — extended with
  `disk_check_path=Path("/")`.

### Tests (new)

- `tests/test_resources.py` (8 cases — happy, missing thermal/meminfo,
  statvfs failure, all-sources-failing, cache hit < TTL, cache miss >
  TTL, dict-shape pin against `RESOURCES_FIELDS`).
- `tests/test_logs.py` (10 cases — happy + argv literal + unknown unit
  + n=0 + n<0 + n>cap clamps with WARN + timeout + non-zero exit +
  argv-list-not-shell + allow-list-IS-services + exception-types-are-
  services-aliases).
- `tests/test_protocol.py` — 9 new cases (CMD_GET_JITTER /
  CMD_GET_AMCL_RATE pinned, encode_* byte-exact, JITTER_FIELDS /
  AMCL_RATE_FIELDS regex-pinned against format strings + struct names,
  RESOURCES_FIELDS pinned, DIAG_FRAME_FIELDS pinned).
- `tests/test_uds_client.py` — 6 new cases (get_jitter happy / canonical
  bytes / server-rejected; get_amcl_rate happy / canonical bytes /
  server-rejected).
- `tests/test_sse.py` — 5 new cases for `diag_stream` (5 Hz cadence,
  skip-pose-error keeps other panels, skip-resources-error keeps three
  UDS panels, keepalive after heartbeat, cancellation propagates,
  all-four-fail emits all-sentinel).
- `tests/test_constants.py` — 5 new constant pins.
- `tests/test_config.py` — `disk_check_path` default + env override.
- `tests/test_app_integration.py` — 12 new cases (3 per single-shot
  endpoint × 4 + diag-stream content-type pin); extended
  `test_anon_read_endpoints_return_200` parametrization to include the
  5 new anon endpoints.

### Mode-A folds applied

- M1: `AmclRateAccumulator` uses `Seqlock<AmclRateRecord>` (in C++).
  Webctl side reads the C++ wire shape unchanged.
- M2: `scan_rate` → `amcl_rate` everywhere (endpoint URL, command name,
  field tuple name, SSE frame key).
- N3: `amcl_rate_seq` is reader-only on `diag_publisher.cpp`
  (C++-side invariant; webctl mirror is one-way).
- N4: `Resources.published_mono_ns` is the WEBCTL `time.monotonic_ns()`,
  NOT comparable to the C++ tracker's CLOCK_MONOTONIC. Documented in
  `protocol.py` and `resources.py`. SPA freshness uses `_arrival_ms`.

### Total webctl test count

333 hardware-free pytest cases pass (was 286 pre-PR-DIAG). +47 new
cases. ruff check clean; ruff format clean.


## 2026-04-29 — Track B-CONFIG (PR-CONFIG-β): config edit pipeline

### Added

- `src/godo_webctl/config_schema.py` — Python mirror of
  `production/RPi5/src/core/config_schema.hpp`. Regex-extracts each
  `ConfigSchemaRow{...}` initializer at process startup, caches as
  `tuple[ConfigSchemaRow, ...]`. `EXPECTED_ROW_COUNT = 37` (Mode-A M2
  fold pin). The C++ source's `// clang-format off` block keeps the
  one-row-per-line shape stable so the regex stays robust.
- `src/godo_webctl/config_view.py` — pure projection helpers
  (`project_config_view`, `project_schema_view`).
- `src/godo_webctl/restart_pending.py` — `is_pending(flag_path)`
  reads the C++-tracker-owned sentinel file. Tracker is authoritative;
  this module never writes (Mode-A scope fold).
- `src/godo_webctl/protocol.py` — 3 new commands (`CMD_GET_CONFIG`,
  `CMD_GET_CONFIG_SCHEMA`, `CMD_SET_CONFIG`), 3 reload-class strings,
  `CONFIG_SCHEMA_ROW_FIELDS`, `CONFIG_SCHEMA_RESPONSE_CAP = 16384`,
  3 new encoders (`encode_get_config`, `encode_get_config_schema`,
  `encode_set_config`). `encode_set_config` rejects `"`, `\`, `\n` in
  key/value (defence-in-depth before the tracker's hand-rolled JSON
  parser sees them).
- `src/godo_webctl/uds_client.py` — 3 new methods (`get_config`,
  `get_config_schema`, `set_config`). `get_config_schema` uses the
  wider `CONFIG_SCHEMA_RESPONSE_CAP` read cap (16 KiB).
- `src/godo_webctl/constants.py` — `CONFIG_GET_UDS_TIMEOUT_S = 0.5`,
  `CONFIG_SET_UDS_TIMEOUT_S = 2.0`, `CONFIG_SCHEMA_CACHE_TTL_S = 60.0`,
  `CONFIG_PATCH_BODY_MAX_BYTES = 1024`,
  `CONFIG_VALUE_TEXT_MAX_LEN = 256`, `RESTART_PENDING_FLAG_PATH`.
- `src/godo_webctl/config.py` — `Settings.restart_pending_path: Path`
  (default `/var/lib/godo/restart_pending`); env override
  `GODO_WEBCTL_RESTART_PENDING_PATH`.
- `src/godo_webctl/app.py` — 4 new endpoints:
  - `GET /api/config` (anon) — UDS `get_config` round-trip; projects
    via `config_view.project_config_view`.
  - `GET /api/config/schema` (anon) — process-cached parse of the
    Python mirror; serves the cached body for `CONFIG_SCHEMA_CACHE_TTL_S`.
  - `PATCH /api/config` (admin via `Depends(auth_mod.require_admin)`) —
    Pydantic body (single-key, value as int|float|bool|str), pre-checks
    body size + the 3 wire-fatal characters (`"`, `\`, `\n`) before
    forwarding to UDS `set_config`. Mode-A S4 fold + Mode-B N1 fold
    rationale: this is **not** a general ASCII check (which the tracker
    owns canonically); it is the strictly-defence-in-depth set of bytes
    that would corrupt the JSON-lines wire frame to the tracker —
    `json_mini.cpp` cannot tolerate raw `"` / `\` / `\n` inside a value.
    Range / type / unknown-key validation stays on the tracker side.
  - `GET /api/system/restart_pending` (anon) — calls
    `restart_pending.is_pending` on the configured flag path.

### Tests added

- `tests/test_config_schema.py` (8 cases) — synthetic + real-source
  parses; cache discipline; `_parse_source` invariants.
- `tests/test_config_schema_parity.py` (8 cases, TB1 fold) — loads
  `production/RPi5/src/core/config_schema.hpp` BY REAL PATH (mirrors
  `LAST_POSE_FIELDS` precedent in `test_protocol.py`), asserts row
  count == 37, every reload_class / type in known set, every default
  non-empty, alphabetical, sections match design, hot keys present.
- `tests/test_config_view.py` (4 cases) — projection shape tests.
- `tests/test_restart_pending.py` (5 cases) — file-existence sentinel.
- `tests/test_uds_client.py` (extended +6) — get_config / get_config
  schema / set_config round-trip + UdsServerRejected on bad_key.
- `tests/test_protocol.py` (extended +9) — command-name / encoder /
  reload-class / cap pins.
- `tests/test_app_integration.py` (extended +9) — the 4 new endpoints
  with anon-200 parametrization, admin gating, bad_key 400 forwarding,
  oversized body 413, `"`-in-key 400, restart_pending happy + missing.

### Invariants

- (n) `config_schema.py` parser is the SOLE Python parser of the C++
  schema source; the cache is process-scoped (single-worker uvicorn).
- (o) `restart_pending.py` is read-only — the C++ tracker is
  authoritative for both touch + clear.
- (p) `set_config` PATCH body is Pydantic-validated for shape +
  size + character set ONLY at webctl; range/type validation lives
  in the C++ `validate.cpp`. Mode-A S4 fold pin.
- (q) `/api/config/schema` cache TTL is `CONFIG_SCHEMA_CACHE_TTL_S`
  (60 s). The schema is constexpr in C++ — never changes within a
  tracker boot — so a positive cache window is safe; the 60 s ceiling
  bounds startup-staleness when the operator replaces the tracker
  binary.

### Cross-language SSOT (extended)

| Layer | File | Drift catch |
|---|---|---|
| C++ canonical | `production/RPi5/src/core/config_schema.hpp` | `static_assert(N == 37)` + `// clang-format off` |
| Python mirror | `godo-webctl/src/godo_webctl/config_schema.py` | regex parse + `EXPECTED_ROW_COUNT == 37` |
| TS mirror | `godo-frontend/src/lib/protocol.ts` (interfaces only) | hand-mirrored; runtime fetch from `/api/config/schema` for the row data |
| Tests | `tests/test_config_schema_parity.py` | loads C++ source by real path; asserts row count + every reload_class string + every type string + alphabetical + 7 sections + 3 hot keys present |


## 2026-04-29 — Track B-BACKUP: map-backup history page (P2 Step 2)

NOTE: top-level invariants now reach (t); the post-(s) duplicates inside Track B-CONFIG's change-log subsection are known and out of scope for this PR.

### Added

- `src/godo_webctl/map_backup.py` — pure-function backup-history primitives
  (`list_backups`, `restore_backup`) + custom exceptions
  (`BackupNotFound`, `RestoreNameConflict`). SOLE owner of every FS
  touch inside `cfg.backup_dir` (new invariant (t)). The restore
  writer ALSO writes into `cfg.maps_dir` but does NOT import `maps.py`
  — restore deliberately does not touch the active symlinks (Option A
  semantics; operator activates separately via the existing Track E
  flow + `godo-tracker` restart).
- `src/godo_webctl/protocol.py` — 2 new error-code mirrors
  (`ERR_BACKUP_NOT_FOUND`, `ERR_RESTORE_NAME_CONFLICT`). Mode-A M5 fold
  intentionally drops `ERR_BACKUP_DIR_MISSING`: `list_backups` returns
  `[]` for both "dir missing" and "dir exists but empty", so the wire
  shape is uniformly 200.
- `src/godo_webctl/app.py` — 2 new endpoints + `_map_backup_exc_to_response`
  helper:
  - `GET    /api/map/backup/list` (anon, Track F).
  - `POST   /api/map/backup/<ts>/restore` (admin via
    `Depends(auth_mod.require_admin)`).

  Mode-A N6 fold: the restore route uses
  `Annotated[str, Path(pattern=r"^[0-9]{8}T[0-9]{6}Z$")]` so a
  malformed `<ts>` returns 422 BEFORE the handler runs; the internal
  `restore_backup` regex stays as the second defence layer.
  Mode-A N7 fold: activity-log entry detail format is
  `f"{ts} ({n} files)"`.
- `tests/conftest.py` — new `tmp_backup_dir` fixture (2 canonical
  backup dirs at distinct UTC stamps + 1 `<ts>.tmp/` orphan).
- `tests/test_map_backup.py` — 12 new pure-function tests covering
  list/restore happy paths, traversal corpus collapse to
  `BackupNotFound`, partial-failure contract (M6 fold:
  `test_restore_never_leaves_partial_pgm`), tmp-cleanup on copy
  failure, size sum, newest-first ordering, `<ts>.tmp/` orphan skip,
  empty/missing dir uniform return.
- `tests/test_app_integration.py` — 8 new cases for the 2 endpoints:
  anon list 200, newest-first wire shape, missing-dir 200-empty
  (replaces the dropped 503 path), admin restore 200, anon restore
  401, unknown-ts 404, dot-traversal corpus collapses to 4xx, activity
  log detail pin (`f"{ts} ({n} files)"`).
- `tests/test_protocol.py` — 2 new pin tests
  (`test_track_b_backup_error_codes_pinned`,
  `test_track_b_backup_no_dir_missing_constant` — pins the absence of
  the dropped symbol).

### Changed

- Invariant (n) — anonymous-readable list extended with
  `/api/map/backup/list`; admin-mutation list extended with
  `/api/map/backup/<ts>/restore`.
- Module map and dependency graph extended to show `map_backup.py`.

### Removed

- (none — `ERR_BACKUP_DIR_MISSING` was never present; Mode-A M5 fold
  removed it from the planned diff.)

### Tests

- 387 → 408 hardware-free pytest cases (+21 from this PR; +12 in
  `test_map_backup.py`, +8 in `test_app_integration.py`, +2 in
  `test_protocol.py` → minus −1 because the dropped 503 case in the
  plan was replaced rather than added).
- `uv run ruff check` clean; `uv run ruff format --check` clean.

### Mode-A folds applied

- **M1**: invariant added as `(t)` (lowest unused top-level letter; the
  post-(s) duplicates inside Track B-CONFIG's change-log subsection
  are pre-existing letter pollution out of scope for this PR).
- **M3**: `FRONT_DESIGN.md:505` 권한 column for
  `GET /api/map/backup/list` brought into alignment with Track F
  invariant (n) (`viewer` → `anon`).
- **M4**: `restore_backup` does NOT import `_yaml_path_for` from
  `backup.py`; copies every basename in `<backup_dir>/<ts>/` verbatim.
- **M5**: `BackupDirMissing` exception removed; `list_backups` returns
  `[]` for both dir-missing and dir-empty; the 503 path is gone.
- **M6**: `test_restore_never_leaves_partial_pgm` pins the contract,
  not the mechanism (3-file backup with a monkeypatched 2nd
  `os.replace`).
- **M7**: `restore_backup` docstring documents partial-restore
  semantics (committed-before-failure files remain replaced;
  at-or-after-failure files retain their pre-restore state).
- **N6**: FastAPI `Path(pattern=...)` regex constraint applied on the
  restore route.
- **N7**: activity-log entry detail format = `f"{ts} ({n} files)"`,
  pinned by `test_backup_restore_appends_activity_log`.
- **TB4**: malformed and unknown-ts arguments both raise
  `BackupNotFound` (deliberate folding for log-uniformity; the
  handler returns 404 for both).

## 2026-04-29 — Track B-SYSTEM PR-2: service observability

### Added

- `src/godo_webctl/system_services.py` (NEW) — TTL cache layer for
  `/api/system/services`. `snapshot()` invokes `services.service_show()`
  over `services.ALLOWED_SERVICES`, caches for
  `SYSTEM_SERVICES_CACHE_TTL_S = 1.0 s`. Per-service degradation (M5
  fold): `services.ServicesError` / `OSError` / `FileNotFoundError`
  yield `active_state="unknown"` for that entry; aggregate endpoint
  always returns 200. `_reset_cache_for_tests()` test seam mirroring
  `resources._reset_cache_for_tests`.
- `src/godo_webctl/services.py::ServiceShow` dataclass + `service_show`
  + `parse_systemctl_show` + `redact_env` + `_parse_environment_value`.
  `BLOCKING_TRANSITION_STATES = frozenset({"activating",
  "deactivating"})` (S7 fold: `reloading` deliberately excluded — none
  of the 3 ALLOWED_SERVICES define `ExecReload=`). `ALLOWED_PROPERTIES`
  tuple lists the 7 systemd properties queried via `--property=`.
  `ServiceTransitionInProgress(transition, svc)` exception carries the
  transition kind for handler-side Korean detail lookup.
- `src/godo_webctl/services.py::control()` extended with a pre-flight
  `is_active()` gate (invariant (w)).
- `src/godo_webctl/protocol.py` — `SYSTEM_SERVICES_FIELDS` (7-field
  tuple), `ENV_REDACTION_PATTERNS` (6-pattern tuple),
  `REDACTED_PLACEHOLDER = "<redacted>"`, `ERR_SERVICE_STARTING`,
  `ERR_SERVICE_STOPPING`.
- `src/godo_webctl/constants.py` — `SYSTEM_SERVICES_CACHE_TTL_S = 1.0`,
  `SERVICE_TRANSITION_MESSAGES_KO` (6 keyed Korean strings; Mode-A M3
  fold uses Korean reading convention).
- `src/godo_webctl/app.py` — `GET /api/system/services` (anon,
  invariant (v)), `POST /api/system/service/{name}/{action}` (admin-
  non-loopback, invariant (x)), `_service_transition_response()`
  helper for the 409 wire shape, 409 arm added to
  `local_service_action`.
- `tests/test_system_services.py` (NEW, 8 cases) —
  pinned-fields, alphabetical service order, secret redaction, memory
  not-set handling, per-service failure → unknown state (M5 pin),
  cache hit/miss with exact `call_count` assertions (T1 fold), degraded
  entry shape pin.
- `tests/test_services.py` — 19 new cases (parser corpus including
  S1 fold's backslash + escaped-newline; redaction parametrize over 6
  patterns + benign control case (T2 fold); service_show shape +
  argv-list pin; transition-gate + anti-monotone pair;
  `test_control_pre_flight_does_not_use_system_services_cache` (S2
  fold)). Existing `test_control_invokes_literal_argv` updated for the
  3-call shape.
- `tests/test_constants.py` — `test_system_services_cache_ttl_pinned`,
  `test_service_transition_messages_ko_pinned` (all 6 tuples literal,
  N5 fold), `test_service_transition_messages_ko_covers_allowed_services`
  (drift catch).
- `tests/test_protocol.py` — `test_system_services_fields_pinned`,
  `test_env_redaction_patterns_pinned`, `test_redacted_placeholder_pinned`,
  `test_service_transition_error_codes_pinned`.
- `tests/test_app_integration.py` — 13 new integration cases
  (`/api/system/services` anon read; per-service degradation 200 with
  unknown state; 409 corpus with EXACT Korean substring pinning per
  service per particle, including the 3 ALLOWED_SERVICES; 8-case
  `/api/system/service/*` admin endpoint matrix per §8.4 — happy,
  401, 403, 400, 404, 409, 504, 500). `test_anon_read_endpoints_return_200`
  parametrize extended with `/api/system/services`.

### Changed

- Invariant (n) anon-readable list extended with `/api/system/services`;
  admin-mutation list extended with `/api/system/service/<name>/<action>`.
- Invariant numbering: PR-1 takes `(u)` (pidfile config key); this PR
  adds `(v)`, `(w)`, `(x)`.

### Tests

- 431 → 490 hardware-free pytest (+59 from this PR; +24 integration in
  `test_app_integration.py`, +19 unit in `test_services.py`, +8 in
  `test_system_services.py`, +4 in `test_protocol.py`, +3 in
  `test_constants.py`, plus pre-existing test updates).
  `uv run ruff check` + `uv run ruff format --check` clean.

### Mode-A folds applied (full plan §7 + §8 fold-in)

- M1: invariants `(v) + (w) + (x)` (NOT `(u) + (v)`).
- M2: §7.1 7-column row format honored in `FRONT_DESIGN.md`.
- M3: Korean particle convention pinned (Korean reading, 받침 rule).
- M4: 7-field dataclass + 7 systemd properties.
- M5: 503 wire path dropped; per-service `active_state="unknown"`.
- M6: R11 mitigation cites systemd idempotency.
- S1 (env corpus): backslash + escaped-newline cases pinned.
- S2 (`control()` doesn't use cache): explicit pin via
  `test_control_pre_flight_does_not_use_system_services_cache`.
- S2 (§8 fold): full exception → status mapping in the new admin
  endpoint (504 for CommandTimeout + 500 for CommandFailed).
- S1 (§8 fold): handler emits `activity_log` entry (audit trail).
- S3: out-of-scope `journal_tail` / `JournalTail.svelte` honored.
- S4: `formatBytesShort` renamed to `formatBytesBinaryShort` on the SPA.
- S5: rationale for new endpoint vs reuse `/api/local/services/stream`
  documented in `CODEBASE.md` invariants.
- S7: `BLOCKING_TRANSITION_STATES` excludes `reloading` with comment.
- TB1 (§8 fold): integration tests monkeypatch
  `godo_webctl.services.control`, NOT `subprocess.run`.
- T1: cache hit/miss tests assert exact `call_count` (3 vs 6).
- T2: redaction parametrize includes benign control case.
- T3: 409 integration tests pin EXACT Korean substring per particle.
- N5: 6 (svc, transition) tuples literal-pinned in `test_constants.py`.

## 2026-04-30 00:30 KST — PR-A: full systemd switchover + polkit + LAN bind + SPA dist

### Why

Track B-SYSTEM PR-2 (above) shipped `POST /api/system/service/{name}/{action}`
and its sibling under `/api/local/`, both routed through
`services.control(svc, action)`. The unit files for the three GODO
services existed but the polkit rule that lets `ncenter` invoke
`systemctl start/stop/restart` without sudo did not. Result: every
admin click returned HTTP 500 `subprocess_failed`. PR-A ships the
missing polkit rule. No webctl code changes — this is purely a
host-config delta — but the existing tests pin the wire contract that
the rule unblocks at runtime.

### Added

- (No new endpoint code; the polkit rule itself lives at
  `production/RPi5/systemd/49-godo-systemctl.rules` because the
  tracker's systemd unit files are also there. The webctl
  `README.md`'s "Install on news-pi01" section now documents
  the full 6-step PR-A switchover.)
- `services.py::time` import — the `service_show()` `active_since_unix`
  derivation now reads `time.monotonic()` + `time.time()` to convert
  systemd's `ActiveEnterTimestampMonotonic` (microseconds since boot)
  into a unix epoch.
- `services.py::os` import — `os.path.getmtime()` powers the new
  `env_stale` flag (envfile mtime > active_since_unix → restart pending).
- `config_schema.py::_resolve_schema_path()` — tiered path
  resolution: `GODO_WEBCTL_CONFIG_SCHEMA_PATH` env override (set in
  `/etc/godo/webctl.env` on production hosts) > dev-tree sibling
  layout (`<repo>/godo-webctl` next to `<repo>/production/RPi5`) >
  `/opt/godo-tracker/share/config_schema.hpp` (production install
  fallback). Earlier code assumed only the dev-tree layout, so
  `/api/config/schema` returned HTTP 503 `schema_unavailable` after
  the PR-A switchover (where `/opt/godo-webctl` is no longer a
  sibling of any `production/RPi5` directory).
- `services.py::_parse_environment_files_paths()` — parses the
  `EnvironmentFiles=...` value of `systemctl show` (whitespace-separated
  `path (option=...)` entries) into a list of absolute paths.
- `services.py::_read_envfile()` — parses a systemd-style envfile
  (shell-like KEY=VALUE per line, `#` comments, matched-quote stripping).
  Used in place of `/proc/<pid>/environ` reads — cap-bearing processes
  are non-dumpable so cross-process /proc/*/environ reads return EPERM
  even for the same user.
- `services.py::_envfile_newer_than_process()` — staleness predicate.
  Returns True when any `EnvironmentFile=` mtime is later than the
  process's `active_since_unix`, surfacing operator envfile edits that
  have not yet taken effect.
- `protocol.py::SYSTEM_SERVICES_FIELDS` — 8 fields now (was 7), adding
  `env_stale`. Pin test in `tests/test_protocol.py` updated.
- `system_services.py::_serialize` + `_degraded_entry` — wire-shape
  emit `env_stale` per service.

### Changed

- `services.py::ALLOWED_PROPERTIES` — `ActiveEnterTimestampRealtime`
  → `ActiveEnterTimestampMonotonic`, AND added `EnvironmentFiles`.
  systemd 257 (Trixie) does NOT expose `ActiveEnterTimestampRealtime`
  as a queryable property; the Realtime variant exists in some legacy
  systemd versions but `systemctl show
  --property=ActiveEnterTimestampRealtime` returned nothing on Trixie
  (silent — the property line was simply absent from output, leaving
  `active_since_unix` always null and the SPA showing "—" for uptime).
  Migrating to the canonical Monotonic property fixes the data hole.
  `EnvironmentFiles` is queried so the env source-of-truth (envfile
  paths the unit declares) is part of the show payload — see the
  `_read_envfile` change below. The conversion to unix epoch is done
  in-process via `time.monotonic()` + `time.time()` reads — Linux
  kernel's CLOCK_MONOTONIC is shared between systemd and Python's
  `time.monotonic()`, so the elapsed-time delta is exact.
- `services.py::service_show()`:
  - Derive `active_since_unix` from monotonic instead of the
    (non-existent) realtime field. Returns `None` when monotonic
    value is `0` or `[not set]` (unit was never active).
  - Build `env_redacted` from the union of the unit's `Environment=`
    directive AND every `EnvironmentFile=` content. Earlier draft
    used `/proc/<MainPID>/environ` reads; cap-bearing processes
    (tracker has CAP_SYS_NICE + CAP_IPC_LOCK) are kernel-marked
    non-dumpable, blocking same-user /proc reads with EPERM. envfile
    text content is the operator's authored source-of-truth — staged
    edits show even on a tracker that has not yet picked them up.
  - Compute `env_stale` via `_envfile_newer_than_process` — True when
    any envfile mtime is later than the process's `active_since_unix`.
- `tests/test_services.py` — 4 tests updated for the new property
  name + monotonic-based derivation; +9 new tests for envfile-path
  parsing, envfile read, the staleness predicate, the oneshot path
  (no envfile, env_stale stays False), and the env_stale=True
  integration case.
- `tests/test_protocol.py::test_system_services_fields_pinned` — pin
  expanded to the 8-field tuple including `env_stale`.
- `tests/test_system_services.py::_show` helper — accepts an
  `env_stale` kwarg defaulting to False so existing tests need no
  per-test edit. The dataclass-time `_ensure_field_order_pin()`
  catches drift between SYSTEM_SERVICES_FIELDS and ServiceShow.
- `tests/test_app_integration.py::_stub_service_show` — passes
  `env_stale=False` to the `ServiceShow` constructor.
- `godo-webctl/systemd/godo-webctl.service`:
  - Removed `Wants=godo-tracker.service` from `[Unit]`. Per the
    operator service-management policy
    (`.claude/memory/project_godo_service_management_model.md`),
    tracker is manual-start via the SPA Start button; webctl
    must NOT pull tracker along at boot. webctl tolerates a
    tracker-down state cleanly (ctl.sock connect failures
    surface as "tracker offline" badges in the SPA).
  - Removed `After=godo-tracker.service`; only `After=network.target`
    remains.
  - Added `RuntimeDirectory=godo` + `RuntimeDirectoryMode=0750` +
    `RuntimeDirectoryPreserve=yes`. With tracker as manual-start,
    webctl is the auto-start service that owns `/run/godo` across
    reboots. systemd reference-counts so the dir survives if either
    service stops (tracker.service also declares the same dir +
    Preserve=yes).
  - Added `MemoryAccounting=yes` so `systemctl show
    --property=MemoryCurrent` returns a real value (was `[not set]`
    before; SPA showed "—" for memory). Effective once the kernel
    cmdline allows the cgroup memory controller — see
    `production/RPi5/CODEBASE.md` for the `cgroup_enable=memory`
    cmdline edit.
- `godo-webctl/README.md`:
  - "Install on news-pi01" rewritten to the 6-step PR-A switchover:
    pre-req tracker install → /var/lib/godo/maps pre-create →
    rsync to /opt/godo-webctl (excluding .venv) → uv sync --no-dev
    → seed /etc/godo/webctl.env (must edit HOST + SPA_DIST) →
    install + enable unit → deploy frontend dist to
    /opt/godo-frontend.
  - New `### /run/godo ownership and webctl-tracker independence`
    subsection documenting the co-ownership + Preserve=yes contract.
- `godo-webctl/systemd/godo-webctl.env.example`: pre-existing file,
  no diff in PR-A. The PR's runtime config (HOST=0.0.0.0,
  SPA_DIST=/opt/godo-frontend/dist) is set by the operator in
  `/etc/godo/webctl.env` per the README install steps; the
  template's commented defaults already document the keys.

### Tests

- No change. `test_app_integration.py::test_post_system_service_*` (8
  cases) and `test_local_service_*` (3 cases) continue to monkeypatch
  `godo_webctl.app.services_mod.control`, so they were always green
  in CI; they are the regression net for the wire shape. The polkit
  gate + the new RuntimeDirectory contract are HIL-asserted on
  news-pi01:
  - `journalctl -u polkit` shows `Finished loading, compiling and
    executing 13 rules` after install (12 default + ours).
  - `systemctl start godo-tracker.service` AS `ncenter` (no sudo)
    returns exit 0; `Interactive authentication required.` would
    indicate a broken rule.
  - The webctl admin endpoint exercise (curl AS admin token):
    `POST /api/system/service/godo-tracker/{stop,start,restart}` →
    HTTP 200 `{"ok":true,"status":"<active|inactive>"}`. Pre-PR-A
    same call returned HTTP 500 `subprocess_failed`.
  - Negative cases also verified end-to-end: `godo-frobnicate/start`
    → 404 `unknown_service`; `godo-tracker/purge` → 400
    `unknown_action`. These exercise the FastAPI handler's exception
    mapping under the polkit gate's happy-path conditions.

### Invariants

- Invariant **(x) admin-non-loopback service-control endpoint** is
  unchanged at the route layer — the only thing PR-A changes is the
  runtime precondition that makes its happy path actually reachable.
  Hosts WITHOUT the polkit rule still observe the documented HTTP 500
  `subprocess_failed` response; hosts WITH the rule observe HTTP 200
  `{"ok":true,"status":"active"|"inactive"|"failed"}`. The wire
  contract is identical in both states.
- Cross-link: `production/RPi5/CODEBASE.md` invariant **(o)
  godo-systemctl-polkit-discipline** is the lock-step partner —
  the unit-name × verb whitelist in the polkit rule MUST equal
  `services.py::ALLOWED_SERVICES × ALLOWED_ACTIONS`. Adding a fourth
  GODO unit or fourth verb is a synchronized two-file edit
  (`services.py` + the polkit rule) per that invariant.

## 2026-05-01 00:30 KST — issue#3: CalibrateBody (pose hint forward) + schema row count 40 → 42

### Added

- `CalibrateBody` Pydantic v2 model in `app.py` — five optional
  fields (`seed_x_m`, `seed_y_m`, `seed_yaw_deg`, `sigma_xy_m`,
  `sigma_yaw_deg`). Per-field bounds via `Field(ge=, le=, lt=)`;
  cross-field shape via `model_validator(mode='after')`:
    1. seed triple is all-or-none (Mode-A M4),
    2. σ overrides require seed_* to be present.
- `protocol.py::encode_set_mode(...)` — keyword-only kwargs
  `seed`, `sigma_xy_m`, `sigma_yaw_deg`. When `seed=None` (default),
  emits the pre-issue#3 wire byte-for-byte (back-compat).
  Defence-in-depth: rejects non-finite floats + σ-without-seed at
  the encoder seam. JSON NUMBER serialization via `repr(float)`
  (shortest round-trip — accepted by the C++ `parse_number` subset).
- `uds_client.py::UdsClient.set_mode(..., *, seed=None, ...)` +
  `call_uds(fn, *args, **kwargs)` extension to forward kwargs.
  Pre-issue#3 callers (positional only) are unaffected.
- `app.py /api/calibrate` accepts an optional `CalibrateBody | None`.
  Empty body / all-None body → no `seed` kwarg → encoder emits
  pre-issue#3 wire (back-compat anti-regression).
- `config_schema.py::EXPECTED_ROW_COUNT` 40 → 42 to track the C++
  schema (issue#3 added `amcl.hint_sigma_xy_m_default` +
  `amcl.hint_sigma_yaw_deg_default`).

### Tests

- `test_app_integration.py` — 7 new cases:
    test_calibrate_with_full_hint_appends_seed_keys_to_wire,
    test_calibrate_partial_hint_returns_422,
    test_calibrate_sigma_only_returns_422,
    test_calibrate_yaw_360_returns_422,
    test_calibrate_yaw_negative_returns_422,
    test_calibrate_seed_only_no_sigma_uses_cfg_default,
    test_calibrate_empty_body_byte_identical_to_pre_issue3.
- `test_protocol.py` — 5 new cases pinning the encoder shape:
    test_encode_set_mode_no_hint_byte_identical_to_pre_issue3
    (anti-regression vs the pre-issue#3 byte sequence),
    test_encode_set_mode_with_full_hint, test_encode_set_mode_seed_only_no_sigma,
    test_encode_set_mode_rejects_sigma_without_seed,
    test_encode_set_mode_rejects_non_finite_hint.
- Schema parity tests bumped to 42:
    test_config_schema_parity, test_config_schema, test_config_view,
    test_get_config_schema_returns_42_rows.
- All 683 webctl tests pass (was 671 baseline + 12 new).
- Ruff clean. Mypy clean on edited files.

### Removed

- (none)

### Invariants

- **(ac) calibrate-hint-forward-compat-discipline** — issue#3
  CalibrateBody pipeline. Three layers must agree on the wire shape;
  drift between any pair is a code-review block.

  1. **Pydantic = first defence**: `CalibrateBody.all_or_none_seed`
     enforces the seed-triple shape AND σ-without-seed rejection
     BEFORE the handler runs. Operator-facing 422 with field
     paths so the SPA can highlight the broken input.

  2. **Encoder = second defence**: `protocol.py::encode_set_mode`
     re-rejects σ-without-seed + non-finite floats. JSON NUMBER
     emission via `repr(float)` is the shortest round-trip Python
     produces; the C++ `parse_number` subset accepts it byte-exactly
     (no leading +, no bare '.', no NaN/Infinity).

  3. **Tracker = third defence**: `production/RPi5/src/uds/uds_server.cpp`
     re-validates the hint at the wire seam (production CODEBASE
     invariant (p)). A non-webctl client (raw `socat`) cannot
     bypass any of the three layers because each one independently
     rejects malformed payloads.

  4. **Back-compat**: an empty body / `body=None` request emits
     `{"cmd":"set_mode","mode":"OneShot"}\n` — byte-identical to
     pre-issue#3. Pinned in two test files (one per layer):
     `test_protocol::encode_set_mode_no_hint_byte_identical_to_pre_issue3`
     + `test_app_integration::test_calibrate_empty_body_byte_identical_to_pre_issue3`.
     A future writer who introduces an unconditional `seed_x_m`
     emit fails BOTH cases.

---

## 2026-05-02 08:57 KST — issue#14 Maj-1: mapping-stop timing ladder operator-tunable + ordering invariant

Mode-B Maj-1 finding: the stop-timing chain was too tight against
nav2 `map_saver_cli`'s atomic-rename window. Operator stake "맵 한번
제작하면 평생 쓰는" demanded both (a) wider defaults and (b)
SPA-tunable knobs so future HIL findings can adjust without code
changes. Tracker schema rows are the SSOT (production/RPi5
CODEBASE.md (r) extended); webctl is the runtime consumer.

### Added

- `webctl_toml.py` — `WebctlSection` extended with 3 new fields
  (`mapping_docker_stop_grace_s`, `mapping_systemd_stop_timeout_s`,
  `mapping_webctl_stop_timeout_s`), 6 new module-level constants
  (defaults + min/max), 3 new env-var keys, ordering-invariant
  validation in `read_webctl_section` (raises `WebctlTomlError`
  with the offending key when the trio is misordered).
- `config.py::Settings.mapping_webctl_stop_timeout_s` — new field
  + matching `_DEFAULTS` / `_PARSERS` / `_ENV_TO_FIELD` row.
  Fallback default sourced from `constants.MAPPING_CONTAINER_STOP_TIMEOUT_S`
  (35.0 s). Runtime value typically comes from the `[webctl]`
  section of `tracker.toml`.
- `mapping.py` — `stop()` polling loop now reads
  `cfg.mapping_webctl_stop_timeout_s`; the legacy constant is the
  fallback when the [webctl] section is silent.
- `constants.MAPPING_STATE_REREAD_INTERVAL_S = 0.25` — Tier-1 cadence
  for issue#14 Maj-2's start-Phase-2 state-reread loop (used by
  the upcoming flock-narrowing refactor).
- `tests/test_webctl_toml.py` — 14 new cases covering the 3 new
  keys: defaults when section missing, TOML reads, env override,
  out-of-range bounds (per-key parametrized), ordering invariant
  in three permutations, partial-override-against-defaults.
- `tests/test_constants.py::test_mapping_unit_file_timing_values_match_constant`
  — pins the AS-CHECKED-IN unit file's `--time=20` + `TimeoutStopSec=30s`
  literals against the constants. Catches drift between the unit
  file (which `install -m 0644` ships verbatim before the first
  webctl boot) and the operator-locked 20/30/35 ladder.
- `tests/test_mapping.py::test_stop_polling_deadline_uses_cfg_field_not_constant`
  — pins the contract that `mapping.stop()` reads
  `cfg.mapping_webctl_stop_timeout_s`, not the legacy constant.

### Changed

- `constants.MAPPING_CONTAINER_STOP_TIMEOUT_S` value 25.0 → 35.0
  (now the FALLBACK default, mirrored by webctl.mapping_webctl_stop_timeout_s
  default in webctl_toml.py + the schema row default_repr).
- `constants.py` — comment block on `MAPPING_CONTAINER_STOP_TIMEOUT_S`
  rewritten to explain the new role (fallback default; runtime value
  in Settings).
- `mapping.py` — `stop()` polling loop now uses `cfg.mapping_webctl_stop_timeout_s`
  for the deadline + the `ContainerStopTimeout` exception message.
- `tests/test_constants.py::test_mapping_container_stop_timeout_ordering_invariant`
  — pin updated to the new 20/30/35 ladder.
- `tests/test_constants.py::test_mapping_container_stop_timeout_s_pinned`
  removed (the value is now operator-tunable; the ordering invariant
  is the new pin).
- `tests/test_config.py::test_empty_env_uses_defaults` — asserts the
  new `Settings.mapping_webctl_stop_timeout_s == 35.0` default.
- `tests/test_config.py::test_each_env_var_overrides_default` — adds
  `GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S=60.0` override.
- `tests/test_config_schema_parity.py` — row count pin 48 → 51,
  + `test_webctl_mapping_timing_rows_present` for the 3 new schema rows.
- `tests/test_config_schema.py` — row count pin 48 → 51 in both the
  parser and the load-schema cases.
- `tests/test_config_view.py::test_project_schema_view_real_source`
  — assertion 48 → 51 + presence checks for the 3 new rows.
- `tests/test_app_integration.py::test_get_config_schema_returns_51_rows`
  — renamed and bumped from 48.
- All Settings constructions in tests (`test_mapping.py`,
  `test_mapping_sse.py`, `test_sse.py`, `test_app_integration.py`)
  add `mapping_webctl_stop_timeout_s=35.0`.
- `config_schema.py::EXPECTED_ROW_COUNT` 48 → 51.

### Removed

- (none)

### Invariants

- **(ad) mapping-timing-ladder** — the stop-timing trio
  (`webctl.mapping_docker_stop_grace_s`,
  `webctl.mapping_systemd_stop_timeout_s`,
  `webctl.mapping_webctl_stop_timeout_s`) must satisfy the
  strict ordering
  `docker_grace_s < systemd_timeout_s < webctl_timeout_s`
  at every layer:

  1. **Tracker schema bounds** — per-row min/max in
     `config_schema.hpp` allow ranges that overlap (docker [10, 60],
     systemd [20, 90], webctl [25, 120]). The schema does NOT
     cross-check the trio — that's webctl's job.
  2. **Webctl single drift-catch** — `webctl_toml.read_webctl_section`
     enforces the strict-greater-than check at startup; a misordered
     `tracker.toml` raises `WebctlTomlError` naming the second key
     in the broken pair (`webctl.mapping_systemd_stop_timeout_s` for
     docker≥systemd, `webctl.mapping_webctl_stop_timeout_s` for
     systemd≥webctl). The error message includes both numeric values
     so the operator sees what to bump.
  3. **install.sh** — sed-substitutes `docker_stop_grace` +
     `systemd_stop_timeout` from the `[webctl]` section into the
     `godo-mapping@.service` template at install time. The
     as-checked-in unit file MUST also satisfy the invariant so a
     bare `install -m 0644` (before the first webctl boot writes
     tracker.toml) still produces a valid ladder. Pinned by
     `tests/test_constants.py::test_mapping_unit_file_timing_values_match_constant`.
  4. **mapping.py** — `stop()` reads
     `cfg.mapping_webctl_stop_timeout_s`, not the legacy
     `MAPPING_CONTAINER_STOP_TIMEOUT_S` constant. The constant is
     the fallback default that lands in Settings via
     `_DEFAULTS["GODO_WEBCTL_MAPPING_WEBCTL_STOP_TIMEOUT_S"]` when
     the env / TOML are silent — its value (35) is pinned in
     `test_constants.py::test_mapping_container_stop_timeout_ordering_invariant`.
  5. **Cross-stack ownership**: tracker schema rows are the SSOT
     (production/RPi5/CODEBASE.md (r) extended for the 3 new rows).
     Webctl reads via `webctl_toml`, install.sh awks the section,
     mapping.py consumes the cfg field. The operator-locked stake
     "맵 한번 제작하면 평생 쓰는" mandates this ladder be operator-
     tunable; the SPA Config tab is schema-driven so the rows
     surface automatically (no frontend change).

## 2026-05-02 20:15 KST — issue#16 HIL hot-fix v4: cp210x interface notation

v3 visibility logs surfaced the real bug:

```
mapping.recover_cp210x: firing for lidar_port=/dev/ttyUSB0 usb_path=3-2
godo-cp210x-recover.sh: line 19: echo: write error: No such device
```

The cp210x driver is a USB *interface* driver — its
`/sys/bus/usb/drivers/cp210x/{bind,unbind}` sysfs files require USB
INTERFACE notation (`<bus>-<port-chain>:<config>.<intf>`, e.g.
`3-2:1.0`), NOT bare device notation (`<bus>-<port-chain>` like
`3-2`). v1/v2/v3 wrote bare device notation and the kernel rejected
every write with ENODEV → recovery never actually fixed any wedged
state.

### Changed

- `_USB_PATH_REGEX` tightened from
  `^[0-9]+-[0-9.]+$` → `^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$`. Bare
  device notation is now rejected; only full interface notation
  passes.
- `_resolve_usb_sysfs_path` no longer strips the `:<config>.<intf>`
  suffix — returns the whole interface segment (`1-1.4:1.0`,
  `3-2:1.0`, `2-1:2.3`).
- `production/RPi5/share/godo-cp210x-recover.sh` regex tightened
  to match. Helper now also runs `udevadm settle --timeout=3` after
  bind so /dev/ttyUSB* is recreated before mapping.start() proceeds
  to systemctl-start of the mapping container.

### Tests

- `test_resolve_usb_sysfs_path_returns_full_interface_notation` —
  confirms `:1.0` suffix preserved.
- `test_resolve_usb_sysfs_path_news_pi01_layout` — pins the
  operator HIL case (`3-2:1.0` from `/sys/.../usb3/3-2/3-2:1.0/...`).
- `test_resolve_usb_sysfs_path_handles_complex_port_chain` —
  multi-hop hub chain returns the leaf interface.
- `test_resolve_usb_sysfs_path_handles_multi_interface_index` —
  arbitrary `:<cfg>.<intf>` integers (e.g. `2-1:2.3`).
- `test_resolve_usb_sysfs_path_no_interface_segment_raises` (NEW)
  — bare device segment without interface = raise.
- Malformed-payload parametrize set extended to include bare device
  segments (`1-1.4` alone, `1-1.4:1` incomplete).
- `_write_cp210x_envfile` test data updated to interface notation.

## 2026-05-02 19:50 KST — issue#16 HIL hot-fix v3: robust USB sysfs resolver + visibility logs

Operator HIL on hot-fix v2 surfaced that auto-recovery was silently
no-op'ing on news-pi01 RPi 5. Diagnostic chain:

1. `journalctl -u godo-cp210x-recover` → `-- No entries --` (oneshot
   never fired).
2. Manual `readlink /sys/class/tty/ttyUSB0/device | sed 's/:.*//'`
   returned `ttyUSB0` not `1-1.4` — the kernel's symlink target on
   this hardware does NOT carry a `:1.0` interface suffix.
3. Old resolver raised `LidarPortNotResolvable` on the no-suffix
   case; mapping.start() caught and silently logged WARNING; but
   the WARNING was below the operator's grep window depth.

### Changed

- `_resolve_usb_sysfs_path` rewritten to walk `realpath()` segments
  from tail to root and return the first segment matching the USB
  port regex. Handles both observed sysfs layouts:
  - (a) tail-segment is the interface (`.../1-1.4:1.0`)
  - (b) tail-segment is the tty device (`.../1-1.4/ttyUSB0`)
  Also rejects realpath outside `/sys/` (defence-in-depth).
- `recover_cp210x` adds two `logger.info` lines:
  - "firing for lidar_port=… usb_path=…" before the systemctl call
  - "completed for usb_path=…" on success
  Operator now sees POSITIVE evidence in `journalctl -u godo-webctl`
  whether the recovery actually ran (the existing WARNING-only log
  made silent-success indistinguishable from never-firing).
- `tests/test_mapping_cp210x_recovery.py` — resolver tests rewritten
  against `os.path.realpath` (was `os.readlink`) including a new
  layout-(b) happy-path test that pins the news-pi01 case.

## 2026-05-02 19:30 KST — issue#16 HIL hot-fix v2: cp210x auto-recovery in start path

Operator HIL on PR #69 v1: first mapping attempt after tracker stop
still failed with `webctl_lost_view_post_crash` (rplidar_node crashed
inside container due to cp210x `set request 0x12 status: -110`).
Precheck cannot detect this — file-layer open() succeeds even when
the USB CDC control endpoint is wedged. Manual recovery button is
insufficient because the operator cannot tell from precheck alone
that recovery is needed.

### Added

- `Settings.mapping_auto_recover_lidar: bool` (default `True`,
  env override `GODO_WEBCTL_MAPPING_AUTO_RECOVER_LIDAR`). Toggles
  the auto-recovery in `mapping.start()` Phase 2 Step 2.5.
- `mapping.start()` Phase 2 Step 2.5 — calls `recover_cp210x(cfg)`
  before `systemctl start godo-mapping@active.service` whenever
  `cfg.mapping_auto_recover_lidar` is true. Best-effort:
  `CP210xRecoveryFailed` / `LidarPortNotResolvable` / `OSError` are
  logged at WARNING and Start proceeds (the recovery being unable
  to run is no worse than the pre-fix baseline; we want to give
  systemctl a chance regardless).

### Changed

- Updated invariant (ae) to document the dual-entrypoint recovery
  flow (manual button + automatic during start).

## 2026-05-02 17:51 KST — issue#16: mapping pre-check + cp210x recovery + ProcessTable refinement

Spec memory: `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.

Three patches in one PR (operator-decided 1단계 — short-term mitigation
for the CP2102N USB CDC stale-state race observed during issue#14 HIL):

1. `GET /api/mapping/precheck` — anonymous-readable readiness gate.
2. `POST /api/mapping/recover-lidar` — admin-only manual cp210x driver
   unbind/rebind (operator-driven via SPA button; NOT auto-on-Start).
3. ProcessTable classification refinement — split docker family so
   always-running daemons (dockerd/containerd) classify as `general`
   and only active-mapping processes (docker run-parent +
   containerd-shim*) stay as `godo`.

### Added

- `mapping.precheck(cfg, name)` + `PrecheckResult` / `PrecheckRow`
  dataclasses. Six per-check helpers (`_check_lidar_readable`,
  `_check_tracker_stopped`, `_check_image_present`, `_check_disk_space_mb`,
  `_check_name_available`, `_check_state_clean`) run in fixed
  PRECHECK_CHECK_NAMES order. `_check_lidar_readable` opens the LiDAR
  with `O_RDWR | O_NONBLOCK` as a "device-file-openable" probe (the
  flag form was reduced post-HIL — see Changed below).
  `_check_name_available` returns `ok=None` (pending) when the
  operator has not typed a name; this counts as not-ready so Start
  stays disabled.
- `mapping.recover_cp210x(cfg)` — resolve `cfg.serial.lidar_port` to
  sysfs USB path via `/sys/class/tty/<basename>/device` symlink, write
  `/run/godo/cp210x-recover.env` atomically, invoke `systemctl start
  godo-cp210x-recover.service`. New `_USB_PATH_REGEX = ^[0-9]+-[0-9.]+$`
  rejects any non-canonical bus-port form before the value reaches the
  bash helper.
- `mapping.CP210xRecoveryFailed` (→ HTTP 500) and
  `mapping.LidarPortNotResolvable` (→ HTTP 400) exception classes.
- `protocol.PRECHECK_FIELDS` / `PRECHECK_CHECK_FIELDS` /
  `PRECHECK_CHECK_NAMES` / `PRECHECK_DISK_FREE_MIN_MB` wire constants.
- `protocol.ERR_CP210X_RECOVERY_FAILED` /
  `ERR_LIDAR_PORT_NOT_RESOLVABLE` error codes.
- `protocol.DOCKER_FAMILY_NAMES` (frozenset {docker, dockerd, containerd}).
  Replaces the former `DOCKER_MAPPING_PROCESS_NAMES` set; the
  `containerd-shim*` prefix is matched at classify time.
- `constants.MAPPING_CP210X_RECOVER_ENV_FILENAME = "cp210x-recover.env"` +
  `constants.MAPPING_CP210X_RECOVER_TIMEOUT_S = 15.0`.
- `app.py::mapping_precheck_endpoint` (anonymous) +
  `mapping_recover_lidar_endpoint` (admin-only). Both bypass the L14
  lock-out so the SPA can render the precheck panel + recovery surface
  while a previous mapping run is mid-failure.
- `tests/test_mapping_precheck.py` — 18 tests covering each helper's
  happy + failure paths, name-pending semantics, aggregator order, and
  to_dict() field-order pin.
- `tests/test_mapping_cp210x_recovery.py` — 13 tests covering sysfs
  resolver happy path + 5 malformed-payload rejection cases + envfile
  atomic-write contract + subprocess argv pin + failure modes.
- `tests/test_protocol.py::test_precheck_*` — 5 new pinning tests for
  PRECHECK_FIELDS / PRECHECK_CHECK_FIELDS / PRECHECK_CHECK_NAMES /
  PRECHECK_DISK_FREE_MIN_MB + issue#16 error codes.
- `tests/test_processes.py::test_docker_family_disjoint_from_godo_and_managed`
  — ensures the docker-family set does not overlap with the
  godo/managed sets (would make classify_pid ambiguous).

### Changed

- `processes.Category` Literal extended to four values:
  `"general" | "godo" | "managed" | "docker"`. The SPA reads the
  current mapping state and recolours the `docker` rows (idle → green,
  mapping running → blue) without the wire payload needing a state
  field.
- `processes.classify_pid(name)` — single docker check. Order:
  managed → godo (GODO_PROCESS_NAMES) → docker (DOCKER_FAMILY_NAMES or
  `containerd-shim*` prefix) → general fallback.
- `mapping._check_lidar_readable` — flag swap from `O_RDWR | O_EXCL` →
  `O_RDWR | O_NONBLOCK`. POSIX leaves O_EXCL undefined without O_CREAT;
  Linux's tty driver ignores it on character devices, so the original
  flag was a no-op (operator HIL confirmed: lidar_readable showed ✓
  even while godo-tracker held the port). Semantics: the row is now
  unambiguously a "device file alive + permission OK" probe, NOT an
  "in-use detection" probe — that role belongs to `tracker_stopped`.
  O_NONBLOCK avoids the rare 60-s carrier-detect open-stall on
  USB-serial adapters.

### Removed

- `protocol.DOCKER_MAPPING_PROCESS_NAMES` — replaced by
  `DOCKER_FAMILY_NAMES`. No callers outside processes.py + the renamed
  test.

### Invariants

- **(ae) issue#16 — mapping precheck + cp210x recovery flow** — six
  fixed-order checks (PRECHECK_CHECK_NAMES) gate the SPA Start button
  via `precheck.ready=True`. Recovery uses systemd oneshot + polkit
  (mirror of `godo-mapping@active.service` pattern), NOT sudo or
  udev-chown. The bash helper at
  `/opt/godo-tracker/share/godo-cp210x-recover.sh` is ALSO defended by
  the same regex anchor that webctl uses (defence-in-depth — webctl
  should never produce a malformed USB_PATH that reaches the helper).

  Recovery has TWO entrypoints:
  1. Operator-driven via `POST /api/mapping/recover-lidar` — the SPA
     "🔧 LiDAR USB 복구" button next to the precheck `lidar_readable`
     row when it shows ✗.
  2. Automatic during `mapping.start()` Phase 2 Step 2.5 — runs
     unconditionally before `systemctl start godo-mapping@active`
     (operator-tuneable via `[webctl] mapping_auto_recover_lidar` in
     tracker.toml; default `True`). Best-effort: failures are logged
     and Start continues. issue#16 HIL hot-fix v2 (2026-05-02 KST)
     rationale: operator HIL surfaced that the first mapping attempt
     after a tracker stop reliably fails with cp210x stale state
     (`failed set request 0x12 status: -110`), and the precheck
     cannot detect this — `open()` at the file layer succeeds even
     when the USB CDC control endpoint is wedged. Auto-recovery in
     the start path eliminates the first-attempt failure with a
     ~1.5 s latency cost. Long-term path: issue#17 (GPIO UART direct
     connection) removes the cp210x USB stack entirely.

  Spec memory:
  `.claude/memory/project_mapping_precheck_and_cp210x_recovery.md`.

- **(af) issue#16 — ProcessTable docker category** — docker-family
  processes (`docker`, `dockerd`, `containerd`, `containerd-shim*`) all
  classify as a single fourth category `docker`. The wire payload does
  NOT carry mapping state; the SPA's System tab subscribes to
  `mappingStatus` and applies a state-aware colour to `.name-docker`
  cells (idle → `--color-status-ok` green, running → `--color-accent`
  blue). Operator HIL feedback drove this two-step trajectory: first
  refinement (16-original) split docker into two categories, but the
  visual loss (dockerd/containerd dropping from bold-blue to plain
  text) was operator-rejected. Final shape keeps everything bold and
  trades colour for state. classify_pid order is locked: managed →
  godo → docker → general fallback. tests/test_processes.py pins the
  new four-value category set + the disjoint-set invariant against
  godo/managed.
