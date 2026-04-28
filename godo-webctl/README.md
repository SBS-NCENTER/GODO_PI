# godo-webctl

Phase 4-3 operator HTTP for `godo_tracker_rt`. A small FastAPI process that
exposes three buttons (health / calibrate / map-backup) over the studio LAN
plus a vanilla-JS status page. Drives the tracker exclusively through its
Phase 4-2 D Unix-domain JSON-lines socket at `/run/godo/ctl.sock`.

## Endpoints

| Method | Path                | Purpose |
| --- | --- | --- |
| GET  | `/api/health`       | Tracker liveness + current AMCL mode (public) |
| POST | `/api/calibrate`    | Latch `OneShot` on the tracker (admin) |
| POST | `/api/map/backup`   | Atomic snapshot of `.pgm + .yaml` (admin) |
| POST | `/api/live`         | Toggle Live ↔ Idle on the tracker (admin) |
| GET  | `/api/last_pose`    | One-shot pose snapshot (public) |
| GET  | `/api/last_pose/stream` | SSE: pose @ 5 Hz (public) |
| GET  | `/api/map/image`    | PGM rendered to PNG (public) |
| GET  | `/api/activity?n=`  | Last N operator actions (public) |
| POST | `/api/auth/login`   | Issue a JWT (public) |
| POST | `/api/auth/logout`  | Acknowledge logout (viewer) |
| GET  | `/api/auth/me`      | Decode current token (viewer) |
| POST | `/api/auth/refresh` | Re-issue a JWT with extended exp (viewer) |
| GET  | `/api/local/services`        | systemctl status × 3 units (public, loopback) |
| POST | `/api/local/service/<name>/<action>` | start \| stop \| restart (admin, loopback) |
| GET  | `/api/local/journal/<name>?n=` | journalctl tail (public, loopback) |
| GET  | `/api/local/services/stream` | SSE: services status @ 1 Hz (public, loopback) |
| POST | `/api/system/reboot` | `shutdown -r +0` (admin) |
| POST | `/api/system/shutdown` | `shutdown -h +0` (admin) |
| GET  | `/`                 | Static status page (`index.html`) — replaced by SPA when `GODO_WEBCTL_SPA_DIST` is set |

## Auth

**Track F (PR-B fold) auth model**: read endpoints are anonymous-readable
so the operator can monitor the studio without logging in (open the SPA,
see live pose / map / service status / activity / journal). Login is
required ONLY for **mutations** (calibrate, live toggle, map backup, all
`/api/local/service/<name>/<action>` writes, system reboot/shutdown).
Anonymous calls to mutation endpoints return HTTP 401
`{"err":"auth_required"}`. The SPA disables those buttons and shows a
"제어 동작은 로그인 필요" hint when no session is present.

Loopback gating on `/api/local/*` is **independent** of auth: anyone
with a TCP peer outside `127.0.0.0/8` + `::1` is rejected at the
`loopback_only` dependency before auth runs. So a remote viewer cannot
read journal output, but the kiosk operator at the Pi can — without
logging in.

PR-A introduced JWT-based auth on mutation endpoints.
HS256 with a 6 h TTL and a server-side secret persisted at
`/var/lib/godo/auth/jwt_secret` (mode 0600, lazy-generated 32 random
bytes on first boot). Restarting `godo-webctl` re-reads the secret;
deleting the file rotates and invalidates all extant operator sessions.

`users.json` (default `/var/lib/godo/auth/users.json`) is the
credential store. Hashes are bcrypt at cost factor 12 (~300 ms / login
on RPi 5 — deliberate friction; do **not** lower without revisiting the
threat model). On first boot a default admin `ncenter`/`ncenter` is
lazy-seeded if the file is absent. Change it via:

```bash
sudo -u ncenter scripts/godo-webctl-passwd \
  ncenter admin /var/lib/godo/auth/users.json
```

If `users.json` is hand-edited into invalid JSON, webctl logs at ERROR
and keeps running — `/api/health` stays 200, but every login returns
`HTTP 503 {"err":"auth_unavailable"}` so the operator sees the failure
on the kiosk B-LOCAL page. Recovery: fix the file, then restart webctl.

### Roles

| Role     | Powers |
| ---      | --- |
| anon     | Every read endpoint (`/api/health`, `/api/last_pose*`, `/api/map/image`, `/api/activity`, `/api/local/services*`, `/api/local/journal/*` from loopback). 401 on every write. |
| `viewer` | Same as anon, plus a session for `/api/auth/me`, `/refresh`, `/logout`. No write powers. |
| `admin`  | Everything anon/viewer can do, plus calibrate, live, map backup, `/api/local/service/*` writes, system reboot/shutdown. |

