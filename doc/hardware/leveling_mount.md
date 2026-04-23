# Leveling Mount — Decision Framework

> **Purpose**: define how the leveling mount between the crane pan-axis
> center and the RPLIDAR C1 is chosen, given the floor tilt survey
> results from [`floor_tilt_survey_TS5.md`](./floor_tilt_survey_TS5.md).
>
> **Status**: decision framework frozen; **mount selection pending TS5
> session results**. The section marked `TODO (post-measurement)` is the
> decision output that will be filled after §1 is applied to the
> measured `max_tilt_deg` and `measured_R_max_m`.
>
> **Phase**: Phase 1 decision gate.
> **Blocks**: Phase 2 map building — do not start mapping until the
> mount is selected and installed.

---

## 1. Threshold rationale

### 1.1 Budget-driven derivation

The C1 rotates in a horizontal plane. If that plane is tilted by angle
`θ` with respect to world horizontal, a LiDAR ray at range `R` hitting
a vertical wall shifts along the wall by `Δ ≈ R · sin(θ) ≈ R · θ`.
AMCL sees this as a residual that it cannot distinguish from a pose
error, so the tilt-induced shift is an additive component of the
positional error budget.

Given:

- `ε_target = 10 mm` — the share of the total `1–2 cm` accuracy target
  that is allocated to "out-of-plane tilt" alone. Other components
  (LiDAR single-sample noise ±30 mm averaged by √N, map quantization,
  AMCL convergence) consume the remainder.
