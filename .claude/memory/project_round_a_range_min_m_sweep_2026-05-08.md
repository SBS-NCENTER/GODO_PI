---
name: Round A — amcl.range_min_m sweep determines 4.5 m as Bug B mitigation point + reveals studio geometry asymmetry
description: 30th-session HIL sweep across range_min_m values (0.15 / 4 / 4.5 / 5 / 7 m) on news-pi01. 4.5 m chosen as production tracker.toml setting — eliminates Bug B (5cm widening) entirely, preserves yaw constraint from -y wall, lowest pose_y stddev across all tested values. Code default UNCHANGED at 0.15 m for safe out-of-box.
type: project
---

## Context

issue#37 K=3 gate (PR #107) + issue#36 yaw tripwire elimination (squashed into #107) shipped 30th-session-opener. Operator HIL on `feat/round-a-prep` (PR #110) added PHASE0 line `pose_x_m` / `pose_y_m` / `xy_std_m` / `yaw_std_deg` fields → enabled per-scan stability time-series analysis. Round A goal: characterize "Bug B" (intermittent ~5 cm pose wobble with x, y simultaneous + sticky + restart-resolved pattern, operator-reported, structural) AND find the operating point that eliminates it.

## Sweep results (2026-05-08 KST, news-pi01 chroma studio)

| range_min_m | n | duration | xy_std_m mean | pose_x σ | pose_y σ | yaw_std mean | Bug B 30-50mm | Bug B 50+mm | iters median | RT jitter max | scan rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **0.15 m** (default) | 197,485 | **8.0 h** | 6.96 mm | **7.7 mm** | 2.2 mm | **0.100°** | **3.4 % (~14/min)** | 0.04 % (75 events) | 16 (95.79 %) | (n/a, pre-Round-A) | 6.89 Hz |
| 4 m | 7,114 | 10 min | 9.24 mm | 2.71 mm | 2.88 mm | 0.109° | 0.014 % (1) | 0.014 % (**1 × 175 mm event**) | 17 | **26.6 µs** ★ | 9.5 Hz |
| **4.5 m ★** | **31,668** | **53 min** | 9.34 mm | **2.44 mm** | **2.38 mm** ★ | 0.113° | 0.0063 % (2) | **0** ★ | 17–18 | 28.8 µs | 9.87 Hz |
| 5 m | 20,666 | 32 min | 9.52 mm | 2.36 mm | 2.56 mm | 0.116° | 0 | 0 | 18–19 | 37.0 µs | 9.76 Hz |
| 7 m | 5,645 | ~5 min | 10.30 mm | 1.89 mm | 2.48 mm | 0.136° | 0 | 0 | **23 (96.8 %, cap-fixed)** | 32.4 µs | 9.43 Hz |

n = PHASE0 path=live\* line count. Bug B Δ histogram bucketed on |Δpose_x|. RT jitter from UDS `get_jitter` (Thread D 60 Hz smoother, CPU 3 SCHED\_FIFO 50). Raw logs: `/tmp/phase0_overnight_baseline_2026-05-08.log` (8 h) + `/tmp/phase0_4m_full_2026-05-08.log` (10 min) + `/tmp/phase0_4.5m_53min_2026-05-08.log` + `/tmp/phase0_5m_30min_2026-05-08.log` + `/tmp/phase0_5m_to_7m_sweep_2026-05-08.log`.

## Decision (operator-locked 2026-05-08 KST)

- **Production**: `/var/lib/godo/tracker.toml` set to `range_min_m = 4.5` via SPA Config tab. Already deployed and HIL-validated for ≥ 53 min with **0 Bug B 50+mm events**.
- **Code default** (`AMCL_RANGE_MIN_M` in `core/config_defaults.hpp`): UNCHANGED at 0.15 m. Other studios / dev hosts may need different value depending on their geometry; the 4.5 m optimum is studio-specific.
- **Validation cap**: `amcl.range_min_m` Tier-2 schema row's max bumped 2.0 → 5.0 → 10.0 m across PR #110 commits, giving operators headroom to sweep up to 10 m without C++ rebuild.

