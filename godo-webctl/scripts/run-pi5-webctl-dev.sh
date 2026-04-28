#!/usr/bin/env bash
# run-pi5-webctl-dev.sh — launch godo-webctl in dev mode on news-pi01
# (or any Pi 5 dev box) without sudo.
#
# Per CLAUDE.md cross-platform hygiene rule: per-machine runtime config
# lives in scripts, never in source. This script sets the 7 GODO_WEBCTL_*
# env vars that route auth state under $HOME (avoiding /var/lib/godo
# permission errors), point maps_dir at the godo-mapping/ checkout, and
# expose 0.0.0.0:8080 so Tailscale + LAN browsers can reach the SPA.
#
# Usage:
#   bash godo-webctl/scripts/run-pi5-webctl-dev.sh [foreground|background]
#
# Default mode is `foreground` (Ctrl-C to stop). Pass `background` to
# detach via setsid + redirect to /tmp/godo-webctl.log; the PID is
# echoed and the script returns immediately.
#
# Stop a backgrounded webctl with:  pkill -9 -f godo_webctl
# Tail the log with:                tail -f /tmp/godo-webctl.log

set -euo pipefail

MODE="${1:-foreground}"

# Resolve the repo root from this script's location so the script works
# regardless of the operator's cwd. scripts/ is one level under godo-webctl/.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEBCTL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$WEBCTL_DIR/.." && pwd)"

MAPS_DIR="$REPO_ROOT/godo-mapping/maps"
MAP_PATH="$MAPS_DIR/studio_v2.pgm"
SPA_DIST="$REPO_ROOT/godo-frontend/dist"
AUTH_DIR="$HOME/.local/state/godo/auth"
JWT_SECRET="$AUTH_DIR/jwt_secret"
USERS_FILE="$AUTH_DIR/users.json"
LOG_FILE="/tmp/godo-webctl.log"

# Sanity-check paths the user is most likely to fat-finger.
if [[ ! -d "$MAPS_DIR" ]]; then
    echo "warn: maps_dir not found: $MAPS_DIR" >&2
fi
if [[ ! -d "$SPA_DIST" ]]; then
    echo "warn: spa_dist not found: $SPA_DIST" >&2
    echo "      run: (cd $REPO_ROOT/godo-frontend && npm run build)" >&2
fi

cd "$WEBCTL_DIR"

export GODO_WEBCTL_HOST=0.0.0.0
export GODO_WEBCTL_PORT=8080
export GODO_WEBCTL_MAPS_DIR="$MAPS_DIR"
export GODO_WEBCTL_MAP_PATH="$MAP_PATH"
export GODO_WEBCTL_SPA_DIST="$SPA_DIST"
export GODO_WEBCTL_JWT_SECRET_PATH="$JWT_SECRET"
export GODO_WEBCTL_USERS_FILE="$USERS_FILE"

case "$MODE" in
    foreground|fg)
        echo "godo-webctl dev: 0.0.0.0:8080 (foreground; Ctrl-C to stop)"
        echo "  maps_dir = $MAPS_DIR"
        echo "  map_path = $MAP_PATH"
        echo "  spa_dist = $SPA_DIST"
        echo "  auth_dir = $AUTH_DIR"
        exec uv run python -m godo_webctl
        ;;
    background|bg)
        # Reject if another webctl is already up — silent re-launch
        # would create two processes fighting for port 8080.
        if pgrep -f "python.* -m godo_webctl" >/dev/null; then
            echo "error: godo_webctl already running:" >&2
            pgrep -af "python.* -m godo_webctl" >&2
            echo "stop it first: pkill -9 -f godo_webctl" >&2
            exit 1
        fi
        setsid uv run python -m godo_webctl > "$LOG_FILE" 2>&1 < /dev/null &
        disown
        sleep 2
        if pgrep -f "python.* -m godo_webctl" >/dev/null; then
            echo "godo-webctl dev: started in background"
            echo "  PID(s): $(pgrep -f "python.* -m godo_webctl" | tr '\n' ' ')"
            echo "  log:    $LOG_FILE"
            echo "  stop:   pkill -9 -f godo_webctl"
        else
            echo "error: godo-webctl failed to start; check $LOG_FILE" >&2
            tail -20 "$LOG_FILE" >&2 || true
            exit 1
        fi
        ;;
    *)
        echo "usage: $0 [foreground|background]" >&2
        exit 2
        ;;
esac
