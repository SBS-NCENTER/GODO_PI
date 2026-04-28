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
| `app.py` | `config`, `uds_client`, `backup`, `protocol`, FastAPI | App factory, 3 thin route handlers, static mount. |
| `__main__.py` | `config`, `app`, uvicorn | Process entrypoint; `workers=1` hardcoded. |

Dependency graph (no back-edges):

```text
protocol.py ◄── uds_client.py ◄──┐
                                  ├── app.py ◄── __main__.py
backup.py    ◄───────────────────┤
config.py    ◄───────────────────┘
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

## Phase 4.5 follow-up candidates

- Deadline-based UDS timeout (single shared `monotonic()` budget per
  request, not per syscall). Would convert worst-case wall-clock from
  `~3 × timeout` to exactly `timeout`.
- `/api/config` GET/PATCH (Tier-2 reload-class table per `SYSTEM_DESIGN.md`).
- React frontend; SSE for `/api/health` to drop the 1 s polling cost.
- `SocketGroup=godo` in the tracker unit so webctl can run as a
  different uid.

## Change log

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
