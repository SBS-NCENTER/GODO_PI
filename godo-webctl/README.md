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
| POST | `/api/map/edit`     | Brush-erase the active PGM via multipart mask + auto-backup-first + restart-pending sentinel touch (admin; tracker restart required) |
| POST | `/api/live`         | Toggle Live ↔ Idle on the tracker (admin) |
| GET  | `/api/last_pose`    | One-shot pose snapshot (public) |
| GET  | `/api/last_pose/stream` | SSE: pose @ 5 Hz (public) |
| GET  | `/api/map/image`    | PGM rendered to PNG of the **active** map (public) |
| GET  | `/api/maps`         | List every map pair under `GODO_WEBCTL_MAPS_DIR` (public) |
| GET  | `/api/maps/<name>/image` | PNG for a specific named map (public) |
| GET  | `/api/maps/<name>/yaml`  | YAML text for a specific named map (public) |
| POST | `/api/maps/<name>/activate` | Atomic active-symlink swap (admin) |
| DELETE | `/api/maps/<name>` | Remove `<name>.pgm` + `<name>.yaml` (admin; 409 on the active map) |
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
| `GODO_WEBCTL_MAP_PATH` | `/etc/godo/maps/studio_v1.pgm` | **DEPRECATED** (Track E, PR-C). One-release back-compat: when set + the file exists AND `${GODO_WEBCTL_MAPS_DIR}/active.pgm` is missing on boot, webctl auto-migrates the legacy pair into `maps_dir` and creates the active symlink. webctl logs WARN every boot until this var is unset. New deployments MUST use `GODO_WEBCTL_MAPS_DIR` and the active-symlink discipline. |
| `GODO_WEBCTL_MAPS_DIR` | `/var/lib/godo/maps` | Multi-map storage directory (Track E, PR-C). Map pairs are `<name>.pgm` + `<name>.yaml`; active pair selected via `active.pgm` + `active.yaml` symlinks (atomic `os.replace` under `flock`). |
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

The full systemd switchover (PR-A, 2026-04-30) installs three pieces:
the tracker bundle (`production/RPi5/systemd/install.sh`), the webctl
bundle (steps below), and the frontend dist. Run the tracker installer
FIRST so the polkit rule + unit files are in place before webctl
points its admin endpoint at them.

```bash
# 0. Pre-req: tracker installer (creates /opt/godo-tracker/, installs
#    the polkit rule, seeds /etc/godo/tracker.env). Skip if already done.
sudo bash /home/ncenter/projects/GODO/production/RPi5/systemd/install.sh

# 1. Pre-create /var/lib/godo/maps. The unit's StateDirectory=godo only
#    creates /var/lib/godo itself.
sudo install -d -m 0750 -o ncenter -g ncenter /var/lib/godo
sudo install -d -m 0750 -o ncenter -g ncenter /var/lib/godo/maps

# 2. Sync the source tree to the system install location. Exclude the
#    dev-tree .venv (uv sync rebuilds it at /opt/godo-webctl/.venv).
sudo rsync -a --delete --exclude='.venv' --exclude='__pycache__' \
  /home/ncenter/projects/GODO/godo-webctl/ /opt/godo-webctl/
sudo chown -R ncenter:ncenter /opt/godo-webctl

# 3. Create the venv + install runtime deps (no dev deps in production).
cd /opt/godo-webctl && uv sync --no-dev

# 4. Seed /etc/godo/webctl.env. Set GODO_WEBCTL_HOST=0.0.0.0 (so LAN /
#    Tailscale clients can reach the SPA) and GODO_WEBCTL_SPA_DIST=
#    /opt/godo-frontend/dist (after step 6 lands the dist there).
sudo install -d -m 0755 -o root -g root /etc/godo
sudo install -m 0644 systemd/godo-webctl.env.example /etc/godo/webctl.env
sudoedit /etc/godo/webctl.env

# 5. Install + enable the systemd unit.
sudo install -m 0644 systemd/godo-webctl.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now godo-webctl

# 6. Deploy the frontend dist (Vite+Svelte SPA). The dev tree must
#    have a current `npm run build` output.
sudo install -d -m 0755 -o root -g root /opt/godo-frontend
sudo rsync -a --delete /home/ncenter/projects/GODO/godo-frontend/dist \
  /opt/godo-frontend/
sudo chown -R ncenter:ncenter /opt/godo-frontend
sudo systemctl restart godo-webctl   # picks up GODO_WEBCTL_SPA_DIST
```

After step 6:

- `curl http://127.0.0.1:8080/api/health` returns
  `{"webctl":"ok","tracker":"unreachable","mode":null}` until the
  operator clicks Start on the SPA System tab; once tracker is up,
  the response shifts to `tracker:"ok","mode":"Idle"`.
- Browse to `http://<LAN-IP-or-Tailscale-name>:8080/` from any
  client; the SPA loads (default admin credentials are
  `ncenter`/`ncenter`; change immediately via
  `scripts/godo-webctl-passwd`).

### `/run/godo` ownership and webctl-tracker independence

Both `godo-webctl.service` and `godo-tracker.service` declare
`RuntimeDirectory=godo` + `RuntimeDirectoryPreserve=yes`. systemd
reference-counts ownership so `/run/godo/` survives whichever service
stops. Per the operator service-management policy
(`.claude/memory/project_godo_service_management_model.md`), webctl is
the auto-start service that owns `/run/godo` across reboots; the
tracker is manual-start via the SPA System tab Start button. webctl
tolerates `tracker.unreachable` cleanly — `/api/health` reflects the
state and the SPA renders tracker-down badges accordingly.

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

