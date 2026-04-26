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
│   ├─ test_uds_client.py             # 9 cases incl. M3 buffer-full
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
Python (protocol.py)              C++ origin
──────────────────────────        ─────────────────────────────────────
UDS_REQUEST_MAX_BYTES = 4096      constants.hpp:54
MODE_IDLE     = "Idle"            rt_flags.hpp::AmclMode::Idle
MODE_ONESHOT  = "OneShot"         rt_flags.hpp::AmclMode::OneShot
MODE_LIVE     = "Live"            rt_flags.hpp::AmclMode::Live
CMD_PING      = "ping"            json_mini.cpp::parse_request L46-50
CMD_GET_MODE  = "get_mode"        json_mini.cpp::parse_request L51-55
CMD_SET_MODE  = "set_mode"        json_mini.cpp::parse_request L56-72
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
