# TS4 — Windows bench session (2026-04-21)

First hardware bench session, home/office environment before chroma-studio testing.

## Session contents

### `data/` — raw capture CSVs

| Timestamp | Backend | Tag | Frames | Notes |
| --- | --- | --- | --- | --- |
| 062327Z | sdk | smoke_sdk | (aborted) | first attempt, wrong COM port (COM7) |
| 062335Z | sdk | smoke_sdk | (aborted) | second attempt, wrong COM port |
| **062844Z** | **sdk** | **smoke_sdk** | **100** | first successful capture, COM3, static |
| **062908Z** | **raw** | **smoke_raw** | **100** | backend-parity counterpart of the above |
| **064216Z** | **sdk** | **reflector_2strips** | **500** | two 3M retro-reflective strips ~1 m at 280 deg |
| **064346Z** | **raw** | **reflector_2strips** | **500** | backend-parity counterpart (same physical setup) |
| **064449Z** | **sdk** | **baseline_500** | **500** | no reflector, same position, 500-frame baseline |

### `logs/` — session .txt (one per successful capture)

Each log contains host/OS/backend/baud/scan-mode + run stats + `csv_sha256` integrity hash for the paired CSV.

### `analysis/` — analyze.py outputs

- `*_polar.png` — per-capture polar plot (angle × distance × quality)
- `*_qhist.png` — quality histogram
- `*_noise.csv` — per-direction (1 deg bin) mean / std / median-q / sqrt_N bound
- `*__vs__*.csv` — SDK-vs-Raw per-bin delta
- `*_qhist.csv` — quality histogram tabulated (reflector only)

## Key findings (documented for session-resume context)

1. **Backend parity confirmed**: SDK (pyrplidar) and Non-SDK (pyserial + in-house parser) agree to sub-mm on stable surfaces (mean |delta_mean| = 1.09 mm across 184 stable bins). pyrplidar is NOT silently denoising.
2. **C1 single-sample precision**: ~1 mm std on stable flat surfaces at 0.6-15 m range (below the 15 mm datasheet resolution spec).
3. **Dead zone**: 0-40 deg and 180-260 deg yielded mostly zero returns in this environment. ~27% null-return rate overall. Unknown whether this is environmental (dark surfaces, distant openings) or geometric (mount / crane arm occlusion). **Re-measure in studio.**
4. **Quality ceiling on natural surfaces**: 6-bit wire quality topped out at ~52 / 63 in this environment. Mean quality ~10.
5. **Reflector discrimination** (two 3M strips at ~1 m, 280 deg):
   - Reflector peak: median q = 50, max 56, std_dist = 31.8 mm on the 275-280 deg peak bin.
   - Natural close object (210 deg, ~640 mm): median q = 37, max 52, q>=50 fraction = 4.0%.
   - Reflector peak bin: q>=50 fraction = 96.2%.
   - **Single-sample threshold has 4% false-positive overlap** (natural surfaces occasionally hit q=52).
   - **Bin-level "q>=50 fraction >= 50%" gives clean separation** — the right discriminator for O4 marker detection.

## Next session (chroma studio)

Repeat the same test protocol in the chroma-studio environment. Capture naming convention:

- `baseline_<studio-config>_500` — no reflector
- `reflector_<pos>_<dist>_<frames>` — reflector at named position / distance
- Also sweep reflector at 2 m / 5 m / 10 m and glancing angles (0 / 30 / 45 / 60 / 75 deg).

Afterwards, archive under `out/TS5/` following the same data/logs/analysis layout.

## Integrity

All raw CSVs have matching `csv_sha256` recorded in the session .txt. Any downstream re-analysis can verify the archive has not drifted.
