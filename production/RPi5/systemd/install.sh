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

echo "[1/12] Installing /opt/godo-tracker/"
install -d -m 0755 -o root -g root /opt/godo-tracker
install -d -m 0755 -o root -g root /opt/godo-tracker/share
install -m 0755 -o root -g root "$BIN_SRC"                          /opt/godo-tracker/godo_tracker_rt
install -m 0755 -o root -g root "$SCRIPT_DIR/godo-irq-pin.sh"       /opt/godo-tracker/godo-irq-pin.sh
# issue#16 — CP2102N unbind/rebind helper script. webctl invokes
# `systemctl start godo-cp210x-recover.service`; the unit's ExecStart
# runs this script after EnvironmentFile= pulls USB_PATH from
# /run/godo/cp210x-recover.env (which webctl writes atomically before
# the start verb).
install -m 0755 -o root -g root "$RPI5_DIR/share/godo-cp210x-recover.sh" \
                                /opt/godo-tracker/share/godo-cp210x-recover.sh
# Cross-language SSOT — webctl parses this header to render the SPA
# Config tab. /opt/godo-tracker/share/ is the production-side mirror
# of the dev tree's `production/RPi5/src/core/config_schema.hpp`.
# webctl points at it via GODO_WEBCTL_CONFIG_SCHEMA_PATH (set in
# /etc/godo/webctl.env). Re-running install.sh after a tracker rebuild
# refreshes both the binary AND the schema mirror.
install -m 0644 -o root -g root "$RPI5_DIR/src/core/config_schema.hpp" \
                                /opt/godo-tracker/share/config_schema.hpp

echo "[2/12] Installing systemd units to /etc/systemd/system/"
install -m 0644 "$SCRIPT_DIR/godo-irq-pin.service"  /etc/systemd/system/godo-irq-pin.service
install -m 0644 "$SCRIPT_DIR/godo-tracker.service"  /etc/systemd/system/godo-tracker.service
# issue#14 — mapping pipeline template unit. Operator never enables
# this; webctl drives `systemctl start godo-mapping@active.service`.
#
# issue#14 Maj-1 — sed-substitute the operator-tunable timing values
# from /var/lib/godo/tracker.toml's [webctl] section:
#   - webctl.mapping_docker_stop_grace_s   → ExecStop docker --time=<X>
#   - webctl.mapping_systemd_stop_timeout_s → TimeoutStopSec=<Y>s
# Defaults (20 / 30) match the as-checked-in unit file. If the operator
# bumps either key in the Config tab, re-running install.sh updates the
# .service file accordingly. The webctl-side ceiling
# (webctl.mapping_webctl_stop_timeout_s, default 35) is read at webctl
# startup directly from the TOML — no install-time substitution needed
# for that one.
GODO_MAPPING_DOCKER_GRACE_S=30
GODO_MAPPING_SYSTEMD_TIMEOUT_S=45
TRACKER_TOML=/var/lib/godo/tracker.toml

