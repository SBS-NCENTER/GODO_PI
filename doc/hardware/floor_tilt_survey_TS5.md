# Floor Tilt Survey — TS5 (부조정실 / chroma studio)

> **Purpose**: empirically characterize the chroma studio floor tilt across the
> crane's movable area so the leveling mount decision
> (see [`leveling_mount.md`](./leveling_mount.md)) can be made from measured
> data, not estimates.
>
> **Status**: methodology frozen; **field measurement pending TS5 session**.
> All sections marked `TODO (TS5 session)` are blank placeholders to be filled
> by the session crew and committed post-session.
>
> **Phase**: Phase 1 (Data normalization).
> **Blocks**: mount selection (P1-9.2), Phase 2 mapping start.

---

## 0. Why this survey exists

AMCL converts a LiDAR-plane residual into a position residual. If the LiDAR
plane is tilted by angle `θ` with respect to the world horizontal, then at
range `R` the intersection with a vertical wall shifts by
`Δ ≈ R · sin(θ) ≈ R · θ` (small-angle). For a wall at `R_max = 10 m` and an
end-to-end error budget of `ε_target = 10 mm`, the allowable tilt is
`θ ≤ ε_target / R_max ≈ 0.001 rad ≈ 0.057°`.

A tilt larger than that cannot be corrected by software at our accuracy target
(1–2 cm). It must be absorbed by the mount.

