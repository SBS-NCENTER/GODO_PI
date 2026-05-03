---
name: Relaxed validator + strict installer — single-point-of-strict design pattern
description: When schema-driven config lands in tracker.toml AND gets consumed by an installer/deploy step, keep the schema validator generic (non-empty + type) and put format-specific strict checks at the SOLE consumer (e.g., install.sh). Operator can Apply a wrong value; consumer refuses-with-instructions while preserving prior valid state.
type: feedback
---

Locked 2026-05-03 KST during issue#10.1 design (PR #73). The `serial.lidar_udev_serial` schema row is a string accepting any non-empty ASCII printable up to 256 chars in tracker C++ Config validation. The cp210x USB serial format (32 lowercase hex `^[0-9a-f]{32}$`) is enforced ONLY at install.sh time, where the value gets sed-substituted into `/etc/udev/rules.d/99-rplidar.rules`. Bad input flow:

1. Operator types `"abc"` in Config tab → Apply succeeds (relaxed validator).
2. tracker.toml stores `[serial] lidar_udev_serial = "abc"`.
3. Operator runs `sudo bash install.sh`.
4. `[5/12]` step format-checks → fails → `ERROR: ... Got: 'abc' Expected: 32 lowercase hex characters` + numbered manual recovery steps + `exit 1`.
5. **Existing `/etc/udev/rules.d/99-rplidar.rules` left untouched** (operator's prior valid serial still active).
6. Operator restores correct value via Config tab → re-runs install.sh → udev rule regenerates.

**Why this beats "strict everywhere"**:

- **Debugger-friendly**: when format check fails, the error message says exactly which row + which format. If schema-side validator rejected the same input, operator would see a 400-ish error from the Config Apply API which is harder to localize.
- **Operator-flow-friendly**: operator can stage values in Config tab without yet running install.sh (e.g., before a planned LiDAR swap). The relaxed validator preserves the staged value as-is.
- **Single point of failure**: ONE format-check site means ONE place to maintain the regex / validation rules. Strict-everywhere requires keeping multiple sites in sync.
- **Existing-state preservation**: install.sh's refuse-with-instructions doesn't touch the live udev file. Operator's prior good state survives the bad-input attempt — no recovery cascade needed.

**Why this is NOT general advice**:

- Use this pattern only when the field has a SOLE consumer (install.sh is the only place reading the value). If multiple consumers exist (e.g., webctl AND tracker AND install.sh all read the field), strict-at-each is required to prevent inconsistency.
- The relaxed-side validator MUST still enforce the type and basic constraints (string non-empty, ≤256 chars) — relaxed ≠ unchecked. Without these, malformed inputs (e.g., empty string, 1 GB blob) still hit the consumer.

**How to apply** (when designing a new schema row that crosses the SPA → tracker.toml → installer/consumer path):

1. **Choose schema-side validator** based on type only: `String` → non-empty + ASCII printable + ≤256 chars (from `validate.cpp` String validator); `Int` → range [min, max]; `Double` → range + finite. NO format-specific regex at schema level.
2. **Move format check to consumer**: install.sh's `[N/M]` step (or whatever the consumer is — could also be a `webctl` startup hook) format-checks before USING the value.
3. **Refuse-with-instructions on bad format**: error message shows the offending key name + value + expected format + numbered manual recovery steps. Mirror existing `OVERRIDE_LADDER_REFUSE` (install.sh) or `WebctlTomlError` (webctl_toml.py) patterns.
4. **Preserve prior valid state**: do NOT delete or rewrite the consumer's output (`/etc/udev/rules.d/...`, generated unit file, etc.) until format check passes. Bad input attempt → no-op + clear error.
5. **HIL test plan MUST include negative path**: `Apply succeeds with bad value → installer refuses → existing state intact → restore good value → retry succeeds`. PR #73 used this exact test plan; verified all four steps green.

**Existing applications in GODO**:

- `serial.lidar_udev_serial` (issue#10.1, PR #73) — schema String relaxed; install.sh strict 32-hex.
- `webctl.mapping_systemctl_subprocess_timeout_s` (issue#16.1, PR #72) — schema Int [10, 90]; webctl runtime enforces ladder pairwise relations only when the row changes (not in install.sh — different pattern, single consumer is the webctl coordinator).

**Future candidates** (rows where this pattern fits):

- IP / port fields with format-specific validation (e.g., `network.ue_host` could go relaxed-validator + boot-time strict-check at tracker startup).
- Path fields where install.sh templates the value into a unit file or config (similar to `lidar_udev_serial` flow).

**When NOT to use**:

- Multi-consumer fields (validator must be authoritative everywhere — drift is unsafe).
- Hot-path fields where bad values cause immediate runtime failure (better to reject early at schema apply).
- Fields where the "prior valid state" doesn't exist as a recoverable artifact (then bad input is genuinely destructive).

Reference: PR #73 plan §3.1 + §7-R1 risk + §8 HIL Definition of Done.