### Default `GODO_WEBCTL_HOST=127.0.0.1` is the firewall

The bind address default is loopback. The weak default seed credential
is only exploitable by someone already on the host. If you flip
`GODO_WEBCTL_HOST` to `0.0.0.0` for studio-LAN access, **also** change
the seed password before exposing the service.

## SSE channels

| Path | Cadence | Auth | Notes |
| --- | --- | --- | --- |
| `/api/last_pose/stream` | 5 Hz | public | Tracker `get_last_pose` polled per tick. |
| `/api/local/services/stream` | 1 Hz | public (loopback) | `systemctl is-active` polled per tick. |

Both channels:

- Emit `: keepalive\n\n` every 15 s of idle stream time.
- Set `Cache-Control: no-cache` and `X-Accel-Buffering: no` so a future
  nginx/Caddy fronting the service does not buffer the cadence away.
- Authenticate via either `Authorization: Bearer <token>` (regular
  `fetch`) or `?token=<jwt>` query param (browser EventSource cannot
  set headers). Uvicorn access logs scrub the token query param.

## Local-only routes

`/api/local/*` is gated by a FastAPI dependency that checks the actual
TCP peer IP (`request.client.host`) against IPv4 `127.0.0.0/8` and
IPv6 `::1`. `X-Forwarded-For` is **never** honoured (no proxy in our
deployment). Anything else returns HTTP 403
`{"err":"loopback_only"}`.

### `GET /api/health`

```text
200  {"webctl":"ok","tracker":"ok","mode":"Idle"|"OneShot"|"Live"}
200  {"webctl":"ok","tracker":"unreachable","mode":null}    # UDS down/timeout
```

The status field IS the signal — webctl returns HTTP 200 even when the
tracker is unreachable, so a browser-side polling UI stays clean.

### `POST /api/calibrate`

```text
200  {"ok":true}                                # OneShot latched
400  {"ok":false,"err":"bad_mode"}              # tracker rejected (should not happen)
502  {"ok":false,"err":"protocol_error"}        # malformed UDS reply
503  {"ok":false,"err":"tracker_unreachable"}   # UDS connect failed
504  {"ok":false,"err":"tracker_timeout"}       # UDS syscall timed out
```

**Calibrate semantics (D4):** a `200 {"ok":true}` means the tracker has
**latched** `OneShot` into `g_amcl_mode`, NOT that calibration has
completed. The cold writer runs `converge()` (~1 s at 5000 particles)
then returns to `Idle` itself. To detect completion, poll `/api/health`
and watch for `mode == "Idle"`.

### `POST /api/map/backup`

```text
200  {"ok":true,"path":"/var/lib/godo/map-backups/20260426T143022Z"}
404  {"ok":false,"err":"map_path_not_found"}
500  {"ok":false,"err":"backup_dir_unwritable"}
500  {"ok":false,"err":"copy_failed: <errno>"}
```

## Environment variables

All values are optional. Defaults shown in the right column.

| Variable | Default | Notes |
| --- | --- | --- |
| `GODO_WEBCTL_HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` for studio LAN. |
| `GODO_WEBCTL_PORT` | `8080` | HTTP port. |
| `GODO_WEBCTL_UDS_SOCKET` | `/run/godo/ctl.sock` | Tracker UDS. Same-uid clients only (see `production/RPi5/doc/uds_protocol.md` §F). |
| `GODO_WEBCTL_BACKUP_DIR` | `/var/lib/godo/map-backups` | Where `/api/map/backup` writes timestamped snapshots. |
| `GODO_WEBCTL_MAP_PATH` | `/etc/godo/maps/studio_v1.pgm` | **MUST include `.pgm` suffix** AND **MUST match the tracker's `GODO_AMCL_MAP_PATH`**. The `.yaml` sibling is derived by stripping `.pgm` (mirrors `occupancy_grid.cpp::yaml_path_for`). |
| `GODO_WEBCTL_HEALTH_UDS_TIMEOUT_S` | `2.0` | Per-syscall UDS timeout for `/api/health`. Worst-case wall-clock ≤ ~6 s under server stall. |
| `GODO_WEBCTL_CALIBRATE_UDS_TIMEOUT_S` | `30.0` | Per-syscall UDS timeout for `/api/calibrate`. UDS returns immediately (it just latches the mode); 30 s is a safety margin. |
| `GODO_WEBCTL_JWT_SECRET_PATH` | `/var/lib/godo/auth/jwt_secret` | Where the HS256 secret lives. Lazy-generated 32 random bytes, mode 0600. |
| `GODO_WEBCTL_USERS_FILE` | `/var/lib/godo/auth/users.json` | bcrypt credentials store. Lazy-seeded on first boot. |
| `GODO_WEBCTL_SPA_DIST` | _unset_ | Path to a built Vite+Svelte `dist/`. When set, served at `/`; when unset, falls back to legacy `static/index.html`. |
| `GODO_WEBCTL_CHROMIUM_LOOPBACK_ONLY` | `true` | Loopback gate for `/api/local/*`. Do **not** flip without an upstream loopback gate. |