## Multi-map management (Track E, PR-C)

The mapping Docker pipeline can drop multiple `<name>.{pgm,yaml}` pairs
into `${GODO_WEBCTL_MAPS_DIR}` (default `/var/lib/godo/maps/`). webctl
exposes them through 5 endpoints (see the table above) and the SPA
`MapListPanel` lets the operator activate one or delete an obsolete
one without SSH.

### Active-symlink discipline

```text
/var/lib/godo/maps/
├─ studio_v1.pgm
├─ studio_v1.yaml
├─ studio_v2.pgm
├─ studio_v2.yaml
├─ active.pgm  → studio_v1.pgm        (relative-target symlink)
├─ active.yaml → studio_v1.yaml
└─ .activate.lock                     (advisory flock target)
```

- **Atomic swap**: `set_active(name)` writes a tempfile-suffixed symlink
  via `os.symlink(target, .active.<rand>.<ext>.tmp)` then `os.replace`
  to the canonical `active.<ext>` name. Two POSIX-atomic syscalls; no
  observable in-between state outside the webctl process.
- **Concurrent serialization**: both symlinks (PGM + YAML) are swapped
  under one `flock(LOCK_EX)` on `.activate.lock`. Last-writer-wins.
- **Self-healing**: every `set_active` sweeps `.active.*.tmp` leftovers
  from any prior crashed swap before creating its own tmp.
- **Path-traversal**: `<name>` MUST match `^[a-zA-Z0-9_-]{1,64}$`. The
  reserved name `"active"` is rejected at the `maps.py` layer (would
  otherwise collide with the resolver). `realpath` containment runs
  in every public function so a malicious symlink whose name passes
  the regex but escapes `maps_dir` is also rejected.

### Tracker restart

The C++ tracker reads `cfg.map_path` once at startup. After a
`/api/maps/<name>/activate` call, the response carries
`{"restart_required": true}` and the SPA confirm dialog offers a
"godo-tracker 재시작" button (loopback-only, calls
`/api/local/service/godo-tracker/restart`). On a non-loopback host the
button is hidden — operator must SSH in. The P2 hot-reload class
(tracker `inotify` + `OccupancyGrid` swap) removes this entirely.

### Recovering a botched activate

The active state is solely the two symlinks. Re-run
`POST /api/maps/<other>/activate` (or `ln -sfT <name>.pgm
/var/lib/godo/maps/active.pgm` over SSH) and the next tracker startup
picks up the new target.

### Migrating a legacy `cfg.map_path` deployment

`scripts/godo-maps-migrate` is the operator one-shot. Boot-time
auto-migration is also wired (idempotent), but the script is the
visible-action path:

```bash
sudo install -m 0755 scripts/godo-maps-migrate /usr/local/bin/
sudo godo-maps-migrate /etc/godo/maps/studio_v1.pgm
# → migrated /etc/godo/maps/studio_v1.pgm -> /var/lib/godo/maps (active=studio_v1)
sudo systemctl restart godo-webctl  # to clear the boot-time deprecation WARN
```

After migration, unset `GODO_WEBCTL_MAP_PATH` (edit `/etc/godo/webctl.env`)
to silence the every-boot WARN.

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
| `EROFS` from `set_active` after overriding `GODO_WEBCTL_MAPS_DIR` | The unit's `ProtectSystem=strict` + `ReadWritePaths=/var/lib/godo` only covers the default. | Add the new path to a unit override: `sudo systemctl edit godo-webctl` → `[Service]\nReadWritePaths=/var/lib/godo /your/maps/dir`, then `sudo systemctl daemon-reload` and `restart`. |
| `map_is_active` (HTTP 409) on DELETE | Operator clicked Delete on the active row. | Activate a different map first, then delete; the SPA also disables the Delete button on the active row. |
| `maps.legacy_map_path_in_use` WARN every boot | `GODO_WEBCTL_MAP_PATH` is still set in `/etc/godo/webctl.env`. | After confirming `${GODO_WEBCTL_MAPS_DIR}/active.pgm` exists, comment out (or remove) the `GODO_WEBCTL_MAP_PATH=…` line and restart webctl. |
| `mask_shape_mismatch` (HTTP 400) on `/api/map/edit` | The mask PNG dimensions do not equal the active PGM dimensions (the SPA must build the canvas at the same logical `width × height` reported by `/api/maps/<active>/dimensions`). | The SPA's `MapMaskCanvas` sizes the canvas from `mapMetadata.width × .height`. A mismatch indicates the operator opened `/map-edit` while the active map changed underneath; reload the page so `mapMetadata` re-fetches. |
| `mask_too_large` (HTTP 413) on `/api/map/edit` | The mask PNG exceeds `MAP_EDIT_MASK_PNG_MAX_BYTES = 4 MiB`. | Reduce brush usage or lower the canvas resolution. The SPA short-circuits before upload at the same cap. |
| `active_map_missing` (HTTP 503) on `/api/map/edit` | `${GODO_WEBCTL_MAPS_DIR}/active.pgm` symlink is missing or broken. | `ls -l ${GODO_WEBCTL_MAPS_DIR}/active.pgm`; activate a valid map via `POST /api/maps/<name>/activate` (or the SPA's `/map` page). |

## Tests

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -m "not hardware_tracker"   # all unit + integration

# Hardware-required smoke (run on news-pi01 with the tracker live):
uv run pytest -m hardware_tracker
```
