#!/usr/bin/env bash
# Install the GODO systemd units. Idempotent — safe to re-run.
#
# Usage:
#   sudo bash production/RPi5/systemd/install.sh
#
# What it does:
#   1. rsync repo -> /opt/godo-tracker/ (binary + helper script)
#   2. Install systemd units to /etc/systemd/system/
#   3. Install watchdog drop-in to /etc/systemd/system.conf.d/
#   4. Install polkit rule to /etc/polkit-1/rules.d/ (lets the
#      ncenter group call systemctl start/stop/restart on the GODO
#      units AND `shutdown -r/-h +0` for host reboot / power-off
#      without sudo; both used by webctl's admin endpoints)
#   5. Seed /etc/godo/tracker.env from the template if absent (preserves
#      a real .env if the operator already wrote one)
#   6. Seed /var/lib/godo/tracker.toml (empty, ncenter-owned) so the
#      tracker's atomic-rename writer can land Config-tab edits there.
#      /etc/godo is ReadOnlyPaths under ProtectSystem=strict, so the
#      live-mutable runtime config lives under /var/lib (which is
#      already in ReadWritePaths via StateDirectory=godo).
#   7. systemctl daemon-reload
#   8. (Does NOT enable the units — operator decides; instructions printed)
#
# This installer covers the RPi5 tracker side ONLY. godo-webctl install
# (rsync to /opt/godo-webctl, uv sync, unit + envfile, frontend dist) is
# documented in godo-webctl/systemd/install.md.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "install: must run as root (sudo)" >&2; exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RPI5_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BIN_SRC="${RPI5_DIR}/build/src/godo_tracker_rt/godo_tracker_rt"

if [[ ! -x "$BIN_SRC" ]]; then
    echo "install: tracker binary not found at $BIN_SRC. Run scripts/build.sh first." >&2
    exit 1
fi

echo "[1/11] Installing /opt/godo-tracker/"
install -d -m 0755 -o root -g root /opt/godo-tracker
install -d -m 0755 -o root -g root /opt/godo-tracker/share
install -m 0755 -o root -g root "$BIN_SRC"                          /opt/godo-tracker/godo_tracker_rt
install -m 0755 -o root -g root "$SCRIPT_DIR/godo-irq-pin.sh"       /opt/godo-tracker/godo-irq-pin.sh
# Cross-language SSOT — webctl parses this header to render the SPA
# Config tab. /opt/godo-tracker/share/ is the production-side mirror
# of the dev tree's `production/RPi5/src/core/config_schema.hpp`.
# webctl points at it via GODO_WEBCTL_CONFIG_SCHEMA_PATH (set in
# /etc/godo/webctl.env). Re-running install.sh after a tracker rebuild
# refreshes both the binary AND the schema mirror.
install -m 0644 -o root -g root "$RPI5_DIR/src/core/config_schema.hpp" \
                                /opt/godo-tracker/share/config_schema.hpp

echo "[2/11] Installing systemd units to /etc/systemd/system/"
install -m 0644 "$SCRIPT_DIR/godo-irq-pin.service"  /etc/systemd/system/godo-irq-pin.service
install -m 0644 "$SCRIPT_DIR/godo-tracker.service"  /etc/systemd/system/godo-tracker.service
# issue#14 — mapping pipeline template unit. Operator never enables
# this; webctl drives `systemctl start godo-mapping@active.service`.
install -m 0644 "$SCRIPT_DIR/godo-mapping@.service" /etc/systemd/system/godo-mapping@.service

echo "[3/11] Installing watchdog drop-in"
install -d -m 0755 /etc/systemd/system.conf.d
install -m 0644 "$SCRIPT_DIR/system.conf.d/godo-watchdog.conf" \
                /etc/systemd/system.conf.d/godo-watchdog.conf

