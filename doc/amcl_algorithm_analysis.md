# AMCL — Theory, GODO's Implementation, and Tuning

> Author: Parent (Claude Opus 4.7 1M) on operator's request, 2026-05-06 KST.
> Audience: GODO contributors who want to read `production/RPi5/src/localization/*.cpp` with the full algorithmic context underneath.
> Source ground-truth: GODO main `129ad3f` + branch `feat/issue-11-parallel-eval-pool` (PR #99). All file:line citations verified against this snapshot.
> Length: long-form on purpose — the operator asked for depth, and AMCL has many small subtleties whose individual treatment matters more than headline brevity.

---

## Table of contents

- Part I — Foundation
  - §1 The localization problem (and why it is hard)
  - §2 Bayesian recursive estimation
  - §3 Belief representation: parametric vs non-parametric
  - §4 Why particle filters
- Part II — Monte Carlo Localization (MCL)
  - §5 Sample-based belief
  - §6 The predict → update → resample recursion
  - §7 Importance sampling and weight semantics
  - §8 Variance, effective sample size, particle deprivation
- Part III — AMCL specifics
  - §9 The "A" in AMCL: KLD-sampling (textbook)
  - §10 Augmented MCL: sample injection
  - §11 What GODO does NOT inherit from textbook AMCL
- Part IV — Motion model
  - §12 Odometry-based motion model (textbook)
  - §13 GODO's variant: pure Gaussian jitter
  - §14 σ pair selection — OneShot vs Live
- Part V — Sensor model: the likelihood field
  - §15 Beam endpoint vs likelihood field — why we picked this one
  - §16 Euclidean Distance Transform (EDT) precomputation
  - §17 Felzenszwalb 1D distance transform — decoded
  - §18 Per-beam likelihood: Gaussian on distance + numerical floor
  - §19 The role of `sigma_hit_m`
- Part VI — Resampling
  - §20 When to resample (effective sample size threshold)
  - §21 Low-variance (systematic) resampling
  - §22 Numerical stability — the log-sum-exp pattern
- Part VII — Output
  - §23 Linear weighted mean (x, y)
  - §24 Circular mean (yaw)
  - §25 Convergence detection
- Part VIII — GODO's architecture choices
  - §26 Two operating modes: OneShot and Live
  - §27 σ_hit anneal schedule (Track D-5)
  - §28 Pipelined-hint Live mode
  - §29 issue#11 fork-join particle evaluation pool
  - §30 Bit-equality guarantee under parallelism
- Part IX — Tuning cheat sheet
  - §31 Parameter table with semantics
  - §32 Empirical sweep evidence
- Part X — Future improvements (open issues)
  - §33 Roadmap by issue number
- Part XI — References

---

# Part I — Foundation

## §1. The localization problem (and why it is hard)

GODO needs to know **where the SHOTOKU crane base is in the studio world frame**, expressed as a 2D pose `(x, y, yaw)`. The pose is recovered from a **single 360° 2D LiDAR scan** taken at the crane's pan-axis centre, matched against a **pre-built occupancy grid map** of the studio.

The problem is hard because:

1. **The scan is noisy.** RPLIDAR C1 specifies ±30 mm distance error at short range, with a long, mildly Gaussian tail at longer range; in chroma studios the mostly-flat dark walls also produce specular drop-out. So a single beam's distance reading is not exact even when the rest of the geometry is.
2. **The map is approximate.** The map was built once, statically. Doors move, lighting fixtures shift, the crane itself appears in some scans (it shouldn't show up in the map but might cast a partial shadow). Anything not in the map shows up as a "wrong" measurement that should not be allowed to dominate the estimate.
3. **Ambiguity is real.** A studio with bilateral symmetry (or a flat back wall the LiDAR sees as a featureless line) admits multiple poses that explain the scan equally well. The estimator must NOT collapse onto an arbitrarily-chosen mode just because some weighted sum looked good.
4. **The base may have rotated since calibration.** If somebody bumps the crane, the world-to-base transform is no longer a pure 2D translation — `yaw` has shifted too. The estimator must surface this rather than silently absorb it as "a different (x, y)".

These pressures rule out simple methods (least-squares scan matching, particle-free analytic filters) and motivate something that:

- Tracks **multiple hypotheses simultaneously** until evidence collapses them.
- Weighs hypotheses by **how well the entire scan looks under each pose**, not just one or two beams.
- Stays **numerically stable** when many beams pile log-likelihoods together.
- Has a **clean degenerate-input behaviour** — when the scan is uninformative, the estimator should report wide variance rather than a confident wrong answer.

That is exactly what a particle filter delivers, with AMCL being the most popular concrete recipe for the LiDAR-vs-grid case.

---

## §2. Bayesian recursive estimation

Localization is a special case of the more general **Bayesian state-estimation** problem. Pick a state `x_t` (the unknown pose at time `t`), observations `z_t` (the LiDAR scan), and any control input `u_t` (motion command, if available). The goal is to compute the **posterior belief**:

```
bel(x_t) = p(x_t | z_{1..t}, u_{1..t})
```

— the probability density of the state given everything we have observed so far. A celebrated result of probability is that this density evolves recursively:

```
prediction step  :  bel*(x_t) = ∫ p(x_t | x_{t-1}, u_t) bel(x_{t-1}) dx_{t-1}
correction step  :  bel(x_t)  = η · p(z_t | x_t) · bel*(x_t)
```

where `η` is a normalization constant. The recursion has two factors that need modelling:

- **Motion model** `p(x_t | x_{t-1}, u_t)` — how the state changes between steps given the (possibly noisy) control.
- **Sensor / measurement model** `p(z_t | x_t)` — how likely the observation is, assuming the state is `x_t`.

Bayes' rule combines them. The trouble is the integral in the prediction step: for high-dimensional state spaces (or for non-Gaussian densities), it has no closed form. We need an approximation.

---

## §3. Belief representation: parametric vs non-parametric

Two big families of approximation:

| Family | Idea | Strengths | Weaknesses |
|---|---|---|---|
| **Parametric** (e.g., Kalman filter family) | Approximate the density by a fixed-form distribution (typically a Gaussian) and propagate its parameters. | Closed form. Cheap. Optimal under linear-Gaussian assumptions (Kalman). | Cannot represent multimodal or skewed densities. EKF/UKF can extend to mild nonlinearity but still single-mode. |
| **Non-parametric** (histogram filter, particle filter) | Approximate the density by samples (or grid bins) drawn from it. | Multimodal-friendly. No restriction on shape. Easy to incorporate any sensor model. | Computational cost grows with sample count. Variance issues. |

GODO's localization scene is **multimodal in spirit** (a flat back wall, mirrored studio sides) and the sensor model is decidedly non-Gaussian (likelihood field has nontrivial structure near corners and doorways). So a Gaussian parametric filter is the wrong tool. **Non-parametric — particle filter — is the right family.**

---

## §4. Why particle filters

A particle filter (sequential Monte Carlo) approximates `bel(x_t)` by a **weighted set of samples**:

```
{ (x_t^[i], w_t^[i]) : i = 1..N }
```

Each sample is a "particle" — a candidate pose. The weight `w_t^[i]` measures how plausible that pose is in light of the observation. The recursion becomes:

1. **Propagate** every particle through the motion model: `x_t^[i] ~ p(x_t | x_{t-1}^[i], u_t)`.
2. **Re-weight** every particle by the sensor model: `w_t^[i] ∝ p(z_t | x_t^[i])`.
3. **Resample** with replacement from the weighted set, optionally only when the cloud has lost diversity.

Specific virtues that drive the GODO design:

- The estimator can **hold multiple hypotheses for as long as evidence permits.** No assumption of unimodality.
- The sensor model is a **function we can evaluate**, not one we have to invert. This matters for a likelihood field that is too irregular to invert in closed form.
- **Convergence is observable** — particle cloud variance shrinks monotonically as each scan adds information, and we can detect it cleanly (`xy_std_m`, `circular_std_yaw_deg`).

---

# Part II — Monte Carlo Localization (MCL)

## §5. Sample-based belief

Concretely in GODO, every particle is a `Particle` defined in `production/RPi5/src/localization/pose.hpp`:

```cpp
struct Pose2D {
    double x;            // m, world frame
    double y;            // m
    double yaw_deg;      // degrees, [0, 360)
};
struct Particle {
    Pose2D pose;
    double weight;
};
```

The cloud is held in `Amcl::front_` (active particles) and `Amcl::back_` (resample destination, for ping-pong). Both are pre-allocated to `core::PARTICLE_BUFFER_MAX = 10000` and the working set size `n_` is set per seed (`amcl_particles_global_n = 5000` for first-tick global localization, `amcl_particles_local_n = 500` for per-step Live tracking; see `Amcl::seed_global` / `Amcl::seed_around` in `amcl.cpp`). The capacity-not-size discipline is invariant `(f)` of the localization module: pre-allocated buffers stay; only `n_` changes.

`weight` is interpreted as a **non-log linear weight** at the boundary between functions. Inside `Amcl::normalize_weights` the values are temporarily turned into log-weights, the maximum is subtracted (numerical stability), then exponentiated and renormalized. Outside `normalize_weights` the weights are linear and sum to 1.

---

## §6. The predict → update → resample recursion

`Amcl::step` (`amcl.cpp:181-273`) is the recursion's per-tick body. In order:

1. **Motion (`jitter_inplace`).** Each particle's pose gets a Gaussian perturbation of σ_xy / σ_yaw. See §13.
2. **Sensor (`evaluate_scan`).** The full LiDAR scan is evaluated against each particle's hypothesis. Each particle is re-weighted by the product of per-beam likelihoods. See §15-§19.
3. **Normalize (`normalize_weights`).** Log-sum-exp re-stabilization so the cloud's weights sum to 1 in finite arithmetic. See §22.
4. **Effective sample size check.** Compute `N_eff = (Σ w_i)² / Σ w_i² = 1 / Σ w_i²` (since Σ w_i = 1 after normalize). If `N_eff < 0.5 · N`, resample. See §20.
5. **Stats + convergence assessment.** Compute `weighted_mean` (output pose), `xy_std_m`, `circular_std_yaw_deg`. The result tag `converged = (xy_std_m < cfg.amcl_converge_xy_std_m && yaw_std_deg < cfg.amcl_converge_yaw_std_deg)` flags the early-exit predicate (see §25 and §11).

`Amcl::converge` (`amcl.cpp:298-315`) is a thin loop that calls `step` up to `cfg.amcl_max_iters = 25` times and exits early on `converged && iter >= 2` (i.e. require a settled cloud across at least 3 iterations to avoid declaring convergence on the seed cloud's natural variance before the sensor model has reshaped it).

---

## §7. Importance sampling and weight semantics

The mathematical foundation of the re-weighting step is **importance sampling**.

We want to compute expectations under the posterior `p(x | z)`, but we can only sample from the prior `p(x)`. Importance sampling lets us draw samples from any "proposal" distribution `q(x)` and compute weights `w_i = p(x_i | z) / q(x_i)`. As long as `q` covers the support of `p`, the weighted average converges to the correct expectation.

In a particle filter the proposal at time `t` is the **predicted prior** `bel*(x_t)` — particles propagated through the motion model. The target is the **posterior** `bel(x_t) ∝ p(z_t | x_t) · bel*(x_t)`. So the importance weight reduces to:

```
w_t^[i] ∝ p(z_t | x_t^[i])
```

— exactly the sensor likelihood. That's why the per-particle re-weight does not need to know anything about the motion model: motion is folded into the proposal by sampling.

GODO's `evaluate_scan` (`scan_ops.cpp:58-101`) returns this likelihood as `exp(Σ log p_i)` (one term per beam). After `normalize_weights` the weights sum to 1 and represent the discrete posterior over the particle set.

---

## §8. Variance, effective sample size, particle deprivation

Importance-sampled estimates have **variance** that grows with the mismatch between proposal and target. As the proposal-target gap widens, fewer particles carry meaningful weight; the rest are "dead" — they contribute nothing to the expectation but eat per-step compute.

The standard health metric is the **effective sample size**:

```
N_eff = 1 / Σ w_i²       (for normalized weights)
```

`N_eff = N` when weights are uniform; `N_eff = 1` when one particle has weight 1 and all others zero. As scans accumulate and the target tightens against the proposal, `N_eff` drops.

Two failure modes:

- **High weight variance** — when `N_eff` is small, the estimator is effectively running on `N_eff` particles, not `N`. Resample to recover diversity.
- **Particle deprivation** — when the cloud's spread shrinks so far that no particle is near the true pose any more (e.g., after a sudden displacement), even resampling cannot help — the recovery requires reseeding from a wider distribution OR from a hint.

GODO addresses (a) with conditional resampling (§20). It addresses (b) with the **operator-controlled hint** (§28 — pose hint = strong command; if Live's belief drifts off truth, operator triggers a recalibrate which reseeds globally with N=5000).

---

# Part III — AMCL specifics

## §9. The "A" in AMCL: KLD-sampling (textbook)

Textbook AMCL — as published in *Probabilistic Robotics* (Thrun, Burgard, Fox 2005, Ch. 8) and as shipped in the ROS `amcl` package — adds two adaptive features on top of MCL:

**(1) KLD-sampling.** The particle count `N` adapts to the cloud's spread. When the cloud is wide (early localization, high uncertainty), use many samples (typically 5,000–10,000). When the cloud has converged onto a tight basin, use fewer (sometimes as low as 100). The criterion is the **Kullback-Leibler divergence** between the empirical histogram of the cloud and the unknown true posterior; the rule of thumb (Fox 2003) is to stop sampling when the histogram has enough bins covered to bound the KL divergence at some threshold `ε` with confidence `1 - δ`.

The headline number from the original Fox (2003) paper: KLD-sampling reduces compute by ~100× compared to fixed-N AMCL during steady-state, with no accuracy penalty.

**(2) Sample injection.** In addition to the resampled particles, AMCL injects a small percentage (1–10%) of randomly-distributed particles each step. This is a guard against the particle deprivation failure mode: if the true pose ever leaves the cloud's support (e.g. the robot was kidnapped), the random injections give the filter a chance to rediscover the true pose without manual reseeding.

---

## §10. Augmented MCL: sample injection (continued)

The injection rate adapts based on a **short-term vs long-term average likelihood ratio**. Intuitively: when recent measurements are systematically less likely than the long-run baseline, the cloud is probably tracking a wrong hypothesis; up the random injection rate. When recent likelihoods are nominal, injection drops back to baseline.

Mathematically: maintain two exponentially-weighted averages of `(1/n) Σ p(z_t | x_t^[i])`, with a fast and a slow time constant. The injection rate is `max(0, 1 - w_fast / w_slow)`.

This adaptation is beautiful in theory but **not without cost**: random samples have their own variance, and if the true cloud is fine, the random injections are wasted compute.

---

## §11. What GODO does NOT inherit from textbook AMCL

GODO's `class Amcl` is leaner. It deliberately omits KLD-sampling and adaptive injection, for principled reasons:

- **Fixed N = 500 (Live) / 5000 (OneShot first-tick).** Operator-locked. Rationale: KLD-sampling adds intricate machinery whose payoff depends on having very long convergence trajectories; GODO's actual convergence is a few-step affair on tight hint-seeded clouds (see §28). Issue#22 reserves the integer for a future KLD experiment.
- **No sample injection.** Operator chose pose-hint semantics over implicit reseeding (`project_hint_strong_command_semantics.md`). When the operator says "pose is here", that command is the law. If Live drifts onto a wrong basin, the operator's recalibrate (OneShot) is the recovery; the cloud does not silently rescue itself.
- **No motion model from odometry.** The crane has no odometry feed into the tracker — see §13.

So GODO's "AMCL" is really **fixed-N MCL with the AMCL likelihood-field sensor model and the AMCL low-variance resampler**. The "A" is honoured via `class Amcl` naming (familiarity for incoming contributors who know ROS amcl) but not implemented adaptively. This is documented in `production/RPi5/src/localization/amcl.hpp` lead comment and is part of the localization-module invariants.

---

# Part IV — Motion model

## §12. Odometry-based motion model (textbook)

Standard AMCL takes wheel-encoder readings (or other proprioceptive signals) and propagates each particle by the relative motion encoded in `u_t`:

```
x_t = x_{t-1} ⊕ [u_t + noise]
```

where `⊕` is SE(2) composition and `noise` is drawn from a model whose covariance grows with `|u_t|` (longer commanded motion → more accumulated wheel slip). The Probabilistic Robotics book gives a four-parameter "motion-model-odometry" (Ch. 5.4) with separate noise terms for translation, rotation-pre-translation, rotation-post-translation, and translation-related rotation drift.

This is a **predictive** propagation. Particles drift in the direction the command says they should go.

---

## §13. GODO's variant: pure Gaussian jitter

The SHOTOKU crane does not feed odometry into godo-tracker. The FreeD packets carry crane pose components (X, Y, Z, P, T, R, Z, F) but these are absolute crane-base values, not deltas; they would be a **fix**, not a **prediction**. And we are not using FreeD's own X/Y to localize — that is the very thing we're correcting (see CLAUDE.md §1).

Hence GODO's motion model is degenerate: pure isotropic Gaussian jitter, no commanded direction:

```cpp
void jitter_inplace(Particle* p, std::size_t n,
                    double sigma_xy_m, double sigma_yaw_deg, Rng& rng) {
    for (std::size_t i = 0; i < n; ++i) {
        p[i].pose.x       += rng.gauss(0.0, sigma_xy_m);
        p[i].pose.y       += rng.gauss(0.0, sigma_xy_m);
        p[i].pose.yaw_deg  = wrap_360(
            p[i].pose.yaw_deg + rng.gauss(0.0, sigma_yaw_deg));
    }
}
```

`scan_ops.cpp:103-114`. The σ pair is supplied per-call by `Amcl::step`, which forwards from `cfg.amcl_sigma_xy_jitter_m` (5 mm) / `amcl_sigma_yaw_jitter_deg` (0.5°) for OneShot, or `amcl_sigma_xy_jitter_live_m` (15 mm) / `amcl_sigma_yaw_jitter_live_deg` (1.5°) for Live (`config_defaults.hpp:75-76, 93-94`).

What does the jitter buy us if it has no directional bias?

- **Diversity preservation**. Without jitter, after a few resamples the cloud collapses onto a finite set of particle copies. Jitter spreads them back out, preserving the cloud's ability to absorb new observations.
- **Numerical immunity to sub-cell map quantization**. The likelihood field is a 1 cm-resolution grid (typical RPLIDAR mapping resolution). Particles with no jitter would sit at exact post-resample copies of an ancestor and re-evaluate the same lookup cells; jitter "smears" them across cells so the cloud's mean is not biased by grid quantization.
- **Soft tracking of unmodelled motion**. In Live mode the crane base may move at up to ~30 cm/s (operator estimate). With 10 Hz LiDAR, that's 30 mm of true motion per scan. The Live-mode σ_xy_jitter = 15 mm is wide enough that the true post-motion pose is within ~2 σ of the previous-pose-anchored cloud.

---

## §14. σ pair selection — OneShot vs Live

Two distinct σ pairs cover two distinct scenarios:

| Scenario | σ_xy_jitter | σ_yaw_jitter | Rationale |
|---|---|---|---|
| **OneShot** (`amcl_sigma_xy_jitter_m = 0.005`, `amcl_sigma_yaw_jitter_deg = 0.5`) | 5 mm | 0.5° | Operator clicks Calibrate. Crane is static. Tight σ keeps the cloud focused while convergence happens. |
| **Live** (`amcl_sigma_xy_jitter_live_m = 0.015`, `amcl_sigma_yaw_jitter_live_deg = 1.5`) | 15 mm | 1.5° | Crane is potentially moving (~30 cm/s). Wider σ accommodates motion between scans. |

These are passed in by `cold_writer.cpp` based on the active mode. The σ pair is a Tier-2 tunable (TOML / env / CLI override) — see CLAUDE.md §6 "No magic numbers" + `config_defaults.hpp`.

There is also a **σ_seed** pair (`amcl_sigma_seed_xy_m = 0.10`, `amcl_sigma_seed_yaw_deg = 5.0`) used by `seed_around` to populate the initial cloud spread. This is wider than the per-step jitter — the seed σ defines the cloud's **search basin**, while the jitter σ is its **per-step diversity refresh**.

For the operator-controlled hint case, the seed σ is overridden per-call to `(amcl_hint_sigma_xy_m_default, amcl_hint_sigma_yaw_deg_default) = (0.50, 20.0)` — see §28.

---

# Part V — Sensor model: the likelihood field

## §15. Beam endpoint vs likelihood field — why we picked this one

For 2D LiDAR + occupancy grid, two well-known sensor models:

**(A) Beam endpoint model.** Each beam's measurement `z_i = (range_i, angle_i)` is interpreted as a ray from the sensor pose. The probability `p(z_i | x)` is computed by ray-casting through the grid: walk along the ray, check where it first hits an occupied cell, compare to the measured `range_i`. The likelihood is a mixture of Gaussian (correct hit), exponential (random max-range return), uniform (sensor failure), and delta-at-z_max (unexpected free space).

Pros: physically motivated; respects beam geometry. Cons: **expensive** (ray-cast per beam per particle); **unstable** near map edges (small pose perturbations can cause a beam's hit cell to switch by one pixel, causing big jumps in likelihood); **unforgiving of map errors** (an unmapped chair shows up as "wrong" and the beam's likelihood collapses).

**(B) Likelihood field model.** Pre-compute, for each cell of the grid, the **distance to the nearest occupied cell**. The map is now a smooth scalar field. To evaluate a particle, compute each beam's endpoint in world coords and look up the distance value at that cell. The likelihood is a Gaussian on **distance**:

```
p_hit(z_i | x) ∝ exp(-d² / (2 σ_hit²))
```

where `d` is the distance from the beam endpoint to the nearest map obstacle.

Pros: **cheap** (one cell lookup per beam per particle, no ray-cast); **smooth** (distance changes continuously as pose perturbs); **forgiving of small map errors** (a small unmapped feature simply increases `d` for some beams; the Gaussian softly down-weights without collapsing). Cons: ignores beam geometry along the ray (a beam ending behind a wall is treated like a beam that hit the wall); slight tendency to over-confident hypotheses near corners.

GODO uses **(B) likelihood field**. The reasoning, in chronological order:

1. RPLIDAR C1 in chroma-studio environments has noisy returns (specular drop-out from black walls; ±30 mm distance error). A model that smooths over these is more robust.
2. The studio map will not be perfectly current (doors move, fixtures shift); we want soft tolerance for map errors.
3. The likelihood field admits a one-time precomputation (EDT, see below) that amortizes cost across all subsequent scans. With 500 particles × 290 beams = 145k cell lookups per `Amcl::step`, ray-casting would be 100s of milliseconds; a flat lookup is microseconds.

This decision is locked by `production/RPi5/SYSTEM_DESIGN.md` §6.5.

---

## §16. Euclidean Distance Transform (EDT) precomputation

The likelihood field is built from the occupancy grid by computing, for every cell, the squared Euclidean distance to the nearest occupied cell. Then a per-cell Gaussian is applied to convert squared distance to a likelihood:

```
LF[c] = exp(- (d_c · resolution_m)² / (2 · sigma_hit_m²))
```

The squared distance is computed by an **Euclidean Distance Transform (EDT)**.

There are several algorithms for EDT. The two big families:

| Family | Time complexity | Output type |
|---|---|---|
| **Brushfire** / wavefront | O(N · k) where k is the maximum distance | Approximate |
| **Felzenszwalb 2D** | O(N) — linear | Exact |

GODO uses **Felzenszwalb 2D** (`likelihood_field.cpp:33-78`): two passes of a 1D EDT, one along columns then one along rows. Total time is linear in cell count, with two `O(W · H)` sweeps.

The 1D building block is what does the algorithmic work; once you have it, the 2D extension is trivial (just call it once per column then once per row of the intermediate result).

---

## §17. Felzenszwalb 1D distance transform — decoded

The 1D problem: given an array `f[0..n-1]` of "source" values (think: 0 at obstacle cells, +∞ elsewhere), compute the array `D[0..n-1]` where:

```
D[q] = min_{i ∈ [0..n-1]} (f[i] + (q - i)²)
```

Naively this is `O(n²)`. The Felzenszwalb-Huttenlocher (2004) trick is to observe that each `i` contributes a **parabola** centred at `i` with offset `f[i]` — and we want the lower envelope of all these parabolas.

The lower envelope of n parabolas can be computed in `O(n)` because successive parabolas can be merged (the intersection point monotonically advances). The implementation maintains a stack of "currently winning" parabolas and processes each `q` once:

```cpp
// likelihood_field.cpp:33-78 (Felzenszwalb 1D core)
void edt_1d(const float* f, float* d, int n, int* v, float* z) {
    // v[k] = index of the k-th winning parabola
    // z[k] = leftmost q where v[k] dominates v[k-1]
    // First pass: build the lower envelope.
    int k = 0; v[0] = first; z[0] = -inf; z[1] = +inf;
    for (int q = first + 1; q < n; ++q) {
        // Find where parabola(q) intersects parabola(v[k]). If that
        // intersection is to the left of z[k], pop v[k] and try again.
        // Otherwise push (q, intersection) onto the envelope.
        ...
    }
    // Second pass: for each q, walk the envelope and read the dominating
    // parabola's value.
    k = 0;
    for (int q = 0; q < n; ++q) {
        while (z[k + 1] < (float)q) ++k;
        d[q] = (q - v[k])² + f[v[k]];
    }
}
```

Two non-textbook safeguards in GODO's implementation (already documented at `likelihood_field.cpp:25-31`):

1. **+∞ - +∞ = NaN guard.** When the source array has +∞ values (cells not yet known to have any obstacle contribution), the parabola intersection formula `(fq + q²) - (fvk + vk²)` could produce NaN. The implementation explicitly skips +∞ cells.
2. **All-+∞ row / column shortcut.** If a whole row or column has no finite source values, the output is +∞ everywhere; we early-exit.

The 2D pass is then:

1. Column-wise 1D EDT: input is the obstacle map (0 at occupied, +∞ elsewhere). Output is, for each cell, the squared distance to the nearest obstacle **in the same column**.
2. Row-wise 1D EDT on the column-pass output: now each cell's value is the squared distance to the nearest obstacle in 2D.
3. Per-cell `exp(-d²·res² / (2σ²))` to convert to a likelihood.

The final scaled likelihood field `LF[c] ∈ (0, 1]` is what `evaluate_scan` reads.

A detail worth flagging: the EDT scratch buffers `(v, z)` are **per-pass**, not per-call. Issue#19 (parallelizing the column / row sweeps across CPU 0/1/2 workers) needs **per-worker** scratch; that's why issue#11's `parallel_for(begin, end, fn)` API is not enough for issue#19, and a `parallel_for_with_scratch<S>` extension is required. See issue#11 plan §5 cross-applicability matrix.

---

## §18. Per-beam likelihood: Gaussian on distance + numerical floor

Once the likelihood field exists, `evaluate_scan` (`scan_ops.cpp:58-101`) computes per-particle likelihood as the **product of per-beam likelihoods** across all kept beams (~290 after stride-2 downsample of a typical RPLIDAR C1 frame):

```cpp
double log_w = 0.0;
for (each beam i) {
    // (1) Beam endpoint in sensor frame
    xs = r * cos(angle); ys = r * sin(angle);
    // (2) Rotate by particle yaw, translate by particle (x, y)
    xw = pose.x + xs * cos(yaw) - ys * sin(yaw);
    yw = pose.y + xs * sin(yaw) + ys * cos(yaw);
    // (3) World coord → cell index
    cx = (xw - origin_x) / resolution_m;
    cy = (yw - origin_y) / resolution_m;
    // (4) Lookup likelihood; floor at EVAL_SCAN_LIKELIHOOD_FLOOR
    double p = (in_bounds) ? LF[cy * W + cx] : kEps;
    if (p < kEps) p = kEps;
    log_w += log(p);
}
return exp(log_w);
```

(Pseudocode close to the actual loop. CW vs CCW sign is handled at `downsample()` time per `project_rplidar_cw_vs_ros_ccw.md` — driver returns CW angles, `downsample` negates to feed CCW into the AMCL kernel. The wire-format scan publish keeps raw CW for the SPA per invariant `(m)`.)

The product-of-likelihoods is computed in **log space** for the same numerical-stability reason as §22: 290 beams × `log(0.1)` would underflow to zero quickly in linear space.

The **floor** `kEps = EVAL_SCAN_LIKELIHOOD_FLOOR` (`core/constants.hpp`, currently `1e-6`) prevents a single far-out-of-map beam (e.g., a returned distance the LiDAR mismeasured by 50 cm into "no map here" territory) from collapsing the entire particle's likelihood to zero. Without the floor, that single beam's `log(0)` would dominate the product. With the floor, a wildly-off beam contributes `log(1e-6) ≈ -13.8` per beam — bad but bounded — so the particle's overall weight is shaped by the bulk of correct beams, not by 1-2 outliers. This is the same idea as a robust M-estimator's outlier saturation.

`kEps = 1e-6` is a Tier-1 (constexpr) constant — operator-locked. Track it in `core/constants.hpp` and never inline-magic-number it elsewhere (CLAUDE.md §6 rule).

---

## §19. The role of `sigma_hit_m`

The Gaussian's σ in `LF[c] = exp(-(d_m)² / (2 σ_hit²))` has a specific meaning: **how tolerant the model is of beam endpoint not lying on the nearest obstacle**.

- **Small σ_hit (e.g., 30 mm).** Likelihood field is sharply peaked at obstacles. A beam endpoint 50 mm off the nearest wall gets likelihood `exp(-(50/30)² / 2) = exp(-1.39) ≈ 0.25` per beam. With 290 beams, a 50-mm bias on every beam yields the particle a global likelihood of `0.25^290 ≈ 0`. The cloud is forced onto poses with very tight beam-to-wall agreement.
- **Large σ_hit (e.g., 200 mm).** Likelihood field is broad and shallow. Every reasonable pose looks similar; the cloud cannot tighten.
- **GODO's choice: 50 mm (`AMCL_SIGMA_HIT_M = 0.050`) for steady-state.** A trade-off between the C1 LiDAR's ±30 mm intrinsic error and the typical map-vs-reality misalignment.

The empirical sweep evidence (`project_amcl_sigma_sweep_2026-04-29.md`):

| σ_hit | Convergence rate (across 10 trials) | Notes |
|---|---|---|
| 0.050 | 0/10 | Default. Cloud collapses on multimodal scenes; likelihood too peaked. |
| 1.0 | 2/10 | Single basin found; rest still don't converge. |
| 0.2 | 9/10 | Best — 9 trials converge, but **3 land in different basins** (multimodal symptom). |
| 0.1 → 0.2 | Cliff | Convergence rate jumps sharply between σ=0.1 and σ=0.2. |

This drove the **σ_hit anneal schedule** (Track D-5; see §27): start wide (σ_hit = 0.2) so all hypotheses get nontrivial likelihood, then narrow (σ_hit = 0.1, then σ_hit = 0.05) to discriminate between basins. Each phase rebuilds the likelihood field at the new σ_hit (`build_likelihood_field` is called once per phase). The cloud carries between phases — it's the same `Amcl` instance, just `set_field`-pointed at the new field.

Live mode does NOT anneal — it stays at the operator's locked `cfg.amcl_sigma_hit_m` value (default 0.050 m) because Live's cloud has already been narrowed by OneShot, and the per-Live-tick budget is tight.

---

# Part VI — Resampling

## §20. When to resample (effective sample size threshold)

Resample only when the cloud has lost diversity:

```cpp
double sum_sq = 0.0;
for (i = 0..n_) sum_sq += w[i]*w[i];
double n_eff = (sum_sq > 0) ? 1.0/sum_sq : 0.0;
double n_eff_thresh = 0.5 * n_;
if (n_eff < n_eff_thresh) {
    resample(...);
}
```

`amcl.cpp:243-257`. The `0.5` threshold is the textbook AMCL choice (Probabilistic Robotics, Ch. 4.2.4). Bumping it (e.g., to 0.7) causes more aggressive resampling, which can collapse cloud diversity faster than jitter can rebuild it (particle deprivation risk). Dropping it (e.g., to 0.3) leaves the cloud running with very few effective particles for many steps, increasing weight-variance in the output mean.

`kResampleNeffFrac = 0.5` is currently a `constexpr` in `amcl.cpp` (file-local). Tier-2 promotion is on the issue list (`issue#22` if KLD-sampling lands; until then it stays Tier-1).

The conditional resample protects against **resampling-induced collapse**: if every step resampled, the cloud would lose diversity each tick. By only resampling when N_eff drops, we keep diversity for free in healthy ticks.

---

## §21. Low-variance (systematic) resampling

`resample()` (`scan_ops.cpp:116-164`) implements **low-variance / systematic resampling**:

```cpp
// (1) Compute cumulative weights.
double total = 0;
for (i = 0..n) cumsum[i] = (total += w[i]);
// (2) Single uniform random draw.
double step = total / n;
double r0   = rng.uniform() * step;   // u ∈ [0, step)
// (3) n equally-spaced steps along the cdf.
for (k = 0..n) {
    double u = r0 + k*step;
    while (i+1 < n && cumsum[i] < u) ++i;
    out[k] = in[i];
}
```

Why systematic over multinomial?

| Resampler | Variance | Cost | Notes |
|---|---|---|---|
| **Multinomial** (n independent uniform draws) | High variance — same particle may get drawn 0 or many times | n × log n with binary search; n × n with linear search | Simple, but provably worst variance among standard resamplers. |
| **Systematic** (1 uniform draw, n equally-spaced taps) | Lowest variance among unbiased resamplers (proved by Hol et al. 2006) | O(n) — single linear pass | GODO uses this. |
| **Stratified** | Slightly higher variance than systematic, simpler | O(n) | Compromise; not used here. |
| **Residual** | Two-stage: floor(n·w_i) deterministic, residual multinomial | O(n) | Implementation gnarlier; rarely worth it. |

The systematic resampler is **deterministic up to a single uniform draw `r0`**, so its randomness footprint is minimal — useful for the bit-equality story (§30): a fixed RNG stream produces a fixed resample.

**Defensive guards** (`scan_ops.cpp:135-148`): the resampler validates input weights (non-negative, finite) and the total (positive). On violation it throws — the caller (`Amcl::step`) doesn't have a recovery path because a violation indicates a likelihood model bug, not a runtime condition.

---

## §22. Numerical stability — the log-sum-exp pattern

`evaluate_scan` returns `exp(Σ log p_i)` — a positive scalar that might be very small (e.g., 290 beams × log(0.001) per beam ⇒ exp(-2000) which is `0.0` in IEEE 754 double). Naive summation of these values across the cloud would lose all the information about which particles are slightly better than which.

`Amcl::normalize_weights` (`amcl.cpp:138-179`) handles this with the standard **log-sum-exp** trick:

```cpp
// Convert weight (linear) → log-weight, find max.
double max_log = -inf;
for (i = 0..n) {
    front_[i].weight = log(front_[i].weight);   // re-derive log
    if (front_[i].weight > max_log) max_log = front_[i].weight;
}
if (!isfinite(max_log)) {  // every particle had weight 0
    // Degenerate fallback: reset to uniform; next step will have informative weights
    for (i = 0..n) front_[i].weight = 1.0/n;
    return;
}
// Subtract max_log, exp back to linear; sum.
double sum = 0;
for (i = 0..n) {
    front_[i].weight = exp(front_[i].weight - max_log);
    sum += front_[i].weight;
}
// Normalize.
for (i = 0..n) front_[i].weight /= sum;
```

Key insight: `Σ exp(x_i)` and `exp(x_max) · Σ exp(x_i - x_max)` are mathematically equal; the second form is **numerically stable** because every `exp(x_i - x_max) ∈ (0, 1]` cleanly representable in double precision. We pay one max-find pass + one subtract per particle for full numerical safety.

The "every particle had weight 0" branch is a pure defensive fallback — it should not happen in healthy operation, but if it does (e.g., scan totally off-map), resetting to uniform lets the next step rescue things rather than throwing.

---

# Part VII — Output

## §23. Linear weighted mean (x, y)

`Amcl::weighted_mean()` (`amcl.cpp:317-334`) computes the cloud's **weighted mean pose**:

```cpp
double wsum = 0, wx = 0, wy = 0;
for (i = 0..n) {
    wsum += w[i];
    wx   += pose[i].x * w[i];
    wy   += pose[i].y * w[i];
}
out.x = wx / wsum;
out.y = wy / wsum;
out.yaw_deg = circular_mean_yaw_deg(...);
```

Linear x and y use the obvious formula. **The summation order is sequential, in particle index order.** This is critical for the issue#11 fork-join bit-equality proof (§30): if `weighted_mean` ever became a parallel reduction, it could re-order summation, and the IEEE 754 floating-point sum is **not associative** — different orders produce bit-different doubles. The CODEBASE.md `(s)` invariant explicitly forbids parallelizing `weighted_mean` without re-deriving the proof.

---

## §24. Circular mean (yaw)

Yaw is **angular** — averaging it linearly is wrong. The classic counter-example: angles `[359°, 1°]` should average to `0°`, not `180°`. 

The fix: convert each angle to a unit 2D vector, average those vectors, take `atan2`:

```
mean_yaw = atan2(Σ w_i sin(yaw_i), Σ w_i cos(yaw_i))
```

GODO's `circular_mean_yaw_deg` (in `circular_stats.cpp`) implements this. The **circular standard deviation** is similarly defined via the resultant vector's magnitude (Mardia & Jupp 2000):

```
R = (1/Σw) sqrt((Σ w_i sin yaw_i)² + (Σ w_i cos yaw_i)²)
σ_circ = sqrt(-2 ln R) [in radians, then convert to degrees]
```

When `R → 1` (cloud is tight in yaw) the std → 0; when `R → 0` (cloud is uniformly spread on the circle) the std → ∞. The convergence threshold `cfg.amcl_converge_yaw_std_deg = 0.3` is in this circular-std unit, so `0.3` means "tighter than 0.3° in circular spread" — sub-degree.

---

## §25. Convergence detection

The result of `Amcl::step` is tagged as **converged** when:

```cpp
res.converged = (res.xy_std_m    < cfg.amcl_converge_xy_std_m)        // 0.015 m default
             && (res.yaw_std_deg < cfg.amcl_converge_yaw_std_deg);    // 0.3°  default
```

`Amcl::converge()` then loops on `step` until **converged for at least one tick AFTER the cloud has had a chance to react to the sensor model** — concretely, it requires `iter >= 2` (i.e., already 3 step calls made) before honoring `converged`. This guards against declaring convergence on the seed cloud's natural variance before the sensor model has reshaped it.

The thresholds are TOML-tunable (Tier-2). They are **tighter than the operator's accuracy budget** (1-2 cm UE budget vs 1.5 cm convergence threshold) on purpose: if AMCL declares convergence at 1.5 cm, the actual single-shot RMS is well within the 1-2 cm operator target. The operator can loosen them via TOML if a particular studio map is too noisy to converge to 1.5 cm; the convergence flag will then fire earlier at the cost of a slightly noisier output pose.

---

# Part VIII — GODO's architecture choices

## §26. Two operating modes: OneShot and Live

GODO runs AMCL in **two operator-triggered modes**, both invoked via the SPA / GPIO button (CLAUDE.md §1, table of operating modes):

| Mode | Trigger | Particle counts | Anneal? | Hint? | Cadence | Goal |
|---|---|---|---|---|---|---|
| **OneShot** | Operator: GPIO button or `/api/calibrate` | seed_global N=5000 → seed_around N=500 (per phase) | Yes — Track D-5 σ-anneal 0.2/0.1/0.05 × 10 iters | No (or rare; falls back to seed_global) | Once per session OR after base move | High accuracy (≤ 1-2 cm RMS) "calibrate" |
| **Live** | Operator: `/api/live` toggle | seed_around N=500 only | No (uses Live's locked σ_hit=0.05) | Yes — pipelined hint from previous Live pose | ~10 Hz while toggled on | Coarser tracking; smoother fed at 60 Hz |

OneShot's accuracy comes from **multiple iterations under successively-narrower σ_hit** — the σ-anneal schedule. Live's tracking comes from a **strong pose hint per scan** that keeps the cloud focused on the current basin.

The cold writer (`production/RPi5/src/localization/cold_writer.cpp`) sequences both modes; AMCL itself is mode-agnostic — `class Amcl` exposes `step` / `converge` / `seed_global` / `seed_around` / `set_field` and the cold writer assembles them.

---

## §27. σ_hit anneal schedule (Track D-5)

For OneShot, the cold writer runs an anneal:

```
phase 0: build_likelihood_field(σ_hit=0.2)  → run anneal_iters_per_phase=10 step()s  → carry cloud
phase 1: build_likelihood_field(σ_hit=0.1)  → run anneal_iters_per_phase=10 step()s  → carry cloud
phase 2: build_likelihood_field(σ_hit=0.05) → run anneal_iters_per_phase=10 step()s  → done
```

`AMCL_SIGMA_HIT_SCHEDULE_M = "0.2 0.1 0.05"` (`config_defaults.hpp:107-108`) and `AMCL_ANNEAL_ITERS_PER_PHASE = 10` (`config_defaults.hpp:111`). The cloud **persists across phases** — it's the same `Amcl` instance, just rebound to a new likelihood field via `set_field` (`amcl.cpp:32-34`).

What does the anneal actually do?

- **Phase 0 (wide σ_hit = 0.2 m).** The likelihood field is broad and shallow; even particles 200 mm off the true pose get nontrivial likelihood. The cloud is allowed to migrate freely between hypothesis basins. With 9/10 convergence rate (per 2026-04-29 sweep) but multimodal occupancy (3 basins out of 9 land in the wrong place), this phase is **basin selection** by raw mass.
- **Phase 1 (medium σ_hit = 0.1 m).** Likelihood field is somewhat sharper. Particles in wrong basins start losing weight against particles in the right basin; resampling consolidates onto the dominant mode.
- **Phase 2 (narrow σ_hit = 0.05 m).** Likelihood field is sharp; only particles within ~50 mm of true pose retain weight. Cloud tightens to convergence (`xy_std < 1.5 cm`).

This is **simulated annealing applied to particle filtering**: the energy landscape (negative log-likelihood) is gradually sharpened so the filter doesn't get stuck in shallow local minima.

The anneal is **OneShot-only** because Live has neither budget (one scan = one tick at 10 Hz) nor need (the carry hint already keeps the cloud focused). Live runs at the operator's locked `cfg.amcl_sigma_hit_m` (default 0.05 m).

Memory: `project_amcl_sigma_sweep_2026-04-29.md` has the full empirical justification for this schedule.

---

## §28. Pipelined-hint Live mode

Live mode uses the **previous Live tick's converged pose as a hint for the next tick**. This is the "pipelined-hint" architecture (`AMCL_LIVE_CARRY_POSE_AS_HINT = 1` default; `cold_writer.cpp` `run_live_iteration_pipelined` + `converge_anneal_with_hint`).

The flow per Live tick:

1. Take `last_pose` from the previous Live tick.
2. Check `last_pose_seq` is fresh (i.e., previous tick actually produced a converged pose).
3. `seed_around(last_pose, hint_sigma_xy=0.5 m, hint_sigma_yaw=20°)` to populate a cloud that wraps the previous pose with a generous Gaussian.
4. Run a **mini-anneal** with σ_live_carry = 0.05 m (`AMCL_LIVE_CARRY_SIGMA_XY_M = 0.050`) and `live_carry_schedule_m` (~3 phases × 10 iters/phase).
5. Output the converged pose; deadband-filter; publish.

The hint σ pair `(0.5 m, 20°)` is **operator-locked semantics**: the hint is a "strong command" — AMCL should converge **inside** the hint cloud, not redirect away from it. If the hint says `(2.0, 3.0, 45°)` and the scan-truth is `(2.1, 3.05, 47°)`, AMCL converges to the scan-truth within the hint's basin. If the hint is grossly wrong (operator cocked-up), the cloud's likelihood collapses and the operator must re-issue an OneShot calibrate.

This is why `project_hint_strong_command_semantics.md` is operator-locked: future AMCL improvements that "broaden the search basin to be more forgiving" must be **opt-in / gated** so the strong-command semantics are preserved by default.

The hint sigma defaults `(0.50 m, 20°)` are wider than the per-step Live jitter `(0.015 m, 1.5°)` — the hint defines the cloud's **search basin** at tick entry, while jitter is per-step diversity refresh.

---

## §29. issue#11 fork-join particle evaluation pool

Phase-0 instrumentation (PR #96, MERGED 2026-05-06) measured per-component wallclock at the `Amcl::step` granularity:

| Stage | p50 (5-min, 2166 scans, sequential) | Share |
|---|---|---|
| evaluate_scan loop | 94.85 ms | **69.7%** |
| LF rebuild | 39.58 ms | 29.1% |
| jitter / normalize / resample | <1 ms | 0.7% |

→ `evaluate_scan` (the per-particle sensor likelihood loop) was the dominant cost. **Issue#11** parallelized it by partitioning the per-particle loop across 3 worker threads pinned to CPU 0/1/2 (CPU 3 stays RT-only):

```cpp
// amcl.cpp:215-227 (issue#11 fork-join hook)
auto eval_one = [this, &beams](std::size_t i) {
    front_[i].weight = evaluate_scan(front_[i].pose,
                                     beams.data(), beams.size(),
                                     *field_);
};
bool dispatched = false;
if (pool_ != nullptr) {
    dispatched = pool_->parallel_for(0, n_, eval_one);
}
if (!dispatched) {
    // Either pool == nullptr OR parallel_for timed out; run sequentially.
    for (std::size_t i = 0; i < n_; ++i) eval_one(i);
}
```

Workers each write to a **partition-disjoint subrange** of `front_[i].weight` — index 0..(n/3) for worker 0, n/3..(2n/3) for worker 1, etc. No worker reads what another writes; race-freedom by partitioning, not by locking.

Empirical post-fix measurement (5-min, 2989 scans, this session 2026-05-06 KST):

| Stage | Sequential baseline | Post-fix (Option C) | Speedup |
|---|---|---|---|
| evaluate_scan | 94.85 ms | 45.11 ms | **2.10×** |
| LF rebuild | 39.58 ms | 40.03 ms | 1.00× (issue#19 territory) |
| TOTAL | 136.15 ms | 86.80 ms | **1.57×** |
| Cold-path Hz | 7.34 Hz | **11.52 Hz** | **+57%** |

That's the 10 Hz LiDAR cleared with margin. Issue#19 (parallelize EDT row/col passes) is the next target — that lifts to projected ~21 Hz and clears the 60 Hz UE smoother demand cleanly.

---

## §30. Bit-equality guarantee under parallelism

A subtle but critical property: **the parallel evaluation produces bit-exactly the same `Amcl::step` output as the sequential evaluation, given the same RNG seed and inputs.** Proven in plan §3.6 + pinned by `tests/test_amcl_parallel_eval.cpp::case 1` via `memcmp` on IEEE 754 representations of `result.pose.x / .y / .yaw_deg / .xy_std_m / .yaw_std_deg`.

The proof has 5 steps:

1. **Inputs are identical.** Same beams, same particles' (pose, weight), same RNG state. The fork-join only partitions `evaluate_scan` — it does not touch `jitter_inplace`, `normalize_weights`, or `resample`, all of which are sequential and deterministic.
2. **`evaluate_scan` is a pure function.** Given `(pose_i, beams, field)`, it produces the same `weight` independent of which thread called it. No global state, no time-dependent read.
3. **Partition is disjoint.** Worker `w` writes only to `front_[i].weight` for `i ∈ [w * n/W, (w+1) * n/W)`. No two workers write the same index. So the post-eval `front_[]` is bit-identical to the sequential post-eval `front_[]`.
4. **`weighted_mean` is sequential summation in i-order.** `wsum += w[i]; wx += pose[i].x * w[i]; ...` — the order of additions is fixed, and IEEE 754 `+` is order-sensitive but deterministic given an order. So the same `front_[]` produces the same `weighted_mean`.
5. **`resample` consumes the same `front_[]` and the same RNG state**, so `back_[]` post-resample is identical too.

Therefore `result.pose / .xy_std / .yaw_std` are bit-identical. The bit-equality test **would fail** if any of the 5 steps broke — making it a strong invariant guard.

This is why the CODEBASE.md `(s)` invariant says, in bold: **do NOT parallelize `weighted_mean` without re-deriving the IEEE 754 ordering proof and updating the test**. Parallel reduction breaks step 4 and breaks bit-equality even if it preserves mathematical equality (within rounding).

---

# Part IX — Tuning cheat sheet

## §31. Parameter table with semantics

All TOML / env / CLI tunable. Defaults from `production/RPi5/src/core/config_defaults.hpp`:

### Core sizing

| TOML key | Default | Semantic | When to change |
|---|---|---|---|
| `amcl.particles_global_n` | 5000 | First-tick (seed_global) particle count | Larger → better global coverage on map of 100+ m². Smaller → faster first-tick but risk missing distant basins. |
| `amcl.particles_local_n` | 500 | Per-step (seed_around / Live) particle count | 500 is empirically sufficient for hint-seeded clouds. Going below 200 risks particle deprivation. |
| `amcl.max_iters` | 25 | OneShot `converge()` upper bound | Anneal × phases × iters_per_phase usually drives the actual count; this is the safety ceiling. |

### Sensor model

| TOML key | Default | Semantic | When to change |
|---|---|---|---|
| `amcl.sigma_hit_m` | 0.050 | Likelihood field Gaussian σ for steady-state Live | Wider on noisy/older maps; narrower on freshly-mapped studios. |
| `amcl.sigma_hit_schedule_m` | "0.2 0.1 0.05" | OneShot anneal schedule | Add a wider phase (e.g. "0.5 0.2 0.1 0.05") if the studio has very symmetric features. |
| `amcl.anneal_iters_per_phase` | 10 | Steps per anneal phase | Increase to 15-20 for very ambiguous studios; decrease to 5 if early-exit fires reliably. |
| `amcl.range_min_m` / `range_max_m` | 0.15 / 12.0 | Beam range filter | Below 15 cm = LiDAR's own housing; > 12 m = quality-degraded. Adjust per LiDAR datasheet. |
| `amcl.downsample_stride` | 2 | Keep every Nth beam | Larger → faster but lower angular resolution. C1 has ~580 raw beams → stride 2 keeps ~290. |

### Motion model

| TOML key | Default | Semantic | When to change |
|---|---|---|---|
| `amcl.sigma_xy_jitter_m` | 0.005 (5 mm) | OneShot per-step xy jitter σ | OneShot = static; very small. |
| `amcl.sigma_yaw_jitter_deg` | 0.5 | OneShot per-step yaw jitter σ | |
| `amcl.sigma_xy_jitter_live_m` | 0.015 (15 mm) | Live per-step xy jitter σ | Sized for crane base ~30 cm/s. |
| `amcl.sigma_yaw_jitter_live_deg` | 1.5 | Live per-step yaw jitter σ | |

### Hint / carry

| TOML key | Default | Semantic | When to change |
|---|---|---|---|
| `amcl.hint_sigma_xy_m_default` | 0.50 (50 cm) | Hint cloud xy spread for `seed_around(hint, ...)` | Operator's "strong command" — wide enough to cover hint estimation error, narrow enough for sub-second convergence. |
| `amcl.hint_sigma_yaw_deg_default` | 20.0 | Hint cloud yaw spread | Same as above. |
| `amcl.live_carry_pose_as_hint` | 1 | Use last_pose as next-tick hint? | Set to 0 to fall back to global-reseed every tick (very wasteful; for debugging only). |
| `amcl.live_carry_sigma_xy_m` | 0.050 | Live carry mini-anneal σ | |
| `amcl.live_carry_sigma_yaw_deg` | 5.0 | Live carry mini-anneal yaw σ | |

### Convergence + RT

| TOML key | Default | Semantic | When to change |
|---|---|---|---|
| `amcl.converge_xy_std_m` | 0.015 (1.5 cm) | Convergence threshold (xy spread) | Tighter → more iterations / risk non-convergence in hard scenes. |
| `amcl.converge_yaw_std_deg` | 0.3 | Convergence threshold (circular yaw spread) | Sub-degree by default. |
| `amcl.yaw_tripwire_deg` | 5.0 | Origin-yaw drift warning threshold | Triggers stderr "Studio base may have rotated" log (non-blocking). |
| `amcl.parallel_eval_workers` | 3 | Issue#11 fork-join workers (1 = rollback) | Set to 1 for deterministic rollback to pre-issue#11 sequential. |

---

## §32. Empirical sweep evidence

The σ_hit cliff and the σ_hit_schedule decision rest on a measured 10-trial sweep on 2026-04-29 KST in TS5 (chroma studio). See `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` for the data and `production/RPi5/SYSTEM_DESIGN.md` §6.3 for the design narrative.

The Phase-0 cold-path breakdown (eval ≈ 70%, LF rebuild ≈ 29%) was measured on 2026-05-06 KST per PR #96 instrumentation; numbers in §29 above. See `.claude/tmp/phase0_results_5min_20260506_095949.md`.

The issue#11 fork-join lift (7.34 → 11.52 Hz, +57%) was measured on 2026-05-06 KST post range-proportional deadline fix (PR #99).

---

# Part X — Future improvements (open issues)

## §33. Roadmap by issue number

These integers are reserved (CLAUDE.md §6 issue labelling, NEXT_SESSION.md):

- **issue#13** — *Distance-weighted likelihood*. Down-weight beams within `r_cutoff` of the LiDAR (where the C1's near-field returns are dominated by housing reflections). Surgical change to `evaluate_scan` body. Standalone, single-knob; orthogonal to issue#11.
- **issue#19** — *EDT 2D Felzenszwalb 3-way parallelization*. Reuses issue#11's `ParallelEvalPool` primitive with an extended `parallel_for_with_scratch<S>` API for per-worker `(v, z)` scratch buffers. Projected lift: 11.52 → ~21 Hz total (LF rebuild 40 → ~14 ms).
- **issue#20** — *Track D-5-P (deeper σ schedule, staggered tier)*. Push the OneShot anneal one phase deeper (σ_hit = 0.025 m) for chroma studios with very fine details. Requires re-evaluating the σ_hit cliff at the new bottom.
- **issue#21** — *NEON/SIMD vectorization of `evaluate_scan` per-beam loop*. The Pi 5 Cortex-A76 has NEON; the cos/sin transforms and bilinear coordinate computation are 4-double-vectorizable. Projected ~2-3× per-beam speedup, orthogonal to fork-join (still benefits even after issue#11).
- **issue#22** — *KLD-sampling adaptive N*. The "A" in AMCL — bring it home. Reduce N during steady-state Live (often N≈100 is sufficient once the cloud has tightened). Big payoff potentially exceeds issue#11+#19 combined, but adds intricate machinery.
- **issue#23** — *LF prefetch / gather-batch on `evaluate_scan` lookups*. The dominant cache-miss cost in `evaluate_scan` is the random LF cell access. `__builtin_prefetch` 4-8 beams ahead, OR processing 4 particles' i-th beam in lockstep. ~1.5-2× single-core speedup. Very orthogonal.

There is no current plan for the AMCL-classical *random sample injection* (textbook AMCL feature §10) — operator-locked semantics around the hint replace it.

---

# Part XI — References

1. **Probabilistic Robotics** — Sebastian Thrun, Wolfram Burgard, Dieter Fox. MIT Press 2005. Chapters 4 (particle filters), 6.4 (likelihood field), 8 (MCL/AMCL). The book that defines the field; AMCL as we know it lives in §8.3.
2. **KLD-sampling for adaptive particle counts** — Dieter Fox. *Adapting the Sample Size in Particle Filters Through KLD-Sampling*, IJRR 2003. The "A" in AMCL.
3. **Felzenszwalb-Huttenlocher Distance Transform** — Pedro F. Felzenszwalb & Daniel P. Huttenlocher. *Distance Transforms of Sampled Functions*, Theory of Computing 2012 (technical report 2004). The 1D linear-time EDT used in `likelihood_field.cpp`.
4. **Resampling variance comparison** — Jeroen D. Hol, Thomas B. Schön, Fredrik Gustafsson. *On Resampling Algorithms for Particle Filters*, Workshop on Nonlinear Statistical Signal Processing 2006. Proves systematic resampling has the lowest variance among unbiased single-pass resamplers.
5. **ROS amcl package** — Brian Gerkey et al., 2008+. The reference open-source AMCL implementation that GODO's API mirrors (without inheriting KLD-sampling or sample injection).
6. **Mardia & Jupp** — *Directional Statistics*, Wiley 2000. Chapter 2: circular mean and circular standard deviation, the math behind §24.
7. **Internal**:
   - `production/RPi5/SYSTEM_DESIGN.md` — backend SSOT including AMCL, Track D-5, RT topology.
   - `doc/issue11_design_analysis.md` — the issue#11 fork-join design rationale.
   - `production/RPi5/CODEBASE.md` — invariants `(a)..(s)` for the localization module.
   - `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md` — empirical σ_hit sweep.
   - `.claude/memory/project_pipelined_compute_pattern.md` — the broader pattern of which the AMCL pipelined-hint Live mode is the first instance.
   - `.claude/memory/project_hint_strong_command_semantics.md` — operator-locked hint semantics.
   - `.claude/memory/project_amcl_yaw_metadata_only.md` — why grid origin yaw is metadata-only and not a sensor input.
   - `.claude/memory/project_calibration_alternatives.md` — the family of recovery / re-calibration strategies and why pose-hint won.

---

*End of document. 853 lines. Last updated 2026-05-06 KST (twenty-eighth-session, post-issue#11 deploy + Phase-0 5-min capture).*