## Install — dev

```bash
cd godo-webctl
uv sync                                # creates .venv, installs runtime + dev
uv run godo-webctl                     # binds 127.0.0.1:8080 by default
# → http://127.0.0.1:8080/             # static page
```

## Install on news-pi01

```bash
# 1. Sync the source tree to the system install location.
sudo rsync -a --delete /home/ncenter/projects/GODO/godo-webctl/ /opt/godo-webctl/
sudo chown -R ncenter:ncenter /opt/godo-webctl

# 2. Create the venv + install runtime deps (no dev deps in production).
cd /opt/godo-webctl && uv sync --no-dev

# 3. (Optional) Override defaults via the env file.
sudo install -m 0644 systemd/godo-webctl.env.example /etc/godo/webctl.env

# 4. Install + enable the systemd unit.
sudo install -m 0644 systemd/godo-webctl.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now godo-webctl
```

`/var/lib/godo/` is created by systemd (`StateDirectory=godo`, mode 0750).
`/run/godo/` is owned by `godo-tracker.service`; webctl waits for the
tracker via `After=`/`Wants=`.

## curl examples

```bash
# Public — no auth.
curl http://127.0.0.1:8080/api/health
# → {"webctl":"ok","tracker":"ok","mode":"Idle"}

# Auth dance.
TOKEN=$(curl -sX POST http://127.0.0.1:8080/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"ncenter","password":"ncenter"}' | jq -r .token)

curl -X POST http://127.0.0.1:8080/api/calibrate \
  -H "authorization: Bearer $TOKEN"
# → {"ok":true}

curl -X POST http://127.0.0.1:8080/api/map/backup \
  -H "authorization: Bearer $TOKEN"
# → {"ok":true,"path":"/var/lib/godo/map-backups/20260426T143022Z"}

curl -X POST http://127.0.0.1:8080/api/live \
  -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' \
  -d '{"enable":true}'
# → {"ok":true,"mode":"Live"}

# SSE: token-on-URL because EventSource cannot send headers.
curl -N "http://127.0.0.1:8080/api/last_pose/stream?token=$TOKEN"
# data: {"valid":1,"x_m":1.5,...}
# data: ...
```

## Static page UX

`index.html` polls `/api/health` every 1 s, paints `webctl` / `tracker` /
`mode`, and provides two buttons:

- **Calibrate (OneShot)** — `POST /api/calibrate`; the `mode` field will
  flip to `OneShot` then back to `Idle` once converge() returns.
- **Backup map** — `POST /api/map/backup`; the JSON response (with the
  destination path) appears in the *Last action* block.

Polling pauses while the browser tab is hidden (Page Visibility API), so
an idle tab in the background generates zero traffic.

## Restoring a backup

`/var/lib/godo/map-backups/<timestamp>/` contains the `.pgm` and `.yaml`
exactly as they existed at backup time. The YAML's `image: studio_v1.pgm`
field is a **relative reference**; restoring requires both files to land
at the names the YAML expects.

```bash
sudo cp /var/lib/godo/map-backups/20260426T143022Z/* /etc/godo/maps/
```

Do NOT rename individual files unless you also edit the YAML's `image:`
field to match.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `tracker:"unreachable"` always | `godo_tracker_rt` not running OR UDS path mismatch | `systemctl status godo-tracker`; check `GODO_WEBCTL_UDS_SOCKET` matches the tracker's `cfg.uds_socket`. |
| `tracker_unreachable` on calibrate after fresh boot | Tracker hasn't created the socket yet | Wait a few seconds; the systemd `After=`/`Wants=` ordering is best-effort. |
| `backup_dir_unwritable` | webctl runs as a user without `/var/lib/godo` write access | Service unit pins `User=ncenter`; check `ls -ld /var/lib/godo`. |
| `map_path_not_found` | `GODO_WEBCTL_MAP_PATH` typo or stale install | Confirm the file exists; ensure the env value INCLUDES `.pgm`. |
| Tracker permission-denied on UDS connect | webctl is running as a different uid than the tracker | Run as the same uid (`ncenter` on news-pi01) until `SocketGroup=godo` lands (Phase 4-2 follow-up). |

## Tests

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -m "not hardware_tracker"   # all unit + integration

# Hardware-required smoke (run on news-pi01 with the tracker live):
uv run pytest -m hardware_tracker
```