This survey determines which mount tier is needed (see
[`leveling_mount.md` §1](./leveling_mount.md#1-threshold-rationale)).

---

## 1. Instruments

### 1.1 Primary: Digi-Pas DWL2000XY (2-axis digital inclinometer)

- Form factor: dual-axis electronic inclinometer with magnetic base.
- Claimed resolution: `0.01°` (1-axis) / `0.05°` range — **datasheet value to
  re-verify against the actual unit's spec sheet when the instrument is
  procured**. Record the verified SKU, firmware, and resolution into the
  `## Instrument log` block below before fieldwork.
- Claimed repeatability: `±0.05°` over the operating range.
- Zero-reference: a calibrated flat granite plate or a factory-calibrated
  reference surface is used as the "true horizontal" anchor for the drift
  gate (see §3.3).
- **Amendment N5**: if the procured unit's datasheet-resolution exceeds
  `0.02°`, recompute the drift gate (§3.3) and the rejection threshold (§3.2)
  upward by the same factor and document it in this file before measuring.

### 1.2 Fallback: dual bubble level + photo log

- Used only if DWL2000XY is unavailable on the TS5 date.
- 2-axis machinist's bubble level with `0.02°/division` graduation,
  photographed with a fixed-focal-length camera on a tripod at each grid
  point.
- Drift gate and rejection thresholds are not applicable in the same form —
  if the fallback is used, downgrade the survey confidence from "quantitative"
  to "semi-quantitative" and flag in §5.

### 1.3 Instrument log

| Field | Value |
| --- | --- |
| Procured SKU | **TODO (TS5 session)** |
| Firmware / revision | **TODO (TS5 session)** |
| Datasheet resolution (axis) | **TODO (TS5 session)** |
| Datasheet repeatability | **TODO (TS5 session)** |
| Zero-reference used | **TODO (TS5 session)** — granite plate / factory reference |
| Last calibration date (vendor) | **TODO (TS5 session)** |

---

## 2. Grid design (hybrid 0.25 m dense / 0.5 m coarse)

### 2.1 Coverage

The measurement area is the **crane's movable area** as defined in
`PROGRESS.md §Decisions` — staff space + between the two studio doors.
The chroma set interior is **excluded** (floor protection / crane cannot
enter).

### 2.2 Grid layout

```text
┌───────────────────────────────────────────────┐
│                chroma set (excluded)          │
├───────────────────────────────────────────────┤
│   ···  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ···   │
│   ···  ·  X  X  X  X  X  X  X  X  ·  ·  ···   │  ◄─ crane lane (dense)
│   ···  ·  X  X  X  X  X  X  X  X  ·  ·  ···   │  ◄─ crane lane (dense)
│   ···  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ···   │
└───────────────────────────────────────────────┘
        coarse 0.5 m             dense 0.25 m
```

- **Dense region** (0.25 m spacing): the crane's expected travel lanes
  between the base-storage position and the shooting positions, plus a
  0.5 m margin on both sides.
- **Coarse region** (0.5 m spacing): the surrounding staff area, doors,
  and any reachable floor outside the dense lane.
- Expected total points: **80–120** (to be finalized after on-site lane
  measurement).

### 2.3 Physical grid marking

- Use non-residue painter's tape to mark grid-cell corners on the floor.
- **≥ 4 corner reference marks** of the full survey area: these anchor the
  grid to studio-frame coordinates and allow re-registration if the tape
  grid is disturbed.
- Photograph the full grid before measurement starts.
- **Tape grid integrity re-check**: after measurement, re-measure each
  corner reference mark with a metric tape. If any corner has drifted more
  than `±5 mm` from its logged position, flag the affected grid cells in
  §5 and consider them "low-confidence".

### 2.4 Grid CSV schema

Raw inclinometer readings are **not committed** (per Reviewer Amendment N2).
They are captured on the operator's laptop and transported off-site.
Summary statistics and the heatmap (§5) are committed.

The raw CSV schema is fixed so the post-processing script is
independent of the session:

| Column | Unit | Meaning |
| --- | --- | --- |
| `point_id` | string | `R<row>C<col>` grid-cell ID |
| `x_m` | m | X in studio frame (from grid corner reference) |
| `y_m` | m | Y in studio frame |
| `region` | string | `dense` or `coarse` |
| `axis` | string | `X` or `Y` inclinometer axis |
| `reading_idx` | int | `1..3` per-point, or `1..5` for noise-floor subsample |
| `tilt_deg` | deg | signed degrees, sign convention per §3.4 |
| `temp_c` | °C | ambient near the instrument |
| `timestamp_iso` | string | ISO-8601 local time |
| `observer` | string | initials of the person taking the reading |

Operators archive the raw CSV on their laptop (e.g.,
`~/godo_ts5/floor_tilt/raw_YYYYMMDD.csv`). The committed summary
(`summary.json`) references only the SHA-256 of the raw file.

---

## 3. Per-point protocol

### 3.1 Acclimation and environment

- Inclinometer acclimates in the studio at ambient temperature for
  **≥ 15 minutes** before the first reading.
- If ambient temperature drifts more than `ΔT > 5 °C` during the session,
  abort and restart after re-acclimation.
- Log ambient temperature at start, middle, and end of the session (§3.3
  drift-gate checkpoints).

### 3.2 Per-point readings

- **3 readings per axis** (X, Y) per grid point.
- Maximum intra-point spread: `max(readings) − min(readings) ≤ 0.1°`.
  - If exceeded on any axis, **reject all 3 readings, re-take the point**.
  - If a second retake also fails, flag the point as "unstable" in the raw
    CSV (`observer` note column) and continue.
- Sign convention (see §3.4) must be consistent across the whole session.

### 3.3 Drift gate

The primary instrument is placed on the reference plate (§1.1) at:

- **Start of session** — record zero offset `z_0`.
- **Midpoint** (after approx. half the points are done) — record `z_mid`.
- **End of session** — record `z_end`.

Drift gate: `max(|z_mid − z_0|, |z_end − z_0|, |z_end − z_mid|) ≤ 0.05°`.

- If the gate fails, all points measured since the last passing checkpoint
  are invalidated and must be retaken.
- If the fallback instrument (§1.2) is used, the drift gate is not
  quantitative; instead, photograph the bubble position against the
  reference plate at each checkpoint and mark the session as
  "semi-quantitative".

### 3.4 Sign convention

- `+X` tilt: west side of the studio floor higher than east side.
- `+Y` tilt: north side higher than south side.
- Record the studio compass orientation in the `## Studio frame
  registration` block (§5) — this is the only way the sign convention
  is unambiguous across sessions.

### 3.5 Noise-floor subsample

- Pick a random 10 % of the total grid points (seed the RNG and log the
  seed in `summary.json` for reproducibility).
- On each selected point, take **5 readings per axis** instead of 3.
- This gives a within-point standard deviation estimate, separate from
  the between-point tilt variation (§5).

### 3.6 Cross-observer check

To bound the observer bias, the following **5 preselected points** are
measured independently by a second person:

| Point name | How it is chosen |
| --- | --- |
| `origin` | the grid-corner reference closest to the studio door |
| `center` | the grid point closest to the centroid of the crane movable area |
| `far` | the grid point farthest from `origin` |
| `highest` | the grid point with the largest tilt magnitude in the first pass |
| `random` | one grid point selected via the same seeded RNG (§3.5), excluding the four above |

- Accept if `|axis_obs1 − axis_obs2| ≤ 0.05°` on both axes for all 5 points.
- If the check fails on any point, the whole session is flagged and a
  root-cause note is written to §5 (instrument drift vs. protocol drift
  vs. tape grid movement).

---

## 4. TS5 session sequencing

TS5 is a shared field session that also includes the chroma-wall NIR
reflectivity measurement (PROGRESS.md #6) and the retro-reflector sweep
(PROGRESS.md #5). These are sequenced to avoid mutual interference:

```text
┌────────────────────┐
│ NIR reflectivity   │  (#6) — studio lights can stay warm
│ measurement        │
└──────────┬─────────┘
           ▼
      ≥ 30 min buffer    ← studio light thermal equilibration + operator rest
           ▼
┌────────────────────┐
│ Reflector sweep    │  (#5) — needs chroma walls to be in a known NIR state;
│ (distance × angle) │        leaves tape/marker residue to clean up
└──────────┬─────────┘
           ▼
      ≥ 30 min buffer    ← tape residue cleanup + reference plate setup for tilt
           ▼
┌────────────────────┐
│ Floor tilt survey  │  (#8) — requires a clean, dry floor for tape grid
│ (this document)    │         and a stable thermal environment
└────────────────────┘
```

**Buffer justification**:

- **NIR → Reflector buffer**: studio tungsten / LED fixtures radiate heat;
  thermal drift on the reflector tape's adhesive (and on the C1's
  photodetector window) stabilizes over ~20–30 min of settled lighting.
- **Reflector → Tilt buffer**: the reflector measurement leaves tape
  strips and marker references on the floor; these must be removed
  before the tilt grid tape is laid, or they become trip hazards and
  reference-ambiguity sources. 30 min covers cleanup + operator rest +
  inclinometer placement on the reference plate for re-acclimation.

---

## 5. Results (to be filled after TS5)

<!-- TODO (TS5 session): fill every subsection in §5 post-measurement. -->

### 5.1 Studio frame registration

- **TODO (TS5 session)**: photograph of the studio, compass orientation
  (N/E/S/W mapped to sign convention §3.4), and the coordinates of the
  4+ grid-corner reference marks in the studio frame.

### 5.2 Summary statistics

Fields to be written into the committed `summary.json` (path:
`doc/hardware/floor_tilt_survey_TS5/analysis/summary.json`, created
post-session):

| Field | Meaning |
| --- | --- |
| `n_points` | Total grid points measured |
| `n_points_dense` | Points in the dense crane lane |
| `n_points_coarse` | Points in the surrounding coarse area |
| `n_points_rejected` | Points rejected by §3.2 spread gate |
| `max_tilt_deg` | `max(|tilt|)` over both axes, all points — **sole tier gate input** |
| `p95_tilt_deg` | 95th percentile magnitude — Phase 5 hindsight only |
| `mean_tilt_deg` | Vector-mean over both axes — Phase 5 hindsight only |
| `stddev_tilt_deg` | Within-point noise floor (§3.5) — Phase 5 hindsight only |
| `drift_gate_pass` | bool |
| `cross_observer_pass` | bool |
| `raw_csv_sha256` | SHA-256 of the laptop-archived raw CSV |
| `rng_seed` | Seed used for §3.5 / §3.6 sampling |
| `ambient_temp_c_start` | °C |
| `ambient_temp_c_mid` | °C |
| `ambient_temp_c_end` | °C |

**Amendment N4**: `max_tilt_deg` is the **sole input** to the tier
decision in `leveling_mount.md §1`. `p95_tilt_deg`, `mean_tilt_deg`,
and `stddev_tilt_deg` are recorded only for Phase 5 retrospective
analysis.

### 5.3 Heatmap

- **TODO (TS5 session)**: 2D heatmap of
  `sqrt(tilt_x² + tilt_y²)` (magnitude) over the grid, with the
  crane lane outline overlaid. Committed to
  `doc/hardware/floor_tilt_survey_TS5/analysis/heatmap.png`.

### 5.4 Field R_max

The AMCL budget derivation in `leveling_mount.md §1` uses
`R_max = min(10 m, measured_farthest_AMCL_confident_wall)`. The "LiDAR
to farthest AMCL-confident wall" distance is measured **during TS5** at
the crane's likely mount position: stand the C1 at the crane pan-axis
mount, identify the farthest permanent wall surface visible in a single
scan that AMCL would use as a feature (i.e., not a movable prop, not
the chroma set interior), and measure that distance with a metric tape
or laser distance meter.

- **TODO (TS5 session)**: record `measured_R_max_m`.
- If `measured_R_max_m < 8 m`, the threshold derivation in
  `leveling_mount.md §1.1` must be recomputed with the new value, and
  the resulting adjusted thresholds logged into that doc before
  mount selection.

### 5.5 Flags / anomalies

- **TODO (TS5 session)**: record every rejected point, every flagged
  tape-grid corner (§2.3), drift-gate failures (§3.3), and
  cross-observer failures (§3.6). Write root-cause notes.

---

## 6. Data egress

- Raw CSV is **NOT committed** to the repo (Reviewer Amendment N2,
  Cross-platform hygiene in CLAUDE.md §6).
- Before the operator leaves the studio:
  - Copy the raw CSV + photo log to a USB stick (primary egress — studio
    WiFi may not exist or may not be reachable).
  - On return, transfer to the laptop, compute SHA-256, and
    `git add` + `git commit` the **summary.json + heatmap.png +
    updated §5 sections** of this file. The raw CSV reference (hash)
    lives in `summary.json`, not on disk in the repo.
- No WiFi dependency during the session.

---

## 7. Change log for this document

| Date | Change | By |
| --- | --- | --- |
| 2026-04-23 | Scaffold landed (methodology + TODO sections for field data) | Writer agent (Plan A v2) |
| **TODO (TS5 session)** | Field measurement + §5 fill-in | TS5 session crew |
