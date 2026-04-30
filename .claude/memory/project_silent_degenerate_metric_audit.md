---
name: Silent degenerate-metric audit candidates
description: Pattern where "no input -> trivial metric pass" hides bugs. AMCL all-free map -> sigma_xy=0 looked converged is the canonical case. Audit codebase for similar trivially-passing health metrics.
type: project
---

## The pattern

A health/quality metric reports "OK" because its inputs degenerated, not because the system is actually healthy. Reviewers and operators trust the metric, and the broken state ships silently.

## Canonical case observed 2026-04-30 (B-MAPEDIT HIL)

When `MapMaskCanvas.getMaskPng()` rewrote the entire active PGM to FREE (alpha-as-paint bug), the resulting all-free map gave AMCL a uniformly flat likelihood field. Symptoms:

- One-shot mode reported `sigma_xy = 0` (looked converged).
- Particles all tied weight → resampling indistinguishable → particles collapsed to seed pose → variance collapses.
- Meanwhile `pose.yaw` bounced 165° → 135° → 333° → 292° between 2-second ticks — yaw tripwire fired correctly (which is how we noticed). But the convergence metric itself never complained.
- Classic AMCL failure mode: "no observation gradient ⇒ no disagreement ⇒ no variance ⇒ trivially-converged metric".

## Why this matters

The convergence metric is the operator-facing trust signal. If it can pass with zero true information, every operator decision downstream of it (FreeD merge, UE publish, base-move recalibration) is built on sand. Silent degenerate metrics are the **opposite of fail-loud**.

## Audit candidates (Parent should grep + reason about each)

| # | Subsystem | Metric / signal | Degenerate input that trips it | Severity |
|---|---|---|---|---|
| 1 | AMCL one-shot + Live | `sigma_xy < threshold` | All-free or all-occupied map; map smaller than scan range; corrupted likelihood field | High — feeds operator UI |
| 2 | AMCL Track D-5 sigma annealing | "minima found at sigma=X" | Cost function flat → any sigma is a "minimum" | Medium — drives schedule |
| 3 | FreeD smoother | jitter / discontinuity check | Constant input (crane parked) → trivially smooth | Low — not gating |
| 4 | UE 60 Hz publisher | "publish OK" rate | Stale-cached pose published indefinitely if writer thread stalls | Medium — UE doesn't know |
| 5 | godo-webctl `/api/health` | `{ok: true}` | Currently checks process alive only; doesn't check tracker UDS responsive | Medium |
| 6 | godo-webctl `/api/system/restart_pending` | `{pending: bool}` | False-negative on stale sentinel from prior boot | Low (tracker clears at boot) |
| 7 | Map activate symlink swap | "active map valid" | Symlink to non-existent target → trackr reads zero bytes → all-free degenerate (case #1!) | High — chains into #1 |
| 8 | Backup `/api/map/backup/list` | "backup available" | Empty backup-dir returns `{items: []}` — UI may show "no rollback" but presents Apply as safe | Medium |
| 9 | Polkit + systemd controls | "service active" | Process alive but stuck in startup loop → systemd reports `active (running)` for the parent | Medium |
| 10 | Diagnostics SSE stream | "stream OK" | Empty stream (no events) indistinguishable from "subscribed but tracker silent" | Low |

## Audit deliverable shape

For each candidate above:
1. Identify the metric definition (file:line).
2. Identify the operator-facing surface that trusts it (UI banner, decision gate, alarm).
3. Construct the degenerate input that would trip a trivial-pass.
4. Decide: fail-loud guard vs. orthogonal sanity check vs. operator education (banner copy).
5. Cost-vs-value: high-severity items get a guard; low-severity items get a memory note + future ticket.

## Why this audit, not just spot-fixing #1

Pattern is structural, not local. AMCL all-free is just where it surfaced first. Without the audit, the next HIL session will surface another instance and we re-discover the rule. One pass across the candidate table prevents that.

## Suggested first-pass guard for #1 (AMCL low-information map)

`entropy_of_likelihood_field` or `count_of_occupied_cells_in_scan_radius < threshold` at calibrate-start. If too low → fail-loud "low-information map" banner instead of letting the calibration proceed and report sigma=0. Block one-shot mode entry until operator acknowledges.

## When to revisit

Schedule this audit AFTER B-MAPEDIT-2 (origin pick) lands. Not blocking; not urgent enough to interrupt the current Track-B sequence. But it should NOT be deferred indefinitely — silent degenerate metrics compound trust debt fast.

## Cross-reference

- B-MAPEDIT prod regression PR #40: triggered this audit observation.
- AMCL Track D-5 sigma annealing (PR #32): related but different — D-5 is about narrow-likelihood convergence cliffs, not zero-likelihood degeneracy.
- `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md`: historic sigma data; useful baseline for "what sigma_xy looks like under healthy convergence".
