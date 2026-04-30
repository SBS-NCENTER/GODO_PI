---
name: AMCL accuracy and frame redefinition are orthogonal problems
description: When the operator asks about LiDAR overlay vs map alignment, distinguish "AMCL accuracy" (Problem 1, runtime localization) from "frame redefinition" (Problem 2, YAML metadata edit). They share the same visualization but require different tools.
type: feedback
---

GODO has TWO map-related problems that look the same on the /map overlay but are fundamentally different. Confusing them leads to applying the wrong fix.

## Problem 1 — AMCL accuracy (runtime)

**Symptom**: live LiDAR scan dots don't sit cleanly on the PGM walls. Visible mismatch even when AMCL says `converged`.

**Root cause**: AMCL is solving "where is the LiDAR in the map frame?" each scan. If its pose estimate is biased (sigma_hit tuning, low-information map regions, multi-basin yaw), the projected scan dots land in the wrong place.

**Tools that fix this**:
- 1-shot calibrate (force AMCL re-converge)
- Sigma annealing (PR #32 — already shipped)
- Brush-erase dynamic objects (PR #39 — already shipped)
- **Initial pose hint** (issue#3 — narrows AMCL particle spread to chosen basin, blocks 90° yaw multi-basin entry)
- AMCL silent-converge diagnostic metric (issue#4 — measures pose accuracy beyond `σ_xy`)
- Pipelined K-step Live AMCL (issue#5 — per-scan iteration depth)
- Re-mapping with cleaner SLAM run

**Tools that do NOT fix this**:
- B-MAPEDIT-2 origin pick (it relabels world coords; the LiDAR-to-map alignment relationship is unchanged)
- B-MAPEDIT-3 yaw rotation (same — frame relabel only)

## Problem 2 — Frame redefinition (operator-meaningful coords)

**Symptom**: the (x, y) values UE receives are nonsensical to the operator. Default frame origin is "wherever the LiDAR was when SLAM started"; the operator wants origin = studio center, axes aligned to walls.

**Root cause**: ROS map_server convention puts the world frame at the SLAM start point. The operator's mental frame (studio center / wall-aligned) is different.

**Tools that fix this**:
- B-MAPEDIT-2 origin pick (PR #43 — translation; YAML `origin[0..1]` edit only)
- B-MAPEDIT-3 yaw rotation (issue#6 — rotation; PGM bilinear resample + YAML `origin[2]`)
- Together = two-point calibration (rigid transform between studio frame ↔ map frame)

**Tools that do NOT fix this**:
- AMCL improvements (they make AMCL more accurate IN whatever frame the YAML defines; they don't change the frame definition)

## Why this matters

The operator on 2026-04-30 KST was confused mid-session: "지도의 레이아웃과 현재 라이다의 오버레이가 서로 완전히 겹치지 않는 이유가 어디에서 오는 것인지 헷갈린다. 1번과 2번이 다른 것인지, 아니면 같은 것인지." They wondered if B-MAPEDIT-2/3 (Problem 2 tools) would also fix the LiDAR overlay mismatch (Problem 1 symptom). They wouldn't.

**How to apply this distinction in future conversations**:

1. When operator reports "scan ↔ map mismatch": Problem 1. Recommend AMCL diagnostics + pose hint + map quality fixes. NEVER recommend B-MAPEDIT-2/3 alone.
2. When operator reports "(x, y) sent to UE doesn't match my studio coordinate system": Problem 2. Recommend B-MAPEDIT-2 + B-MAPEDIT-3.
3. When operator reports BOTH: separate into two work tracks. Different tools, different priorities. Don't bundle.
4. β/γ work (frame redefinition) was correctly scoped for Problem 2. The HIL pain on overlay alignment is Problem 1 and needs issue#3/#4/#5.

**Visual diagnostic**: when scan ↔ map mismatch is uniform (whole scan rotated by N° relative to map), it's a Problem 1 yaw multi-basin signature. When mismatch is regional (some walls match, others don't), it's a Problem 1 map-distortion signature. In NEITHER case does B-MAPEDIT-2/3 help.
