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
#   4. systemctl daemon-reload
#   5. (Does NOT enable the units — operator decides; instructions printed)

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

echo "[1/4] Installing /opt/godo-tracker/"
install -d -m 0755 -o root -g root /opt/godo-tracker
install -m 0755 -o root -g root "$BIN_SRC"                          /opt/godo-tracker/godo_tracker_rt
install -m 0755 -o root -g root "$SCRIPT_DIR/godo-irq-pin.sh"       /opt/godo-tracker/godo-irq-pin.sh

echo "[2/4] Installing systemd units to /etc/systemd/system/"
install -m 0644 "$SCRIPT_DIR/godo-irq-pin.service"  /etc/systemd/system/godo-irq-pin.service
install -m 0644 "$SCRIPT_DIR/godo-tracker.service"  /etc/systemd/system/godo-tracker.service

echo "[3/4] Installing watchdog drop-in"
install -d -m 0755 /etc/systemd/system.conf.d
install -m 0644 "$SCRIPT_DIR/system.conf.d/godo-watchdog.conf" \
                /etc/systemd/system.conf.d/godo-watchdog.conf

echo "[4/4] systemctl daemon-reload"
systemctl daemon-reload

echo
echo "Install complete. To enable + start:"
echo "  sudo systemctl enable --now godo-irq-pin.service"
echo "  sudo systemctl enable --now godo-tracker.service"
echo "  # webctl (if installed): sudo systemctl enable --now godo-webctl.service"
echo
echo "Watchdog drop-in requires re-exec of PID 1 to apply:"
echo "  sudo systemctl daemon-reexec"
echo
echo "Verify:"
echo "  systemctl status godo-tracker"
echo "  journalctl -u godo-tracker -f"
echo "  cat /proc/irq/106/smp_affinity_list   # should be 0-2 (eth0)"
