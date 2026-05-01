---
name: production tracker.toml ↔ branch Config struct compatibility
description: PGM tracker.toml is a strict-schema TOML — unknown keys are a fatal load error (`unknown TOML key`, exit 2). When deploying any branch whose `Config` struct does NOT contain a key already present in `/var/lib/godo/tracker.toml`, the tracker enters a systemd auto-restart loop. Surfaced 2026-05-01 KST during PR #56 (frame fix) HIL — toml carried PR #54's `amcl.hint_sigma_*_default` keys from earlier PATCH probing, but PR #56's main-based binary did not yet know them. Pre-deploy hygiene rule below.
type: feedback
---

## What happened

During issue#3 σ sweep, operator PATCHed `amcl.hint_sigma_xy_m_default` and `amcl.hint_sigma_yaw_deg_default` via the SPA Config tab — these went into `/var/lib/godo/tracker.toml` (PR #55's RW path). When PR #56 (frame fix) was deployed shortly after, its tracker binary was built from `main` (which had been merged with PR #55 but NOT PR #54), so its in-tree `Config` struct did not contain those two keys. Cold start hit `Config::load`, parsed the TOML, found the unknown key, threw, exit code 2/INVALIDARGUMENT, systemd auto-restarted, looped infinitely.

Operator observed via SPA: `godo-tracker: activating (auto-restart)` — not a transient hiccup but a deterministic load failure.

## Why the unknown-key fail-fast exists

Strict TOML schema is a deliberate Tier-2 invariant: unknown keys frequently mean operator typos, drift, or stale TOML carrying values from a different code branch. Silent acceptance would hide misconfiguration; loud rejection forces alignment between code and runtime config. The rule is correct — the problem is the deploy procedure was missing a compatibility check.

## Pre-deploy hygiene rule

Before deploying a branch on news-pi01, **align the runtime TOML with the branch's known-keys set**:

1. Inspect `/var/lib/godo/tracker.toml` for any key the branch's `Config` struct does not declare:
   ```bash
   # Quick check — runs the tracker dry to surface the unknown-key list.
   /opt/godo-tracker/godo_tracker_rt --help 2>&1 | grep -i toml
   # Or directly: tail the journal after a single restart attempt.
   sudo systemctl restart godo-tracker
   sudo journalctl -u godo-tracker -n 5 --no-pager | grep "unknown TOML key"
   ```
2. If unknown keys are reported, options:
   - Strip them from the runtime TOML: `sudo sed -i '/^<key_name>/d' /var/lib/godo/tracker.toml`
   - Or stage the deploy: rebase / merge the missing branch first so the keys become recognised.
3. Restart `godo-tracker` and confirm `Active: active (running)` plus `journalctl ... | grep "unknown TOML key"` returns nothing.

## Why operator-applied PATCHes are at higher risk

The webctl-driven PATCH path writes to TOML on success. If the operator uses the SPA Config tab to set a Tier-2 key on branch X, then later deploys branch Y which lacks that key in its `Config` struct, branch Y's tracker fails to start. The TOML becomes a "branch lock-in" artifact unless explicitly cleaned.

This is most likely to bite when:
- A branch is open for HIL on the production host (operator probes via SPA → keys land in TOML).
- A different branch is deployed for parallel experimentation (e.g., PR #56 frame fix while PR #54 still open).

## Mitigation candidates (future PRs)

- **Schema migration**: when `Config::load` encounters an unknown key, downgrade the failure to a WARNING + skip-the-key, but ONLY if the key prefix matches a known-allowlist of Tier-2-experimental namespaces (e.g., `amcl.experimental.*`). Strict rejection elsewhere preserved.
- **Deploy script**: a `production/RPi5/scripts/predeploy-check.sh` that diff's `tracker.toml` keys against the branch's `config_schema.hpp` and emits a warning before `systemctl restart`.
- **CODEBASE.md cross-stack invariant**: pin the TOML-vs-Config compatibility expectation explicitly so future writers understand the cross-cutting risk.

## How to apply

Whenever the operator (or a remote agent on news-pi01) is about to:
- Deploy a freshly-built tracker binary, AND
- The branch was NOT continuously deployed during the operator's recent SPA Config-tab activity,

run the pre-deploy hygiene check above. The cost is 5 seconds; the cost of skipping is a tracker auto-restart loop and an HIL session blocked until diagnosis.

## Status

- Incident date: 2026-05-01 KST during PR #56 HIL.
- Resolution applied: stripped `hint_sigma_*` keys from production TOML; tracker green.
- This memory is the lesson; mitigation candidates above are future work.