# issue#16.1 — pre-deploy gate. Live tracker.toml on news-pi01 may
# pin the legacy issue#14 Maj-1 default trio (20/30/35) which is
# both (a) below the new schema's lower bounds in spirit (we bumped
# defaults to 30/45/50 to fix t5 trap-timeout), and (b) missing the
# new mapping_systemctl_subprocess_timeout_s key (validator now
# requires it < webctl_stop_timeout). Without this gate, the next
# webctl boot would either crash-loop on the validator (`systemctl
# default 45 >= webctl 35`) or leave t5 unfixed because the unit
# file's sed-substituted ladder still says 20/30. The gate detects
# the legacy trio and auto-rewrites in place; non-default overrides
# trigger a refuse-with-instructions exit.
#
# Detection algorithm runs BEFORE the existing tomllib-parse block;
# rewrite is sed-based with exact anchors so partial matches are
# safe. Backup is timestamped per Mode-A round 2 minor #2 so re-runs
# do not clobber a prior backup.
#
# Bash dispatch on the Python-side single-token exit message:
#   LEGACY_TRIO_REWRITE   — auto-rewrite (Option α)
#   OVERRIDE_LADDER_REFUSE — refuse with instructions (Option β)
#   ALREADY_NEW           — operator already at new defaults; no-op
#   EMPTY_OK              — empty/sparse file; no-op
#   OVERRIDE_OK           — non-default override that still satisfies invariant; no-op
if [[ -e "$TRACKER_TOML" ]]; then
    # Step 1: detect the live state of the legacy trio + new key.
    GATE_VERDICT=$(python3 - <<'PYEOF' "$TRACKER_TOML" 2>/dev/null
import sys
import tomllib

path = sys.argv[1]
try:
    with open(path, "rb") as f:
        doc = tomllib.load(f)
except (OSError, tomllib.TOMLDecodeError):
    # Treat malformed as EMPTY_OK so the existing tomllib parse below
    # surfaces its own error message.
    print("EMPTY_OK")
    sys.exit(0)
section = doc.get("webctl", {})
docker = section.get("mapping_docker_stop_grace_s")
systemd = section.get("mapping_systemd_stop_timeout_s")
webctl = section.get("mapping_webctl_stop_timeout_s")
systemctl = section.get("mapping_systemctl_subprocess_timeout_s")
LEGACY = (20, 30, 35)
NEW = (30, 45, 50)
if (docker, systemd, webctl) == LEGACY and systemctl is None:
    print("LEGACY_TRIO_REWRITE")
elif systemctl is not None and not (
    isinstance(systemctl, int) and isinstance(webctl, int) and systemctl < webctl
):
    print("OVERRIDE_LADDER_REFUSE")
elif (docker, systemd, webctl) == NEW and systemctl == 45:
    print("ALREADY_NEW")
elif docker is None and systemd is None and webctl is None:
    print("EMPTY_OK")
else:
    eff_webctl = webctl if isinstance(webctl, int) else 50
    eff_systemctl = systemctl if isinstance(systemctl, int) else 45
    print("OVERRIDE_OK" if eff_systemctl < eff_webctl else "OVERRIDE_LADDER_REFUSE")
PYEOF
)
    case "$GATE_VERDICT" in
        LEGACY_TRIO_REWRITE)
            echo "  → issue#16.1 gate: live tracker.toml has legacy default trio (20/30/35); auto-rewriting to (30/45/50 + 45-systemctl)"
            BACKUP_PATH="${TRACKER_TOML}.bak.$(date +%s)"
            cp "$TRACKER_TOML" "$BACKUP_PATH"
            echo "    backup at ${BACKUP_PATH}"
            sed -i \
                -e 's/^mapping_docker_stop_grace_s = 20$/mapping_docker_stop_grace_s = 30/' \
                -e 's/^mapping_systemd_stop_timeout_s = 30$/mapping_systemd_stop_timeout_s = 45/' \
                -e 's/^mapping_webctl_stop_timeout_s = 35$/mapping_webctl_stop_timeout_s = 50/' \
                -e '/^mapping_webctl_stop_timeout_s = 50$/a mapping_systemctl_subprocess_timeout_s = 45' \
                "$TRACKER_TOML"
            ;;
        OVERRIDE_LADDER_REFUSE)
            echo "ERROR: install.sh: webctl.mapping_*_s ladder violates the cross-quartet invariant" >&2
            echo "       (docker_stop_grace_s < systemd_stop_timeout_s < webctl_stop_timeout_s" >&2
            echo "        AND systemctl_subprocess_timeout_s < webctl_stop_timeout_s)." >&2
            echo "" >&2
            echo "The new schema requires (defaults shown):" >&2
            echo "  webctl.mapping_docker_stop_grace_s             = 30 (or override, < systemd)" >&2
            echo "  webctl.mapping_systemd_stop_timeout_s          = 45 (or override, > docker, < webctl)" >&2
            echo "  webctl.mapping_systemctl_subprocess_timeout_s  = 45 (NEW issue#16.1, must be < webctl)" >&2
            echo "  webctl.mapping_webctl_stop_timeout_s           = 50 (or override)" >&2
            echo "" >&2
            echo "Manual action:" >&2
            echo "  sudo nano $TRACKER_TOML" >&2
            echo "  sudo bash production/RPi5/systemd/install.sh" >&2
            exit 1
            ;;
        ALREADY_NEW|EMPTY_OK|OVERRIDE_OK)
            : ;;  # no-op; existing parser block applies
        *)
            echo "  → issue#16.1 gate: unexpected verdict '$GATE_VERDICT'; falling through to defaults" >&2
            ;;
    esac