- `R_max = min(10 m, measured_farthest_AMCL_confident_wall)` — see
  [`floor_tilt_survey_TS5.md` §5.4](./floor_tilt_survey_TS5.md#54-field-r_max).
  Default conservative value is `10 m` (C1 datasheet range for 70 %
  reflectance, clamped by indoor studio geometry). If TS5's measured
  value comes in below 8 m, **recompute the thresholds in §1.2 with
  the new R_max and record the recomputed table in §3**.

The allowable tilt is `θ ≤ ε_target / R_max`.

### 1.2 Threshold table (`R_max = 10 m` default)

```text
┌──────────────┬──────────────────────┬────────────────────────────────┐
│ Tier         │ θ range (deg)        │ Implied max error @ R_max=10 m │
├──────────────┼──────────────────────┼────────────────────────────────┤
│ Tier 1       │ max_tilt ≤ 0.06°     │ Δ ≲ 10.5 mm   (on-budget)      │
│ Gray zone    │ 0.06° < max_tilt     │ 10.5 mm < Δ ≲ 21 mm            │
│              │         ≤ 0.12°      │ (above budget, below target)   │
│ Tier 2       │ max_tilt > 0.12°     │ Δ > 21 mm      (off-target)    │
└──────────────┴──────────────────────┴────────────────────────────────┘
```

- **Cost-engineering compromise label**: the bin edges `0.06°` / `0.12°`
  are **not** dictated purely by the `ε_target / R_max` math — `0.06°`
  is `~1.05 × ε_target / R_max` rounded up to a convenient DWL2000XY
  resolution step. The gray zone is a factor-of-2 buffer that maps to
  "still under the 1–2 cm total-system target, but tilt is
  over-consuming the budget and the rest of the budget has to
  compensate". This is a deliberate engineering compromise and MUST
  be revisited if the Phase 5 integration test shows the total-system
  target is not met.

### 1.3 Tier-decision input — single gate

**Amendment N4**: the tier decision uses `max_tilt_deg` **only**.
`p95_tilt_deg`, `mean_tilt_deg`, and `stddev_tilt_deg` are logged in
`floor_tilt_survey_TS5.md §5.2` for Phase 5 retrospective analysis, but
they do not participate in the mount decision. Using a single gate
avoids the failure mode where "most of the floor is fine so we pick
the cheap mount" and then the crane parks on the one bad spot.

### 1.4 Threshold recompute rule

If `measured_R_max_m < 8 m` (per
[`floor_tilt_survey_TS5.md §5.4`](./floor_tilt_survey_TS5.md#54-field-r_max)),
recompute the table in §1.2 using the measured value. The Tier 1 edge
becomes `ε_target / measured_R_max_m` (rad → deg), and the gray-zone
edge is kept at 2× that. Record the recomputed edges and the driving
`measured_R_max_m` in §3.

---

## 2. Candidate mounts

### 2.1 Candidate (a) — passive bubble-level + shim

**Description**: a machined aluminum / steel plate with a built-in
bubble level and three shim-adjustment screws (or a purpose-built
spirit-level leveling base). The operator adjusts shims once at
installation, then re-checks periodically per SOP.

| Attribute | Value |
| --- | --- |
| Static levelness achievable | `≲ 0.03°` with a 0.02°/div bubble level and care |
| Yaw stability | No yaw DOF — yaw is mechanically fixed to the mount |
| Estimated cost (KRW) | 30k–80k (machined plate + shims + bubble) |
| Complexity | Low — no active components |
| Power | None |
| Failure modes | (i) shim creep over months of vibration; (ii) operator forgets to re-check → SOP dependency |
| Maintenance cadence | Monthly visual bubble check + re-shim if needed |
| Phase 5 risk contribution | Low — static mechanical system |

### 2.2 Candidate (b) — 2-axis active gimbal

**Description**: a motorized or piezo-actuated 2-axis gimbal that
servos the C1 mounting plate to level using an embedded inclinometer.
The gimbal compensates floor tilt at the mount without relying on
operator attention.

| Attribute | Value |
| --- | --- |
| Static levelness achievable | `≲ 0.01°` closed-loop |
| **Yaw stability (critical)** | Must be specified by vendor as **< 0.1° yaw wobble under a ±5 kg·m moment** at the LiDAR mounting plate. If not spec'd, DO NOT procure — yaw wobble feeds directly into AMCL and is far more harmful than residual tilt |
| Estimated cost (KRW) | 300k–1.2M |
| Complexity | High — motors, controller firmware, inclinometer, power |
| Power | 5–12 V DC, typ. 200–500 mA |
| Failure modes | (i) controller firmware bug / watchdog absence; (ii) motor hunting when idle; (iii) yaw wobble if gimbal bearings are not preloaded; (iv) power-rail drop causing mid-session loss of level |
| Maintenance cadence | Per-session post-install acceptance test (§4) |
| Phase 5 risk contribution | Medium — adds an active subsystem that must itself pass the embedded-reliability checklist (`doc/Embedded_CheckPoint.md`) |

---

## 3. Decision matrix

The decision rule depends on `max_tilt_deg` from
[`floor_tilt_survey_TS5.md §5.2`](./floor_tilt_survey_TS5.md#52-summary-statistics):

| Tier (from §1.2) | Mount choice | Rationale |
| --- | --- | --- |
| Tier 1 (`≤ 0.06°`) | Candidate (a) passive | Floor is already within budget — shim mount is sufficient |
| Gray (`0.06°–0.12°`) | Candidate (a) **+ SOP** | Passive mount is acceptable if the operator SOP enforces pre-session bubble check; **SOP dependence is itself a failure mode** (see §3.1) |
| Tier 2 (`> 0.12°`) | Candidate (b) active | Passive mount cannot bring us within budget; active gimbal required |

### 3.1 Gray-zone SOP-dependence caveat

The gray-zone recommendation of "passive mount + SOP" carries an
explicit failure mode: **if the operator skips the pre-session bubble
check, the tilt error re-appears silently**. This is by design a human
factor, not a mechanical fix. Mitigations (MUST be applied if this
branch is taken):

- Document the pre-session bubble check in the operator runbook as a
  blocking step (can't proceed without it).
- Add a session-log line in `godo-tracker` that records the operator's
  confirmation of the bubble check (timestamp + operator initials).
  The tracker should warn if the last confirmation is older than
  N hours (N to be set during Phase 3).
- Re-evaluate the choice if Phase 5 integration reveals operator
  compliance is unreliable — in that case, upgrade to Candidate (b).

### 3.2 Recompute record (post-TS5)

<!-- TODO (post-measurement): fill after §1.4 rule is applied. -->

| Field | Value |
| --- | --- |
| Source document | `floor_tilt_survey_TS5.md §5.2 / §5.4` (rev `<git-sha>`) |
| `measured_R_max_m` | **TODO (post-measurement)** |
| Recompute triggered? | **TODO (post-measurement)** (`true` iff `measured_R_max_m < 8 m`) |
| Tier 1 edge used | **TODO (post-measurement)** |
| Gray edge used | **TODO (post-measurement)** |
| `max_tilt_deg` observed | **TODO (post-measurement)** |
| Resulting tier | **TODO (post-measurement)** |
| Selected candidate | **TODO (post-measurement)** |

---

## 4. Post-install acceptance test (P1-9.4)

After the selected mount is installed and the LiDAR is bolted down,
run the following acceptance test before declaring the mount
ready for Phase 2 mapping.

### 4.1 Test procedure

1. **5-point residual measurement**: with the inclinometer re-placed
   on the LiDAR's top plate (not on the floor, on the LiDAR mounting
   surface itself), measure the residual tilt at 5 preselected points
   using the selection rule in §4.2.
2. **Axis convention**: the same sign convention as the floor survey
   (`floor_tilt_survey_TS5.md §3.4`) applies here. Do NOT re-define.
3. **Readings per point**: same as the survey — 3 readings per axis,
   spread gate `≤ 0.1°`.
4. **Gate**: for every point and every axis,
   `|residual_tilt| ≤ 0.06°` must hold, regardless of which tier was
   selected. This is the **whole-system** tilt limit at the LiDAR plane
   after mount correction — it is NOT relaxed for gray-zone or Tier 2
   builds. The mount's job is to bring tilt under the Tier 1 limit; if
   it does not, the mount has failed.
5. **Fail action**: if any point fails the gate, re-shim (Candidate a)
   or re-calibrate the gimbal zero (Candidate b) and re-test. Do not
   proceed to mapping.

### 4.2 Point selection rule (5 points)

The 5 acceptance-test points are:

| Point | Selection |
| --- | --- |
| `origin` | the studio-frame origin (same physical spot as `floor_tilt_survey_TS5.md §3.6 origin`) |
| `crane_centroid` | the centroid of the crane movable area (same as `§3.6 center`) |
| `lane_end_A` | one endpoint of the primary crane travel lane (storage side) |
| `lane_end_B` | the other endpoint of the primary crane travel lane (shooting side) |
| `highest_gradient` | the grid cell with the largest spatial gradient of tilt from `floor_tilt_survey_TS5 §5.3` heatmap — i.e., the worst "ramp" where the crane is most sensitive to small wheel position errors |

### 4.3 Acceptance test record

<!-- TODO (post-install): fill after mount is installed. -->

| Field | Value |
| --- | --- |
| Install date | **TODO (post-install)** |
| Mount selected | **TODO (post-install)** |
| Residual @ origin (X / Y, deg) | **TODO (post-install)** |
| Residual @ crane_centroid | **TODO (post-install)** |
| Residual @ lane_end_A | **TODO (post-install)** |
| Residual @ lane_end_B | **TODO (post-install)** |
| Residual @ highest_gradient | **TODO (post-install)** |
| Gate pass? | **TODO (post-install)** |
| Operator / date | **TODO (post-install)** |

---

## 5. Phase 2 gating

**Do not start map building until this document's §3.2 (decision) and
§4.3 (acceptance test) are both filled and the gate is green.**

A map built on a tilted LiDAR will bake that tilt into the walls'
apparent geometry, and AMCL will chase a biased solution forever after.
This is not recoverable in software at our 1–2 cm target.

The `PROGRESS.md` "Phase 2 preparations" section carries the same
gate as a one-line reminder pointing at this file.

---

## 6. SYSTEM_DESIGN cross-reference

Once §3.2 is filled, the mount decision propagates into
`SYSTEM_DESIGN.md §1` (hardware topology diagram) and `§8` (failure
scenarios). Those edits are **Parent-led** (not this doc's
responsibility) and happen in the same follow-up session that fills
§3.2 here.

### Appendix A — Gray-zone failure mode phrasing (for `SYSTEM_DESIGN.md §8`)

Reference text the Parent may use when writing the `SYSTEM_DESIGN.md
§8` row for the gray-zone + passive-mount branch:

> **Failure**: operator skips pre-session bubble check after a gray-zone
> floor-tilt survey; residual tilt silently re-enters the position
> budget.
> **Symptom**: AMCL pose slowly drifts over a session; UE footage
> misregisters by > 2 cm at far walls.
> **Detection**: godo-tracker session-log operator-confirm line is
> stale (> N hours) OR yaw tripwire fires against the last baseline.
> **Mitigation**: refuse to start a session without a fresh bubble-
> check confirmation; escalate to Candidate (b) active gimbal if
> compliance proves unreliable.

This is suggested text, not binding — the Parent may rephrase when
integrating into `SYSTEM_DESIGN.md §8`.

---

## 7. Change log for this document

| Date | Change | By |
| --- | --- | --- |
| 2026-04-23 | Scaffold landed (thresholds + candidates + TODO for decision / acceptance) | Writer agent (Plan A v2) |
| **TODO (post-measurement)** | §3.2 filled with TS5 results | Follow-up session |
| **TODO (post-install)** | §4.3 filled with acceptance-test residuals | Follow-up session |