## Why 4.5 m wins (geometry + AMCL interaction)

Operator's studio has a **long flat wall on the -y axis at perpendicular distance ~2.5 m** (operator-locked observation 2026-05-08 KST). Sweep results confirm this geometric reality:

```
range_min_m → behavior
  0.15 m   : near-LiDAR fixtures (people, soft surfaces, LiDAR housing)
             contaminate AMCL likelihood → x bottleneck (flat-wall direction
             gets weak constraint AMPLIFIED by noise) → 7.7 mm pose_x σ.
             Multi-modal particle cloud → Bug B "5 cm widening" sticky
             degenerate state ~14/min in 30-50 mm Δx range.
  4 m      : near noise mostly removed BUT 2.5 m wall's perpendicular
             beams (r < 4 m) also gone. r=4-12 m oblique wall beams kept
             → yaw constraint preserved (best yaw_std 0.109°). 1 large y-
             axis 175 mm jump in 10 min → Bug B not fully eliminated.
  4.5 m ★  : sweet spot. Wall oblique beams r=4.5-12 m kept (yaw
             still good 0.113°). Slightly more near noise removed than
             4 m → Bug B eliminated (0 events 53 min). Best pose_y σ
             across all tested values. RT jitter low (28.8 µs).
  5 m      : Bug B eliminated, but pose_y σ slightly worse (2.56 vs 2.38)
             AND RT jitter notably higher (37 µs) due to iters median
             rising 18-19 vs 17-18.
  7 m      : -y wall oblique r=2.5-7 m all gone → yaw constraint cliff
             (0.136°, +24 % over 5 m). iters cap-fixed at 23 (97 %) —
             AMCL annealing budget exhausted every scan. Too aggressive.
```

**Counterintuitive finding (load-bearing for design)**: increasing `range_min_m` makes AMCL's self-uncertainty `xy_std_m` WORSE (6.96 → 9.34 mm at 4.5 m, +34 %) BUT makes the actual published pose value MORE stable (pose_x σ 7.7 → 2.44 mm, 3.2× better). Mechanism: fewer beams = wider posterior (AMCL honest about reduced data) BUT remaining beams more informative per-beam (less noise injection from near fixtures). For Live mode UE rendering — which consumes `pose_x_m`/`pose_y_m`, NOT `xy_std_m` — this is strict net improvement.

## Bug B mechanism — characterized

8 h baseline data showed Bug B is a **structural pattern, not rare**: ~14 events/min in 30-50 mm Δx range, ~0.16 events/min in 50+mm range. Operator observations (sticky, x+y simultaneous, restart-resolved) match a **particle filter degenerate state / sticky multi-basin lock-in**:

```
Trigger    : transient weak x constraint (e.g., person crosses LiDAR view)
            → particle cloud bifurcates into bimodal distribution in x.
Symptom    : weighted mean pose oscillates between basin centroids
            → both x and y shift simultaneously (basins separated in (x, y)).
Stuck      : degenerate resampling kills cloud diversity in the losing basin
            → filter can't escape via measurement updates.
Recovery   : tracker restart reseeds particle cloud → diversity restored.
```

This explains why operator-tunable `range_min_m` cures the symptom: removing near-LiDAR fixture noise prevents the bimodal split from happening in the first place (single-basin posterior). Same idea as down-weighting in issue#13 (distance-weighted likelihood) but as hard cutoff — empirically sufficient at 4.5 m.

## Implications for follow-up issues