fi

# issue#14 Mode-B Mn1 fix (2026-05-02 KST) — use Python's stdlib tomllib
# instead of an awk parser. The previous awk path silently fell back to
# defaults on whitespace-noisy values (`= 25  ` with trailing spaces) or
# leading-space lines, which would silently drift the runtime away from
# the operator-set value. tomllib (Python 3.11+) is whitespace-resilient
# and ships with python3 on Trixie. The fallback semantics (missing key
# / missing file / parse error → keep default) are preserved by trapping
# every exception and printing diagnostic lines.
if [[ -e "$TRACKER_TOML" ]]; then
    parsed=$(python3 - <<PYEOF "$TRACKER_TOML" 2>&1 || true
import sys
import tomllib

def main(path: str) -> None:
    try:
        with open(path, "rb") as f:
            doc = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"WARN: install.sh: tracker.toml parse failed ({e}); using defaults", file=sys.stderr)
        return
    section = doc.get("webctl", {})
    docker = section.get("mapping_docker_stop_grace_s")
    systemd = section.get("mapping_systemd_stop_timeout_s")
    if isinstance(docker, int) and 1 <= docker <= 600:
        print(f"DOCKER={docker}")
    elif docker is not None:
        print(
            f"WARN: install.sh: mapping_docker_stop_grace_s value {docker!r} not int in range; using default",
            file=sys.stderr,
        )
    if isinstance(systemd, int) and 1 <= systemd <= 600:
        print(f"SYSTEMD={systemd}")
    elif systemd is not None:
        print(
            f"WARN: install.sh: mapping_systemd_stop_timeout_s value {systemd!r} not int in range; using default",
            file=sys.stderr,
        )

main(sys.argv[1])
PYEOF
)
    while IFS='=' read -r key val; do
        case "$key" in
            DOCKER)  GODO_MAPPING_DOCKER_GRACE_S="$val"      ;;
            SYSTEMD) GODO_MAPPING_SYSTEMD_TIMEOUT_S="$val"   ;;
            WARN*|*) [[ -n "$key" ]] && echo "  $key${val:+=$val}" >&2 ;;
        esac
    done <<< "$parsed"
fi
# Render the substituted unit to a temp file then `install` it. The sed
# uses `#` as the delimiter so it does not collide with the path slashes
# in the ExecStop line.
MAPPING_UNIT_TMP=$(mktemp /tmp/godo-mapping@.service.XXXXXX)
trap 'rm -f "$MAPPING_UNIT_TMP"' EXIT
sed \
    -e "s#docker stop --time=[0-9]\+ godo-mapping#docker stop --time=${GODO_MAPPING_DOCKER_GRACE_S} godo-mapping#g" \
    -e "s#^TimeoutStopSec=[0-9]\+s#TimeoutStopSec=${GODO_MAPPING_SYSTEMD_TIMEOUT_S}s#g" \
    "$SCRIPT_DIR/godo-mapping@.service" > "$MAPPING_UNIT_TMP"
install -m 0644 "$MAPPING_UNIT_TMP" /etc/systemd/system/godo-mapping@.service
echo "  godo-mapping unit timing: docker_stop_grace=${GODO_MAPPING_DOCKER_GRACE_S}s, TimeoutStopSec=${GODO_MAPPING_SYSTEMD_TIMEOUT_S}s (operator-tunable via Config tab → webctl.mapping_*)"
# issue#16 — CP2102N recovery oneshot unit. NOT enabled (operator
# never starts this directly); webctl is the sole caller via the SPA
# "🔧 LiDAR USB 복구" button.
install -m 0644 "$SCRIPT_DIR/godo-cp210x-recover.service" \
                /etc/systemd/system/godo-cp210x-recover.service

