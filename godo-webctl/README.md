# godo-webctl

Phase 4-3 operator HTTP for `godo_tracker_rt`. A small FastAPI process that
exposes three buttons (health / calibrate / map-backup) over the studio LAN
plus a vanilla-JS status page. Drives the tracker exclusively through its
Phase 4-2 D Unix-domain JSON-lines socket at `/run/godo/ctl.sock`.

## Endpoints

| Method | Path                | Purpose |
| --- | --- | --- |
| GET  | `/api/health`       | Tracker liveness + current AMCL mode |
| POST | `/api/calibrate`    | Latch `OneShot` on the tracker (returns immediately) |
| POST | `/api/map/backup`   | Atomic snapshot of `.pgm + .yaml` to `<backup_dir>/<UTC ts>/` |
| GET  | `/`                 | Static status page (`index.html`) |

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
curl http://127.0.0.1:8080/api/health
# → {"webctl":"ok","tracker":"ok","mode":"Idle"}

curl -X POST http://127.0.0.1:8080/api/calibrate
# → {"ok":true}

curl -X POST http://127.0.0.1:8080/api/map/backup
# → {"ok":true,"path":"/var/lib/godo/map-backups/20260426T143022Z"}
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
