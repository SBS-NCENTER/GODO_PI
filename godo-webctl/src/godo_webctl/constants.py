"""
Webctl-internal Tier-1 constants.

Scope: values that are NOT on the wire to the C++ tracker. The wire SSOT
lives in ``protocol.py``; that file is a deliberate one-to-one mirror of
production/RPi5/src/core/constants.hpp + uds_server.cpp + json_mini.cpp
and must stay free of webctl-only knobs.

Anything pinned here is a **deliberate** choice; tests in
``tests/test_constants.py`` pin every value so changes require a visible
diff. CLAUDE.md §6 forbids magic numbers in ``src/`` — every literal in
``src/godo_webctl/`` that is not a local iteration bound or a wire-side
mirror MUST resolve to a constant declared here or a Settings field in
``config.py``.

Leaf module: imports nothing from the package.
"""

from __future__ import annotations

import re
from typing import Final

# --- JWT / auth -----------------------------------------------------------
# HS256 keeps the secret + verify operations inside the FastAPI process —
# no public-key infrastructure needed for a 1-2 user studio host.
JWT_ALGORITHM: Final[str] = "HS256"

# 6 h session window. Long enough that an operator who logs in at the
# start of a recording day does not get bounced; short enough that a
# stolen token has a bounded blast radius.
JWT_TTL_SECONDS: Final[int] = 21600  # 6 h

# bcrypt cost factor. ~300 ms per login on RPi 5 Cortex-A76 — deliberate
# friction against credential-stuffing on a LAN-exposed host. Do NOT
# lower without revisiting the threat model; at 1-2 users / ~1 login per
# day cadence the latency is invisible.
BCRYPT_COST_FACTOR: Final[int] = 12

# --- SSE cadence ----------------------------------------------------------
# Last-pose stream tick: 5 Hz matches the cold-writer publish cadence
# (no benefit polling faster than the tracker updates the seqlock).
SSE_TICK_S: Final[float] = 0.2  # 5 Hz

# Services stream tick: 1 Hz is plenty for systemctl status — service
# state transitions are operator-driven, not high-frequency events.
SSE_SERVICES_TICK_S: Final[float] = 1.0

# Keepalive comment line interval. 15 s is well under typical 60 s
# proxy/browser idle timeouts and short enough that a cold reverse-proxy
# does not buffer past the first frame.
SSE_HEARTBEAT_S: Final[float] = 15.0

# --- Map image cache ------------------------------------------------------
# PGM → PNG conversion takes ~200 ms for a 1024×1024 map. Cache for 5 min
# so back-to-back B-MAP page loads are O(1). Invalidation is mtime-keyed
# (see map_image.render_pgm_to_png).
MAP_IMAGE_CACHE_TTL_S: Final[float] = 300.0

# --- Activity log ---------------------------------------------------------
# In-process ring buffer size. Last 50 actions covers a typical recording
# session; older entries fall off silently. Process restart wipes the
# buffer (documented in CODEBASE.md invariant — in-memory only for P0).
ACTIVITY_BUFFER_SIZE: Final[int] = 50

# Default `n` for /api/activity?n=… when the operator does not specify.
# 5 matches the DASH "last 5 activities" line (FRONT_DESIGN §7.1).
ACTIVITY_TAIL_DEFAULT_N: Final[int] = 5

# --- Journalctl tail ------------------------------------------------------
# Default `n` for /api/local/journal/<svc>?n=… when the operator does not
# specify. 30 lines covers most "what just went wrong" debugging without
# blowing up the response size.
JOURNAL_TAIL_DEFAULT_N: Final[int] = 30

# --- LoginBody field bounds ----------------------------------------------
# Wire-side bounds on /api/auth/login payload. 64 covers the existing
# `ncenter` seed plus any reasonable LDAP migration; 256 leaves headroom
# above bcrypt's 72-byte input limit (longer passwords are silently
# truncated by bcrypt, but we accept them client-side).
LOGIN_USERNAME_MAX_LEN: Final[int] = 64
LOGIN_PASSWORD_MAX_LEN: Final[int] = 256

# --- SSE per-poll UDS timeout --------------------------------------------
# Short — if the tracker stalls, we want the loop to skip a frame, not
# stall the stream. 0.5 s is well under the 1 s services tick and the
# 0.2 s last_pose tick (the latter falls back to skip-on-timeout cleanly
# because the next tick re-queries).
SSE_UDS_TIMEOUT_S: Final[float] = 0.5

# --- Backup-side Tier-1 (relocated from protocol.py per planner M2) ------
# Bound on rename collision retries inside backup.backup_map. Above 9
# means more than 9 backups in the same UTC second, which never happens
# in practice. Lives here because it is webctl-internal — the tracker
# has no opinion on how webctl manages its backup directory.
MAX_RENAME_ATTEMPTS: Final[int] = 9

# --- Multi-map management (Track E, PR-C) --------------------------------
# Map name validator. ASCII only, case-sensitive, no dots / slashes /
# whitespace. `.pgm` and `.yaml` extensions are appended by the caller —
# names are stems. The reserved name `"active"` passes this regex (so a
# router-level mismatch cannot dodge it) and is rejected separately by
# the public maps.py functions to keep the active-symlink names from
# colliding with a regular map.
MAPS_NAME_MAX_LEN: Final[int] = 64
MAPS_NAME_REGEX: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9_-]{1,64}$",
)

# Reserved basename used for the active-pair symlink pair
# (`active.pgm` + `active.yaml`). Operators cannot upload a regular map
# with this name — `set_active`/`delete_pair` reject it before any FS op.
MAPS_ACTIVE_BASENAME: Final[str] = "active"

# Advisory `flock(LOCK_EX)` target inside `cfg.maps_dir`. The leading dot
# keeps it out of `list_pairs` (which only enumerates `<stem>.pgm` +
# `<stem>.yaml` pairs).
MAPS_ACTIVATE_LOCK_BASENAME: Final[str] = ".activate.lock"