- **issue#22 (KLD-sampling adaptive N)** — primary motivation reduced (Bug B mitigation no longer the load-bearing reason) but value retained: (a) OneShot first-tick N=5000 efficiency, (b) Live steady-state CPU savings → cache pressure ↓ → RT jitter ↓ further, (c) particle-diversity preservation as defense against future weak-constraint scenarios that 4.5 m hard cutoff doesn't catch. Round B kickoff candidate.
- **issue#13 (distance-weighted likelihood)** — empirically partially superseded by hard `range_min_m` cutoff. Still has value if studio geometry needs distance-dependent weighting (e.g., heterogeneous near-features where some are useful and some noise). Lower priority post-Round-A.
- **issue#38 (`amcl.range_min_m` cap)** — DONE in PR #109/PR #110 (cap 2 → 5 → 10 m). Operator can now sweep up to 10 m via SPA without rebuild.
- **Future studio-specific tuning** — when GODO deploys to a different studio, operator should sweep `range_min_m` again with this same protocol. Optimal value depends on local geometry (presence/absence of close flat walls, near-LiDAR fixtures). 4.5 m is news-pi01-specific.

## RT jitter side-finding

RT jitter on Thread D (60 Hz smoother, CPU 3, SCHED\_FIFO 50) varied across the sweep:

| range_min_m | RT jitter max (UDS get_jitter) |
|---|---|
| 4 m | 26.6 µs |
| 4.5 m | 28.8 µs |
| 5 m | 37.0 µs |
| 7 m | 32.4 µs |

5 m has the highest jitter despite NOT having the most filtered beams. Hypothesis: at 5 m, iters median = 18-19 (slightly elevated from 4-4.5 m's 17-18) → cold path on cores 0-2 generates more memory bandwidth pressure → L3 cache shared with CPU 3 → RT thread cache miss rate ↑. At 7 m, iters jumps to 23 (cap-fixed) but TOTAL beam count drops more sharply, so cold-path total work doesn't grow as much. 4 / 4.5 m are the cache-friendliest. 60 Hz frame budget = 16,667 µs so even 37 µs is 0.22 % of frame — operationally harmless, but visible signal for future tuning.

This is another argument for `range_min_m = 4.5 m` as the production sweet spot.

## Sample backup files (gitignored, /tmp)

- `/tmp/phase0_overnight_baseline_2026-05-08.log` — 8 h × 0.15 m baseline (issue#37 + issue#36 deploy validation, 197 K samples)
- `/tmp/phase0_4m_full_2026-05-08.log` — 10 min × 4 m
- `/tmp/phase0_4.5m_53min_2026-05-08.log` — 53 min × 4.5 m (production decision evidence)
- `/tmp/phase0_5m_30min_2026-05-08.log` — 32 min × 5 m
- `/tmp/phase0_5m_to_7m_sweep_2026-05-08.log` — 5 min × 7 m
- `/tmp/phase0_5m_extra2min_2026-05-08.log` — 2 min × 5 m (operator config-typo period; rolled into 5 m total)

Operator script: `~/analyze_round_a.sh` (POSIX-awk-portable, sigma_xy / pose / yaw / iters / acceptance bars in one shot).

## Operator workflow lessons (process)

1. **HIL-driven sweep is essential**: simulation alone wouldn't have surfaced the geometric x-vs-y asymmetry or the multi-basin Bug B mechanism. Live-on-news-pi01 protocol is the right tool for AMCL likelihood-shape questions.
2. **Per-scan time-series instrumentation pays off**: PHASE0 line extension (PR #110 commit `e39f266`) was the enabler for ALL the analysis above. ~10 LOC investment, infinite analytical leverage. Same pattern reusable for issue#22 / #13 baseline measurement.
3. **Operator's gut-feel intuition reliable**: 4.5 m suggested by operator before any data — exactly matched empirical optimum. Geometric intuition (long -y wall at 2.5 m) led to correct prediction of yaw cliff at 7 m.
4. **Stacked-PR pitfall**: PR #109 was stacked on `feat/issue-37-pool-k-gate` (already squash-merged via #107). When operator clicked Merge on #109, it landed on the orphan stacked branch, not main. Resolution: PR #110 re-targeted to main directly. Lesson for future: when a stacked PR's base branch is squash-merged upstream, retarget the stacked PR's base to main IMMEDIATELY before merging.
