# Track D-5 — Post-anneal HIL convergence test (TS5)

> Operator-driven hardware-in-the-loop test for the Track D-5
> coarse-to-fine sigma_hit annealing fix on news-pi01.
>
> Protocol: see `production/RPi5/doc/convergence_hil.md` (run procedure +
> truth-pose extraction + acceptance gate).
>
> Pre-Track-D-5 baseline (post-Track-D-3, pre-anneal, σ=0.05): k_post =
> 0/10 (per `.claude/memory/project_amcl_sigma_sweep_2026-04-29.md`,
> 21:00 KST sweep).
>
> Post-Track-D-5 expected gate: **k_post ≥ 8 / 10** with each converged
> pose's xy_err < 1.0 m (per
> `production/RPi5/doc/convergence_hil.md::Track D-5 update`).

---

## Run log

### YYYY-MM-DD HH:MM KST — fix/track-d-5-sigma-annealing — <git sha>

- LiDAR floor location: (x_truth = ___, y_truth = ___) m
- Yaw truth: ___ °
- Map: 04.29_v3.{pgm,yaml} (height 365 px, resolution 0.050 m/cell)
- Tracker SHA: <git rev-parse HEAD>
- Tracker config (active schedule):
  - `amcl.sigma_hit_schedule_m = "1.0,0.5,0.2,0.1,0.05"`
  - `amcl.sigma_seed_xy_schedule_m = "-,0.10,0.05,0.03,0.02"`
  - `amcl.anneal_iters_per_phase = 10`
- Attempts: 10
- Successes: ___ / 10
- Median pose error: ___ m
- Median yaw error: ___ °
- Median per-OneShot wall-clock: ___ ms
- Screenshot: ___
- Decision: PASS / MARGINAL / FAIL
- Notes: ___
