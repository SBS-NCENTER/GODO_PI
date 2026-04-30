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
#   6. systemctl daemon-reload
#   7. (Does NOT enable the units — operator decides; instructions printed)
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

echo "[1/6] Installing /opt/godo-tracker/"
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

echo "[2/6] Installing systemd units to /etc/systemd/system/"
install -m 0644 "$SCRIPT_DIR/godo-irq-pin.service"  /etc/systemd/system/godo-irq-pin.service
install -m 0644 "$SCRIPT_DIR/godo-tracker.service"  /etc/systemd/system/godo-tracker.service

echo "[3/6] Installing watchdog drop-in"
install -d -m 0755 /etc/systemd/system.conf.d
install -m 0644 "$SCRIPT_DIR/system.conf.d/godo-watchdog.conf" \
                /etc/systemd/system.conf.d/godo-watchdog.conf

echo "[4/6] Installing polkit rule for ncenter-group systemctl + login1 access"
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

echo "[5/6] Seeding /etc/godo/tracker.env (preserves existing real .env)"
install -d -m 0755 -o root -g root /etc/godo
if [[ ! -e /etc/godo/tracker.env ]]; then
    install -m 0644 -o root -g root "$SCRIPT_DIR/godo-tracker.env.example" /etc/godo/tracker.env
    echo "  → /etc/godo/tracker.env created from template (operator MUST review;"
    echo "    GODO_AMCL_MAP_PATH already points at /var/lib/godo/maps/active.pgm)"
else
    echo "  → /etc/godo/tracker.env already present; left untouched."
    echo "    Compare with $SCRIPT_DIR/godo-tracker.env.example for new keys."
fi

echo "[6/6] systemctl daemon-reload"
systemctl daemon-reload

echo
echo "Install complete. Auto-start policy (operator decision):"
echo "  - godo-irq-pin.service    AUTO    (IRQ pinning, oneshot, no runtime risk)"
echo "  - godo-webctl.service     AUTO    (operator UI; must reach at boot)"
echo "  - godo-tracker.service    MANUAL  (start via SPA System tab Start button)"
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
