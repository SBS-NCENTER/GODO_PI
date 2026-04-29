---
name: RPi 5 VideoCore VII GPU for matrix ops (rotation, future linear algebra)
description: Operator (2026-04-29 24:00 KST) raised: RPi 5 has a VideoCore VII GPU; we use only one HDMI for the camera framework (no on-Pi display); the GPU is mostly idle. Could map rotation (and future matrix-heavy operations) be offloaded?
type: project
---

## Hardware context

RPi 5 has a **VideoCore VII GPU** (Broadcom BCM2712 platform's display/compute block). On news-pi01 we only use HDMI for occasional bring-up — production mode has no display at all. So the GPU sits at near-0% load while CPUs 0/1/2 carry the cold-path workload (CPU 3 is RT-isolated for the hot path).

## Operator's specific suggestion

> 회전 변환이 행렬 연산이라면 RPi5의 VideoCore VII GPU를 활용하는 것은 어때? 어차피 라즈베리파이에 HDMI OUT은 한 개만 사용할거라서 자원이 조금 남을텐데.

The map-rotation feature (Track B-MAPEDIT-3 per project_map_edit_origin_rotation.md) needs to apply a 2×2 rotation matrix to coordinates. That's tiny per-call but adds up if applied to e.g. every cell during a re-rasterization. Same matrix-math angle applies to AMCL particle resampling, EDT rebuilds, scan transforms, etc.

## Programming surface (what the GPU exposes)

| Path | Effort | Notes |
|---|---|---|
| **OpenGL ES 3.1 compute shaders** | medium | Mesa V3D driver supports compute shaders on VideoCore VII. Standard GLSL, GPU buffer objects. Has display-server overhead unless we use EGL surfaceless context. |
| **Vulkan 1.2 compute** | medium | V3DV driver in Mesa supports Vulkan on VideoCore VII (RPi 5). Headless via VK_KHR_surfaceless_queue. More modern than GLES, less framework cruft. |
| **OpenCL via POCL/Mesa rusticl** | low to medium | RPi 5 has experimental OpenCL exposure through rusticl. Simplest API for matrix ops. Maturity is uncertain on the Trixie image — verify before scoping. |
| **Direct V3D submit** (BCM kernel ioctl) | high | Pi Foundation discourages this; it's not stable across kernel versions. Avoid. |

## When the GPU is worth it

GPU offload only beats CPU when:
- The dataset is large enough to amortize transfer + dispatch overhead (~50-200 µs per dispatch on V3D).
- The math is parallelizable (SIMD-friendly).

For our candidates:
- **Map rotation re-rasterization** (~105k cells × 1 mat-vec each) — CPU does this in ~5 ms with SIMD. GPU might do it in ~1 ms but +200 µs dispatch ≈ break-even. **Marginal gain.**
- **EDT rebuild** in `build_likelihood_field` (~105k cells × multi-pass) — could be a big GPU win if we move the whole 1D EDT to a compute shader. But the algorithm's data-dependent passes don't trivially map to GPU. **Research project.**
- **AMCL particle resampling / weight evaluation** (5000 particles × 200 beams = 1M ops/iter, 25 iters/OneShot = 25M ops) — **this is the actual juicy target.** GPU could shorten OneShot from ~750 ms to ~100-200 ms. But moving the AMCL kernel to GPU is a massive structural change.
- **Scan transform / projectScanToWorld** (200 beams × per-frame) — small, CPU is fine.

## Tradeoffs vs sigma annealing throughput

If we keep growing the annealing schedule (per the pipelined-pattern memory) — e.g., 20 phases × 25 iters — total iters reach 500. CPU side stays under 1 s but pushes the OneShot latency budget. GPU at that scale would drop it to ~150 ms.

So the GPU-acceleration argument STRENGTHENS if we go more granular on annealing. Worth keeping in scope **after** B-MAPEDIT-3 rotation lands.

## Recommended sequencing

1. **Don't attempt now**. RPi 5 V3D + Mesa + Vulkan/OpenCL on Trixie is a maturity bet — needs a proof-of-concept run first.
2. Step 1 of any future GPU work: **measure** current CPU time on the candidate operations (annealing total wall, EDT rebuild, AMCL evaluate_scan). Without numbers, "GPU is faster" is hand-wave.
3. Step 2: **POC** a single dispatch — e.g. EDT 1D pass via Vulkan compute. Measure end-to-end latency including transfer.
4. If POC shows ≥ 5× speedup on the chosen op AND total system wallclock improves, scope a full integration PR. Else, document the negative result and stop.

## Resource monitoring prerequisite

Operator's other request — System tab CPU/GPU usage display (per `project_system_tab_service_control.md`) — is a **prerequisite** for any GPU work. Without GPU utilization metrics in the operator UI, we can't validate that GPU offload is actually happening or compare to baseline.

So:
- Phase A: System tab GPU metrics (~100 LOC, part of the System tab process monitor PR-B).
- Phase B: Pick a candidate operation + benchmark CPU baseline.
- Phase C: POC GPU dispatch.
- Phase D: Production integration if POC wins.

A and B can run in parallel with B-MAPEDIT. C and D are research-grade work for after Track 5 (UE integration).
