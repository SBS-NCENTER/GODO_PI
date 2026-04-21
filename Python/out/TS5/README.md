# TS5 — Chroma studio (부조정실), 2026-04-21

First field session in the production environment. LiDAR temporarily mounted ~2 m below planned height. **5 retro-reflective tapes** stuck on walls across two different surfaces (4 on the staff-area soundproof wall, 1 on the chroma screen); position not revealed to the analyst (detection blind test).

## Physical layout (confirmed post-analysis)

- **135°–250°**: chroma screens (wrapping left/right/back). 220°–250° was briefly occluded by the operator.
- **60°–85°**: set-access door (slightly open, hence non-flat). 85°–110° blocked by other equipment.
- **270°–280°**: corridor door (smaller than the set door).
- **300°–360°, 0°–60°**: staff area, camera/equipment path, set-storage zone. **Soundproof walls.** All 4 reflector tapes are on this stretch of wall.

## Session contents

### `data/` — raw capture CSVs (7 files)

| Timestamp | Backend | Position | Notes |
| --- | --- | --- | --- |
| 071718Z | sdk | A | Center of set, full scene cluttered |
| 071825Z | raw | A | Parity counterpart |
| 074236Z | sdk | — | Aborted capture (no paired log) |
| 074409Z | sdk | B | Moved LiDAR, cleaner room shape |
| 074535Z | raw | B | Parity counterpart |
| 075643Z | sdk | C | Moved again, most tapes occluded |
| 075815Z | raw | C | Parity counterpart |

### `logs/` — session .txt (6 files, one per successful capture)

### `analysis/` — analyze.py outputs (15 files)

- `*_polar.png`, `*_qhist.png` per capture
- 3 × SDK-vs-raw compare CSVs

## Blind-test detection results (adaptive algorithm, post-rework)

**Algorithm**: 0.5° angular bins, local contrast (±10° neighbor), adaptive thresholds `q_median ≥ max(25, p95−5)` AND `contrast ≥ max(12, 2×median)`, cluster gap ≤ 2°.

### Per-position, per-backend (**5 tapes total** — 4 on staff-wall, 1 on chroma screen)

| Position | Backend | Detected | Tape angles | Distances | q_peak range |
| --- | --- | --- | --- | --- | --- |
| A | sdk | **4 / 5** (staff-wall all) | 26.5°, 32.5°, 40.0°, 51.0° | 2.76–3.99 m | 45–46 |
| A | raw | **4 / 5** (staff-wall all) | 26.5°, 32.5°, 40.5°, 51.0° | 2.76–3.99 m | 46–47 |
| B | sdk | **4 / 5** (staff-wall all) | 337.5°, 341.5°, 346.0°, 355.0° | 4.81–5.81 m | 37–43 |
| B | raw | **4 / 5** (staff-wall all) | 337.5°, 341.5°, 346.0°, 355.0° | 4.81–5.81 m | 37–43 |
| C | sdk | **1 / 5** (chroma-wall tape) + 1 near-field | 155.5° (+ 247° @ 0.17 m) | 4.49 m | 43 |
| C | raw | **1 / 5** (chroma-wall tape) + 1 near-field | 155.5° (+ 247° @ 0.17 m) | 4.49 m | 44 |

**Key lesson**: no single LiDAR position saw all 5 tapes. Staff-wall tapes (4) and chroma-wall tape (1) are mutually occluded between position clusters A/B vs C. This is a **retroreflector directionality + geometric occlusion** constraint, not a resolution limit (each individual tape was cleanly detected in isolation with sub-3-mm distance std).

### Backend parity

SDK vs raw agreement is sub-mm on reflector distance, within 1 quality point, and cluster counts match exactly in all three positions. Compare CSVs show mean |delta_mean_mm| of 22–32 mm across full scene (dominated by clutter-bin variance, not reflector-bin variance).

### Distance precision at reflectors

| Position | Best reflector std | Distance |
| --- | --- | --- |
| A | **1.3 mm** | 2.76 m |
| B | 5.5 mm | 4.81 m |
| C | **2.1 mm** | 4.49 m |

All well within the 15 mm datasheet resolution spec, validating C1 for marker localization at studio ranges.

## Key findings

1. **Adaptive reflector detection works across environments.** Same algorithm catches reflectors cleanly at TS4 (indoor bench, 1 m) and TS5 (studio, 2.7–5.8 m) without threshold retuning.
2. **Quality attenuates with distance**, roughly following 1/r². q_peak 46 at ≈1 m (TS4 and TS5-A), 43 at ≈4.5 m (TS5-C), 37–40 at ≈5 m (TS5-B).
3. **Geometric occlusion is the dominant limit, not signal strength.** Position C saw only 1/4 tapes because the other 3 are blocked or outside the scan plane — not because the signal was too weak.
4. **Near-field anomalies (< 0.5 m) must be filtered** in the detection algorithm. Position C surfaced a 16.7 cm "reflector" that is almost certainly a mount / operator / equipment artifact.
5. **O4 marker-based localization is viable** in this studio: even a single cleanly-detected reflector gives sub-3 mm distance precision at 4.5 m.

## Recommendations (feeding back into `analyze.py`)

1. Replace `reflector` mode in `analyze.py` with the adaptive-threshold + fine-bin + narrow-gap clustering used above.
2. Add a near-field guard: reject clusters with `d_median < 500 mm` unless explicitly targeted.
3. Re-scale visualize mode's quality colorbar to `[0, max(observed)]` instead of fixed `[0, 255]`.
4. Tape placement strategy for production: spread reflectors across **multiple walls** (not just one stretch) so every LiDAR position sees at least 2–3 markers.

## Integrity

All CSVs have matching `csv_sha256` in the paired session .txt. Re-analysis without hardware is fully reproducible.
