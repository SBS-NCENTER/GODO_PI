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

### (e) `workers=1`

`__main__.py` hardcodes `workers=1` in `uvicorn.run(...)`. The tracker
UDS server is single-client, one-shot per connection; multi-worker
uvicorn would multiply the chances of stale-socket races without
serialising anything meaningful.

### (f) `backup_map` is single-writer

`backup_map` is single-writer at runtime (uvicorn `workers=1` + handler
single-await). Concurrent invocation is undefined; the bounded
`MAX_RENAME_ATTEMPTS=9` retry exists only for back-to-back calls in the
same UTC second by a single writer.

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

`MAPS_NAME_REGEX = ^[a-zA-Z0-9_-]{1,64}$` lives in `constants.py`
(Tier-1). Every public `maps.py` function that returns or operates on
a path validates the name AND runs `os.path.realpath(result).startswith(
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
  SSE @ 5 Hz), `/api/logs/tail` (PR-DIAG), `/api/local/services`
  (loopback), `/api/local/services/stream` (loopback),
  `/api/local/journal/<name>` (loopback).
- **Login-gated mutations** (`Depends(require_admin)`): `/api/calibrate`,
  `/api/live`, `/api/map/backup`, `/api/map/backup/<ts>/restore`
  (Track B-BACKUP), `/api/maps/<name>/activate`,
  `DELETE /api/maps/<name>`, `/api/local/service/<name>/<action>`
  (loopback + admin), `/api/system/reboot`, `/api/system/shutdown`.
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

## Phase 4.5 follow-up candidates

- Deadline-based UDS timeout (single shared `monotonic()` budget per
  request, not per syscall). Would convert worst-case wall-clock from
  `~3 × timeout` to exactly `timeout`.
- `/api/config` GET/PATCH (Tier-2 reload-class table per `SYSTEM_DESIGN.md`).
- React frontend; SSE for `/api/health` to drop the 1 s polling cost.
- `SocketGroup=godo` in the tracker unit so webctl can run as a
  different uid.

## Change log

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
