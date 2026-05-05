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

Entries are archived weekly under [`CODEBASE/`](./CODEBASE/) (ISO 8601 weeks, KST Mon–Sun). The master keeps invariants + Index only; per-week dated entries live in their archive file.

| Week | Date range (KST) | Archive |
| --- | --- | --- |
| 2026-W19 | 2026-05-04 → 2026-05-10 | [CODEBASE/2026-W19.md](./CODEBASE/2026-W19.md) |
| 2026-W18 | 2026-04-27 → 2026-05-03 | [CODEBASE/2026-W18.md](./CODEBASE/2026-W18.md) |
| 2026-W17 | 2026-04-20 → 2026-04-26 | [CODEBASE/2026-W17.md](./CODEBASE/2026-W17.md) |

---

## Quick reference links

- Project guide: [`CLAUDE.md`](../CLAUDE.md) — operating rules + agent pipeline + deploy.
- Cross-stack scaffold: [`CODEBASE.md`](../CODEBASE.md) (root) — module roles + cross-stack data flow.
- Backend design SSOT: [`SYSTEM_DESIGN.md`](../SYSTEM_DESIGN.md) — RT path / AMCL / FreeD / UDS bridge.
- Sibling stacks:
  - C++ tracker: [`production/RPi5/CODEBASE.md`](../production/RPi5/CODEBASE.md) — webctl drives via UDS at `/run/godo/ctl.sock`.
  - SPA: [`godo-frontend/CODEBASE.md`](../godo-frontend/CODEBASE.md) — webctl serves the built bundle via `StaticFiles` and exposes `/api/*` + SSE.
- Project state: [`PROGRESS.md`](../PROGRESS.md) (English) · [`doc/history.md`](../doc/history.md) (Korean).
- Most recent shipping: [`CODEBASE/2026-W19.md`](./CODEBASE/2026-W19.md).
- README (deploy + dev runbook): [`README.md`](./README.md).