echo "[3/12] Installing watchdog drop-in"
install -d -m 0755 /etc/systemd/system.conf.d
install -m 0644 "$SCRIPT_DIR/system.conf.d/godo-watchdog.conf" \
                /etc/systemd/system.conf.d/godo-watchdog.conf

echo "[4/12] Installing polkit rule for ncenter-group systemctl + login1 access"
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

echo "[5/12] Installing udev rule for /dev/rplidar symlink (issue#10)"
# issue#10 — single-rule cp210x-by-serial → /dev/rplidar SYMLINK so
# the studio's RPLIDAR C1 has a stable device path independent of
# ttyUSB enumeration order. install + reload + trigger is idempotent;
# re-running the script after a kernel update or tracker rebuild is
# safe. Production tracker.toml's `serial.lidar_port` should read
# `/dev/rplidar` (new schema default); dev hosts without the studio's
# specific cp210x serial must override `[serial] lidar_port =
# /dev/ttyUSB0` in their tracker.toml.
install -m 0644 -o root -g root "$SCRIPT_DIR/99-rplidar.rules" \
                                /etc/udev/rules.d/99-rplidar.rules
udevadm control --reload-rules
# --subsystem-match=tty narrows the trigger so we do not replay `add`
# events for USB hubs / audio cards / etc. that the operator may have
# plugged in alongside the LiDAR.
udevadm trigger --action=add --subsystem-match=tty
echo "  → /etc/udev/rules.d/99-rplidar.rules installed; rules reloaded + tty add events triggered."
echo "  → Verify with: ls -l /dev/rplidar (must symlink to /dev/ttyUSB[01])"
echo "  → If missing: confirm LiDAR plugged in + check udevadm test \$(udevadm info -q path -n /dev/ttyUSB0) | grep SYMLINK"

echo "[6/12] Seeding /etc/godo/tracker.env (preserves existing real .env)"
install -d -m 0755 -o root -g root /etc/godo
if [[ ! -e /etc/godo/tracker.env ]]; then
    install -m 0644 -o root -g root "$SCRIPT_DIR/godo-tracker.env.example" /etc/godo/tracker.env
    echo "  → /etc/godo/tracker.env created from template (operator MUST review;"
    echo "    GODO_AMCL_MAP_PATH already points at /var/lib/godo/maps/active.pgm)"
else
    echo "  → /etc/godo/tracker.env already present; left untouched."
    echo "    Compare with $SCRIPT_DIR/godo-tracker.env.example for new keys."
fi

echo "[7/12] Seeding /var/lib/godo/tracker.toml (empty, ncenter-owned)"
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

echo "[8/12] Installing godo-mapping@.env.example reference (issue#14)"
# Documentation only — webctl writes the real envfile at runtime to
# /run/godo/mapping/active.env. This reference copy lives in /etc/godo
# so an operator inspecting the system can see the expected shape.
install -m 0644 -o root -g root "$SCRIPT_DIR/godo-mapping@.env.example" \
                                 /etc/godo/godo-mapping@.env.example

echo "[9/12] Ensuring /var/lib/godo/maps/.preview/ exists (issue#14 mapping previews)"
# Bind-mount target inside the container at /maps/.preview. webctl reads
# the PGM via realpath-contained `mapping.preview_path`. Belt-and-
# suspenders: the entrypoint also `mkdir -p /maps/.preview` at
# container-start.
install -d -m 0750 -o ncenter -g ncenter /var/lib/godo/maps/.preview

echo "[10/12] Ensuring docker group membership for ncenter (issue#14)"
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

echo "[11/12] systemctl daemon-reload"
systemctl daemon-reload

echo
echo "[12/12] Install complete. Auto-start policy (operator decision):"
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