echo "[4/11] Installing polkit rule for ncenter-group systemctl + login1 access"
install -d -m 0755 /etc/polkit-1/rules.d
install -m 0644 "$SCRIPT_DIR/49-godo-systemctl.rules" \
                /etc/polkit-1/rules.d/49-godo-systemctl.rules
# polkit 126 (Trixie) reloads rules on file change automatically via
# inotify — no service-restart command is required. We probe the
# polkit daemon path so failures here are visible (would otherwise be
# silent until the operator pressed a Start/Stop button).
if ! systemctl is-active --quiet polkit; then
    echo "install: warning — polkit unit is not active; rule will load when polkit starts" >&2
fi

echo "[5/11] Seeding /etc/godo/tracker.env (preserves existing real .env)"
install -d -m 0755 -o root -g root /etc/godo
if [[ ! -e /etc/godo/tracker.env ]]; then
    install -m 0644 -o root -g root "$SCRIPT_DIR/godo-tracker.env.example" /etc/godo/tracker.env
    echo "  → /etc/godo/tracker.env created from template (operator MUST review;"
    echo "    GODO_AMCL_MAP_PATH already points at /var/lib/godo/maps/active.pgm)"
else
    echo "  → /etc/godo/tracker.env already present; left untouched."
    echo "    Compare with $SCRIPT_DIR/godo-tracker.env.example for new keys."
fi

echo "[6/11] Seeding /var/lib/godo/tracker.toml (empty, ncenter-owned)"
# /var/lib/godo itself is created by the unit's StateDirectory=godo, but
# the install path is also valid before the unit ever runs (the directory
# tree is harmless if /var/lib/godo/maps/ etc. arrive later).
install -d -m 0750 -o ncenter -g ncenter /var/lib/godo
if [[ ! -e /var/lib/godo/tracker.toml ]]; then
    install -m 0644 -o ncenter -g ncenter /dev/null /var/lib/godo/tracker.toml
    echo "  → /var/lib/godo/tracker.toml created empty (ncenter:ncenter 0644)."
    echo "    SPA Config-tab edits land here via atomic mkstemp+rename."
else
    echo "  → /var/lib/godo/tracker.toml already present; left untouched."
fi
# Migrate a pre-fix install that wrote tracker.toml under /etc/godo (where
# it would have been read-only at runtime anyway). The file is harmless to
# leave behind, but moving it makes the new RW path the SSOT and avoids
# operator confusion about which file is "current".
if [[ -e /etc/godo/tracker.toml ]]; then
    if [[ -s /var/lib/godo/tracker.toml ]]; then
        echo "  → WARN: both /etc/godo/tracker.toml AND /var/lib/godo/tracker.toml exist;"
        echo "    /var/lib is the new SSOT. Leaving /etc copy in place — operator"
        echo "    must reconcile manually." >&2
    else
        mv /etc/godo/tracker.toml /var/lib/godo/tracker.toml
        chown ncenter:ncenter /var/lib/godo/tracker.toml
        chmod 0644 /var/lib/godo/tracker.toml
        echo "  → migrated /etc/godo/tracker.toml → /var/lib/godo/tracker.toml"
    fi
fi

echo "[7/11] Installing godo-mapping@.env.example reference (issue#14)"
# Documentation only — webctl writes the real envfile at runtime to
# /run/godo/mapping/active.env. This reference copy lives in /etc/godo
# so an operator inspecting the system can see the expected shape.
install -m 0644 -o root -g root "$SCRIPT_DIR/godo-mapping@.env.example" \
                                 /etc/godo/godo-mapping@.env.example

echo "[8/11] Ensuring /var/lib/godo/maps/.preview/ exists (issue#14 mapping previews)"
# Bind-mount target inside the container at /maps/.preview. webctl reads
# the PGM via realpath-contained `mapping.preview_path`. Belt-and-
# suspenders: the entrypoint also `mkdir -p /maps/.preview` at
# container-start.
install -d -m 0750 -o ncenter -g ncenter /var/lib/godo/maps/.preview

