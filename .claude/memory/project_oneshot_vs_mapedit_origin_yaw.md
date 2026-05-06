---
name: OneShot calibrates (x, y) only; origin yaw is changed exclusively via MAP EDIT
description: Operator-locked invariant from 2026-05-07 KST briefing. OneShot calibration writes the new (x, y) base position to the origin offset but DOES NOT touch origin.yaw — that field is set or reset only by the SPA Map Editor's yaw rotation Apply (issue#28 / issue#30 lineage). The operator's standard workflow is "OneShot first, then Live Mode" (every session); origin.yaw is a calibration-time anchor, not a per-session value. Misunderstanding this drove documentation in issue#19 to suggest "OneShot Calibrate to silence the yaw tripwire" — that suggestion is incorrect. Locked 2026-05-07 KST during issue#19 HIL on news-pi01.
type: project
---

## The semantic split

| Operation | Affects `origin.x, origin.y` | Affects `origin.yaw` |
|---|---|---|
| OneShot calibrate (Control tab button OR `/api/calibrate`) | ✅ writes new value | ❌ untouched |
| Live tracking (10 Hz) | ❌ untouched (live pose only) | ❌ untouched |
| **MAP EDIT yaw rotation Apply** (Map Editor SPA) | (depends on operator's edit semantic) | ✅ writes new value |

Source-of-truth code path:

- OneShot writes `origin_x_m`, `origin_y_m` to the calibration record; `origin_yaw_deg` is left at whatever MAP EDIT last set it (default 0° for a fresh map). See `production/RPi5/src/localization/cold_writer.cpp` (OneShot path) — origin yaw is read from config, not written by the calibrate path.
- MAP EDIT yaw rotation (issue#28 + issue#30 lineage) writes the new `origin_yaw_deg` into the YAML next to the .pgm; that file is the SSOT for origin yaw across calibration sessions.

## Standard operator workflow (load-bearing)

Per the 2026-05-07 briefing:

1. (Whenever needed: MAP EDIT to update origin.yaw if studio coordinate frame conventions changed.)
2. **OneShot calibrate** — fixes (x, y) drift after a base move.
3. **Live Mode on** — runs continuously with cold-path AMCL update + 60 Hz hot-path UDP send.

The operator does step 2 every session as a matter of routine, even when the base has not visibly moved, because OneShot is cheap (a few seconds) and re-anchors (x, y) to studio millimetre-level accuracy. Step 1 is rare; once the studio frame is set, MAP EDIT is left alone.

## What this rule rules out

- ❌ "Run OneShot to silence the yaw tripwire" — wrong. OneShot does not change `origin.yaw`, so the tripwire (which compares live `pose.yaw` against `origin.yaw`) is unaffected.
- ❌ "Set origin.yaw via TOML" — there is no Tier-2 TOML key for `origin.yaw`. It lives in the map YAML next to the .pgm.
- ❌ "OneShot resets the calibration to fresh state" — partially correct (x, y is fresh) but yaw is preserved across OneShots within the same map.

## Cross-link to other memories

- `project_pick_anchored_yaw_normalization_locked.md` — issue#30 SSOT for the rotation semantic in MAP EDIT.
- `project_yaw_tripwire_design_flaw.md` — the tripwire that misleadingly suggests calibration; flagged for `issue#36` removal.
- `project_amcl_yaw_metadata_only.md` — AMCL's role: yaw is metadata-only inside AMCL, not part of state.

## Forensic anchor

Documentation drift caught during issue#19 HIL on news-pi01 2026-05-07 KST. Plan and PR body had suggested "OneShot Calibrate to silence the yaw tripwire" as a noise-reduction measure for the 5-minute Phase-0 capture. Operator clarified on the spot: "OneShot does not change origin yaw; MAP EDIT does." This memory locks the distinction so future plans / Mode-A reviews catch the misconception before propagation.
