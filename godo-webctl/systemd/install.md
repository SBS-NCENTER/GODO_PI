# systemd install notes

The `godo-webctl.service` unit is documented in the top-level
[`README.md`](../README.md) under "Install on news-pi01". This file
covers the **PR-A** addition: `godo-local-window.service` (Chromium
kiosk window auto-launching at boot on the RPi 5 desktop).

## godo-local-window.service

### Prerequisites

- Pi OS Bookworm with a graphical session (the unit binds
  `WantedBy=graphical.target`).
- `chromium` package installed at `/usr/bin/chromium`. On Bookworm:

  ```bash
  sudo apt install chromium
  ```

  If your install only ships `/usr/bin/chromium-browser`, edit the
  `ExecStart=` line in the unit accordingly.

### Install

```bash
sudo install -m 0644 systemd/godo-local-window.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
# enable for graphical.target on next boot:
sudo systemctl enable godo-local-window
# start now (must be inside an active graphical session):
sudo systemctl start godo-local-window
```

The unit's `ExecStartPre=` polls `http://127.0.0.1:8080/api/health` for
up to 60 s before launching Chromium; if `godo-webctl` is not up, the
unit fails fast (no half-loaded kiosk).

### Behavior notes (per planner N3 / N4)

- **Profile dir at `/run/user/<uid>/godo-chromium-profile` (tmpfs)** —
  wiped on reboot so cookies/cache cannot grow unbounded over months.
  This means saved sessions and any state stored in
  `localStorage` reset on every reboot. The B-LOCAL page does not need
  persistent state (everything it shows is read live from the backend
  every second), so this is fine.
- **`--kiosk`** locks navigation. The operator cannot use Ctrl+L /
  Ctrl+T / F11 / Ctrl+W to escape. To exit during maintenance:
  `sudo systemctl stop godo-local-window` (or close from a remote SSH
  session via `pkill chromium`).

### Verifying

```bash
systemctl status godo-local-window
journalctl -u godo-local-window -n 30
# or, from the kiosk display:
xdotool search --name "godo" getwindowname
```

## Multi-map storage (Track E, PR-C — 2026-04-29)

The Track E surface lives in `${GODO_WEBCTL_MAPS_DIR}` (default
`/var/lib/godo/maps`). Map pairs are `<name>.pgm + <name>.yaml`; the
active pair is selected via `active.pgm + active.yaml` symlinks (atomic
`os.replace` swaps under `flock`).

### Initial setup on news-pi01

```bash
sudo install -d -m 0750 -o ncenter -g ncenter /var/lib/godo/maps
```

The default `godo-webctl.service` already covers
`/var/lib/godo` via `ReadWritePaths=/var/lib/godo` (no change needed).

### Mapping container volume mount

The mapping Docker pipeline previously wrote into
`godo-mapping/maps/` on the dev workspace. For production deploys
flip the volume mount to the new directory:

```bash
docker run --rm \
  -v /var/lib/godo/maps:/output \
  godo-mapping:latest
```

The mapping container drops `<name>.pgm + <name>.yaml`; webctl picks
them up automatically (no restart). The operator activates one via
the SPA.

### Operator script install

`scripts/godo-maps-migrate` is a one-shot for legacy
`GODO_WEBCTL_MAP_PATH`-based deployments. Install once on news-pi01:

```bash
sudo install -m 0755 /opt/godo-webctl/scripts/godo-maps-migrate \
  /usr/local/bin/
```

### Overriding `GODO_WEBCTL_MAPS_DIR`

The default unit's `ReadWritePaths=/var/lib/godo` covers the default
`maps_dir`. If an operator overrides to a path outside `/var/lib/godo`
(e.g. an external SSD), they MUST extend the unit:

```bash
sudo systemctl edit godo-webctl
# add:
#   [Service]
#   ReadWritePaths=/var/lib/godo /mnt/maps
sudo systemctl daemon-reload
sudo systemctl restart godo-webctl
```

Without that override, `set_active`/`delete_pair` raise `EROFS` from
`ProtectSystem=strict`.