echo "[9/11] Ensuring docker group membership for ncenter (issue#14)"
# webctl shells out to `docker inspect` / `docker stats` etc. without
# sudo; ncenter must be in the docker group. First-time-after-install
# requires log out + back in (or reboot) for the group membership to
# take effect on existing sessions. Idempotent: re-runs print a no-op.
if id -nG ncenter | grep -qw docker; then
    echo "  → ncenter already in docker group."
else
    if getent group docker >/dev/null 2>&1; then
        usermod -aG docker ncenter
        echo "  → ncenter added to docker group."
        echo "  → IMPORTANT: operator must log out + log back in (or reboot)"
        echo "    for this membership to take effect on existing sessions."
        echo "  → Verify with: groups ncenter | grep -w docker && docker ps"
    else
        echo "  → docker group not present — install Docker first, then re-run install.sh." >&2
    fi
fi

# (M2 fix — no /run/godo/mapping/ install-time seed. /run is tmpfs and
# any install-time mkdir is wiped on reboot. webctl's
# `_write_run_envfile` performs `Path(...).mkdir(parents=True,
# exist_ok=True, mode=0o750)` at runtime before its atomic write — this
# is the only correct creator. /run/godo itself comes from
# godo-tracker.service's RuntimeDirectory=godo + RuntimeDirectoryPreserve=yes,
# and webctl already has ReadWritePaths=/run/godo so the runtime mkdir
# of the `mapping` subdir succeeds without elevation.)

echo "[10/11] systemctl daemon-reload"
systemctl daemon-reload

echo
echo "[11/11] Install complete. Auto-start policy (operator decision):"
echo "  - godo-irq-pin.service                AUTO    (IRQ pinning, oneshot, no runtime risk)"
echo "  - godo-webctl.service                 AUTO    (operator UI; must reach at boot)"
echo "  - godo-tracker.service                MANUAL  (start via SPA System tab Start button)"
echo "  - godo-mapping@active.service         MANUAL  (issue#14 — driven by webctl /api/mapping/start)"
echo
echo "Enable the auto-start units:"
echo "  sudo systemctl enable --now godo-irq-pin.service"
echo "  sudo systemctl enable --now godo-webctl.service   # after webctl install"
echo
echo "Tracker is installed but NOT enabled — operator brings it online via SPA."
echo "To start tracker manually for testing:"
echo "  systemctl start godo-tracker.service              # AS ncenter, no sudo"
echo
echo "Watchdog drop-in requires re-exec of PID 1 to apply:"
echo "  sudo systemctl daemon-reexec"
echo
echo "Verify:"
echo "  systemctl status godo-tracker"
echo "  journalctl -u godo-tracker -f"
echo "  cat /proc/irq/106/smp_affinity_list   # should be 0-2 (eth0)"
echo
echo "Verify polkit rule loaded (any user):"
echo "  sudo journalctl -u polkit -n 5 | grep 'rules'"
echo "  # Expected: 'Finished loading, compiling and executing 13 rules' (or similar)"
echo "  # The count is default rules + our 49-godo-systemctl.rules (one extra)."
echo
echo "Verify rule actually grants access (must run AFTER unit files installed):"
echo "  systemctl start godo-tracker.service     # AS ncenter — no sudo!"
echo "  # If polkit gate is open: systemctl returns 0 (or unit-specific error,"
echo "  # but NOT 'Interactive authentication required')."
echo "  # If denied: 'Failed to start godo-tracker.service: Interactive"
echo "  # authentication required.' → rule did not load or user not in"
echo "  # ncenter group."
echo
echo "Note: 'pkcheck --detail unit=...' for direct verification is BLOCKED by"
echo "polkit 126 security ('Only trusted callers can pass details') — only"
echo "root or the action owner can use it. Use the systemctl invocation above"
echo "as the runtime gate test, OR exercise the webctl admin endpoint via"
echo "the SPA System tab Start/Stop/Restart buttons."
