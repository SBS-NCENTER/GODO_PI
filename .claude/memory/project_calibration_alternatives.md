---
name: AMCL calibration alternatives beyond pose hint
description: Operator (2026-04-30 23:30 KST) flagged that issue#3 pose hint is a fallback safety net, not a production-friendly daily tool. Future direction = autonomous calibration via image-based matching, GPU feature extraction, or pre-marked landmarks. Logged so a later session naturally revisits these after issue#3/4/5 stabilize.
type: project
---

## Operator framing

"이런 기능은 production에서 매번 사용하기는 힘들 것 같긴 해. 아마 정확하긴 하겠지만." — issue#3 pose hint is correct as a baseline + safety net but should NOT be the ultimate solution for routine recalibrate. Operator burden of clicking hint every calibrate is unsustainable in production.

The long-term direction is autonomous AMCL calibration that needs no per-call operator input. Operator suggested three concrete approaches.

## Approach A — image-based shape matching

LiDAR scan and PGM are both occupancy images (after rasterizing the scan). Use template/feature matching directly:

- OpenCV `matchTemplate` / `phaseCorrelate` for global (Δx, Δy, Δyaw) transform recovery.
- ORB / SIFT / AKAZE feature matching + RANSAC.
- Particularly strong when the studio has distinctive geometric features (operator example: chroma wall's rounded ㄷ shape).
- **Bypasses AMCL's particle approach entirely** — multi-basin trap eliminated.
- Weaknesses: long monotonic walls (feature-poor regions) under-determine the transform; needs at least one distinctive corner/arc visible.

## Approach B — GPU-accelerated feature extraction (corner / arc / line)

Extract geometric primitives from both PGM and LiDAR scan, RANSAC-match them:

- Targets RPi 5 VideoCore VII GPU (see `project_videocore_gpu_for_matrix_ops.md` for the candidate compute path).
- If fast enough: applies to **live mode** at 60 Hz hot path — autonomous self-correction without any hint or calibrate trigger.
- Highest implementation cost (GLSL shaders + data marshaling between LiDAR thread and GPU queue).
- Highest theoretical ceiling: solves issue#3, #4, #5 together.

## Approach C — PGM-marked landmarks + LiDAR reverse-mapping

Operator marks distinctive geometric features on the PGM once (e.g. "this rounded corner = landmark 1, this notch = landmark 2"). Calibrate algorithm finds the same pattern in the live LiDAR scan, computes the rigid transform.

- Builds on **issue#6 (B-MAPEDIT-3) infrastructure** — operator will already be comfortable editing PGM in the Map Edit tab.
- One-time operator effort (mark features once per studio change), zero per-calibrate effort.
- Highest automation reliability of the three (operator-validated features → near-zero mismatch).
- Implementation: midweight (landmark-storage YAML extension + matching algorithm + Map Edit UI for mark/unmark).

## Comparison

| Approach | Per-calibrate operator effort | Accuracy | Automation reliability | Implementation cost |
|---|---|---|---|---|
| issue#3 (hint) | every time | high (within σ) | depends on operator | low (in flight) |
| A (image match) | none | medium-high | high if features rich | medium |
| B (GPU features) | none | high | autonomous, 60 Hz capable | high |
| C (marked landmarks) | one-time (per studio) | very high | very high | medium |

## Recommended evolution path

1. **issue#3** (this session) — pose hint baseline.
2. **issue#4** — silent-converge diagnostic (metric to compare any approach against AMCL).
3. **issue#5** — Pipelined K-step Live AMCL (improves Live without changing the algorithm).
4. **Approach C first** — sits on issue#6 infrastructure; one-time setup; highest reliability per implementation hour. Operator already trained on Map Edit by the time issue#6 lands.
5. **Approach A second** — fallback for studios where landmark marking isn't feasible; complementary to C (feature-poor regions get C-marks, feature-rich regions get A-auto).
6. **Approach B last** — only if A+C combined still leave a gap that's worth the GPU shader investment. May never be needed.

## How to apply

When issue#3/#4/#5 are stable and the operator asks "what's next for localization quality?", point at approach C as the natural next move. When the operator asks "can we make calibrate auto-trigger?", point at A or B. When the operator says "how do we get rid of the hint button?", the answer is "C is the lowest-cost way."

Do NOT propose A/B/C until issue#3 is shipped and HIL-validated. Premature optimization.

## Architectural pattern: heavy-algo seed + AMCL maintenance (operator 2026-04-30 23:50 KST)

Rather than running approaches A/B/C every calibrate (expensive), use them as **first-seed only**:

```text
boot / cold-start
  → expensive algo (A/B/C) runs ONCE → produces a rough but unique pose basin seed
  → AMCL inherits the seed → maintenance via step() / converge_anneal() each scan / each calibrate
  → AMCL stays in the correct basin as long as the system is up
```

This re-frames issue#5 (Pipelined K-step Live AMCL) — the issue is NOT "AMCL needs deeper convergence per scan", it's "AMCL needs to be started in the right basin and never lose it". A heavy seed at boot + cheap AMCL maintenance solves both.

**Implications for Live mode**: Live's ~4 m drift seen in test5 is multi-basin entry, not iteration depth. A single boot-time cold-start via approach A/B/C eliminates the drift. issue#5's pipelined K-step then becomes the "stay in basin under perturbation" guarantee, not the "find the basin" mechanism.

## Distance-weighted AMCL likelihood (operator 2026-04-30 23:50 KST)

Operator-proposed: in AMCL likelihood matching, **down-weight near-LiDAR points and up-weight far points** (or hard cutoff below `r_cutoff`).

Counter-intuitive — usually "near = accurate, far = noisy" applies to raw range measurement. But for AMCL match likelihood, near walls are LOW information (monotonic, any small yaw error still matches them) while far corners/notches/doors are HIGH information (distinctive, only the right pose matches them).

```text
w(dot) = match_score(dot) × distance_weight(dot.range)

distance_weight(r) = 0                                if r < r_cutoff
                   = (r - r_cutoff) / (r_max - r_cutoff)   otherwise
```

T-shape studio: distinctive features (rounded ㄷ corner, doors, notches) sit at ~3-5 m from typical LiDAR positions. So `r_cutoff` candidates: 0.5, 1.0, 1.5, 2.0 m.

**Methodology**: same sweep approach as `project_amcl_sigma_sweep_2026-04-29.md` (sigma_hit sweep) — run N calibrates at each r_cutoff, measure (x, y) error + yaw error + repeatability variance. Pick the cutoff that maximizes correctness × repeatability.

This is a **single-knob change** to `production/RPi5/src/localization/amcl.cpp` likelihood weighting. Lowest-cost of all the algorithmic ideas in this file. Could be its own issue (issue#8?) and ship before approaches A/B/C.

Open question: does the cutoff need to be position-dependent (different optimum near a wall vs at studio center)? If yes, the sweep becomes 2D (position × cutoff). If no, single global value.

## Camera AF analogy (operator 2026-04-30 23:50 KST)

Mirrorless camera AF combines two complementary methods. GODO localization maps directly:

| Camera AF | GODO localization |
|---|---|
| **Phase detection** (fast, coarse, range-finding by parallax) | Heavy algo (image match / GPU features / landmarks) — fast first seed in the right basin |
| **Contrast detection** (slow, accurate, hill-climb on local sharpness) | AMCL particle filter — accurate maintenance within a basin |
| **Hybrid AF** (combines both — phase first, then contrast for fine focus) | First-seed pattern (above) — heavy algo for cold-start, AMCL for maintenance |
| **Manual focus (MF)** | issue#3 pose hint — operator does the phase-detection equivalent by hand |

Operator's framing: issue#3 is "automated hint" by analogy = the phase-detection step in hybrid AF. The eventual production architecture is hybrid AF with the manual-focus override always available.

This analogy is portable — useful when explaining the system to engineers / operators / new collaborators. "It's like mirrorless AF" conveys the architecture in one sentence.

## Status

- File created 2026-04-30 23:30 KST.
- Extended 2026-04-30 23:50 KST with first-seed pattern + distance-weighted AMCL + AF analogy.
- MEMORY.md index entry deferred at operator's request — re-indexing happens at session-close (chronicler skill) or upon explicit request.
