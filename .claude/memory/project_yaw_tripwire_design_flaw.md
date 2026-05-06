---
name: cold_writer yaw tripwire fires spuriously because LiDAR yaw follows pan rotation by physical invariant
description: The yaw tripwire in cold_writer.cpp ("Studio base may have rotated; re-run calibration when convenient") was designed under the assumption that the crane BASE could rotate, but operator-locked physical invariant (CLAUDE.md §9) is that the BASE does not rotate; only the LiDAR rotates because it sits on the crane's pan-axis center. The pan rotation continuously drives LiDAR yaw, so tripwire fires every Live tick whenever yaw deviates from origin by more than ~2°. Real-world impact: stderr spam (e.g., 2994 events / 5 minutes during issue#19 HIL on news-pi01 2026-05-07 KST) burying useful diagnostic lines and adding fprintf wake-up overhead to the cold path. Tripwire is a flawed feature; deactivate or raise threshold to >= 90° (or eliminate entirely).
type: project
---

## Why the tripwire was added (historical reasoning)

The tripwire in `production/RPi5/src/localization/cold_writer.cpp` (search for `"yaw tripwire fired"`) compares the live `pose.yaw` against `origin.yaw` and fires whenever the absolute difference exceeds 5° (default). The intent at design time was: "if the crane base ever rotates physically (someone turns the studio base by hand, kicks a wheel, etc.), the operator should be told to re-run calibration so the FreeD origin offset can be re-established."

## Why the tripwire fires spuriously in normal operation

Operator-locked physical invariants (CLAUDE.md §2 + §9):

1. **The crane BASE does NOT rotate** — dolly wheels are always parallel; physical base rotation is impractical in studio operation. ✅ The scenario the tripwire was guarding against essentially never happens.
2. **The LiDAR is mounted at the pan-axis center** — so LiDAR (x, y) is invariant under pan rotation, but **LiDAR yaw follows the pan rotation 1:1**. Every time the operator pans the crane (which happens every shot), LiDAR yaw moves through tens of degrees.

Therefore: in normal operation, `pose.yaw - origin.yaw` is dominated by the camera operator's pan motion, NOT base rotation. The tripwire fires every Live tick where the camera is panned more than ~2° from where it was at OneShot time. Empirically observed at news-pi01 2026-05-07 KST during issue#19 HIL: yaw=83° vs origin.yaw=0° → tripwire fires every Live tick (2994 events in 5 minutes capture window).

## Why this matters

- **stderr spam**: ~10 fprintf/s during Live mode buries `[phase0]` / `PHASE0` / `[pool-degraded]` and any other operator-actionable diag. journalctl filtering still works but reading the raw stream is impossible.
- **Cold-path overhead**: `fprintf(stderr, …)` is buffered but the line-formatting + journald socket write add measurable wake-up overhead per scan. Suspected (but not proven) noise contributor in issue#19's measured 1.43× LF speedup vs the plan's projected 3× (production observation matched dev-box ctest 1.4–1.5×, suggesting the ceiling is real but the tripwire I/O likely amplifies it slightly).
- **Operator alert fatigue**: a tripwire that always fires teaches the operator to ignore it, defeating the purpose for the rare case the BASE actually moves.

## Operator workflow distinction (load-bearing)

OneShot calibration sets the (x, y) origin offset; it does **NOT** reset `origin.yaw` to the current LiDAR yaw. Operator's standard sequence is:

1. **OneShot calibrate** (re-aligns x, y after base move; yaw left untouched at the value it had when MAP EDIT last set it).
2. **Live mode on** — Live tracking runs continuously; yaw varies with pan motion.

`origin.yaw` is set/reset only by **MAP EDIT** (yaw rotation in the SPA Map Editor); it is the calibration-time anchor for FreeD's coordinate frame, not a per-session value. So the tripwire's "re-run calibration" message is itself misleading — running OneShot would not silence the tripwire.

## Resolution path

`issue#36` is reserved for this work. Three options to evaluate:

1. **Eliminate the tripwire entirely** (cleanest) — the BASE-rotation scenario is so rare and so visible (the operator notices when a crane base shifts) that an automated tripwire adds noise without value.
2. **Raise threshold to ≥ 90°** — only fire if yaw difference is so large it could not plausibly be pan motion. Likely never fires, but the dead code stays.
3. **Make the tripwire latch + rate-limit** — fire once per session per N° threshold, then suppress until restart or origin update. Adds complexity for a feature that may not be useful.

Operator preference (per 2026-05-07 KST briefing): leaning toward option 1 (eliminate). issue#36 plan should validate this preference before code change.

## Forensic anchor

issue#19 HIL on news-pi01 2026-05-07 KST: 5-minute Live-mode capture produced 2994 yaw tripwire events alongside ~3000 PHASE0 lines. Tripwire spam was the immediate symptom that surfaced this design flaw — operator clarification ("LiDAR yaw varies with pan; tripwire is wrong") locked the resolution path on the spot.
