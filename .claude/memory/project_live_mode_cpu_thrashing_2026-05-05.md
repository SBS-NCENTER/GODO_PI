---
name: Live mode cold-path single-thread CPU thrashing observation (2026-05-05)
description: While Live mode is active on news-pi01, ONE cold-path thread sustains 40-60% CPU on a single core; CFS migrates that thread between cores 0/1/2 every few seconds, producing the operator-observed "one core spikes to 100%, then another core takes over" pattern. RT hot path (CPU 3 isolated) stays at 0.25% — hot path is fine. issue#11 (Live pipelined-parallel multi-thread) is the prepared answer; the empirical CPU data captured this session motivates re-prioritising it.
type: project
---

## What was measured (2026-05-05 16:35 KST, news-pi01, branch main post-PR #93)

Live mode active. `godo_tracker_rt` PID 3438264. 10 threads:

| TID | cpus_allowed | priority | utime/stime | role (inferred) |
|---|---|---|---|---|
| 3438264 | 0-3 | 20 | 2/2 | main / orchestrator |
| 3438305 | 0-3 | 20 | 0/0 | idle worker |
| 3438306 | 0-3 | 20 | 0/0 | idle worker |
| **3438307** | **0-3** | **20** | **16138/37** | **AMCL Live cold-path kernel — sustained 40-60% CPU, state=R (running)** |
| 3438308 | 0-3 | 20 | 0/3 | idle worker |
| 3438309 | 0-3 | 20 | 7/14 | low-cost periodic (LiDAR scan publisher?) |
| **3438312** | **3** | **-51** | **5/32** | **RT hot path (SCHED_FIFO, CPU 3 isolated) — 0.25% only ✓** |
| 3438313 | 0-3 | 20 | 1/1 | idle worker |
| 3438338 | 0-3 | -2 | 46/42 | nice-elevated periodic (diag/SSE producer?) |
| 3438339 | 0-3 | -2 | 23/104 | nice-elevated periodic (jitter_seq/amcl_rate publisher?) |

`top -H` 5 samples × 2s confirmed TID 3438307 holding 40-60% CPU continuously while every other thread sits at 0%. utime ratio (16138 / (16138+37) = 99.8%) — pure compute, not syscall-heavy. Particle filter loop is the load.

Core migration pattern over 5 samples:
- Sample 1-4: TID 3438307 last_cpu=2 (stayed on core 2)
- Sample 5: TID 3438307 last_cpu=1 (migrated to core 1)

CFS keeps the thread off core 3 (where the RT thread parks) and oscillates between cores 0/1/2. This produces the operator-observed "one core 100%, then another core 100%" pattern — same single thread, just rescheduled.

System load: load average 7.35 (4-core system) — high-ish but mostly absorbed by the cold-path thread.

## What this means for issue#11

Issue#11 (Live pipelined-parallel multi-thread) plan exists at `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` (Round 1 plan + Mode-A round 1 fold). The plan splits the AMCL likelihood-eval loop across multiple threads (Wave A: 4-way parallel particle evaluation; Wave B: deeper).

**Empirical motivator now captured**: the single-thread bottleneck is NOT theoretical — it's measured. A 4-way parallel implementation would (ideally) drop single-core peak from 50-60% → ~15% per core × 4 cores. RPi 5 thermal headroom on prolonged 50% single-core load is the operational concern operator flagged ("장시간 운용 부담").

issue#11 was previously paused awaiting issue#26 (cross-device latency measurement tool) for end-to-end verification. Operator may now want to re-prioritize: re-run issue#11 plan with this CPU thrashing observation as the load-bearing motivation, decoupled from the issue#26 timing baseline.

## How to reproduce the measurement

```bash
PID=$(pgrep -f "/opt/godo-tracker/godo_tracker_rt" | head -1)
# Per-thread utime/stime + last_cpu over time
for i in $(seq 1 10); do
  for tid in $(ls /proc/$PID/task/); do
    awk -v tid=$tid '{printf "TID=%s state=%s last_cpu=%s utime=%s stime=%s prio=%s\n", tid, $3, $39, $14, $15, $18}' /proc/$PID/task/$tid/stat
  done
  echo "---"
  sleep 1
done

# Per-thread CPU% via top
top -H -b -n 1 -p $PID | tail -16
```

`pidstat` is NOT installed on news-pi01 — use the /proc/stat reading or `top -H` instead.

## Cross-references

- `project_pipelined_compute_pattern.md` — the prepared design pattern.
- `project_cpu3_isolation.md` — RT hot path isolation invariant (confirmed working: TID 3438312 stays on CPU 3, low utilization).
- `.claude/tmp/plan_issue_11_live_pipelined_parallel.md` — full plan with Mode-A round 1 fold.
- `project_amcl_sigma_sweep_2026-04-29.md` — particle count and σ schedule context (5000 particles in global init phase).

## Caveats

- The initial 8-second measurement window showed only one cold-path thread at 40-60% CPU. The longer-term behaviour is worse (next bullet).
- The 99.8% user-mode ratio rules out syscall thrash; whatever optimization issue#11 brings is purely compute-parallelism.

## Long-running follow-up (2026-05-05 ~18:00 KST, ~1-2 hours after initial measurement)

**Operator observed ALL FOUR cores pegged at 100% — including CPU 3 (which should be RT-isolated for the hot path).** This is a significant escalation from the early-window measurement. Implication: under sustained Live mode operation, the cold-path AMCL kernel's load grows beyond what one core can absorb, the CFS spreads work across all available cores including CPU 3, and the RT hot path's isolation guarantee breaks down (or at least gets contended).

Possible mechanisms:
- Particle-cloud growth: as Live tracking accumulates over time, the operating particle count or σ-schedule may grow, increasing per-tick compute.
- Memory pressure / cache thrashing: 86 MB peak (per `systemctl status` earlier in this session) is small, but cache-line bouncing across 4 cores could be a factor.
- Backlog buildup: if cold path can't service scans at ~10 Hz, queueing causes the cold thread to never sleep → CFS migrates it more aggressively → RT thread sees more contention.
- `isolcpus=` kernel parameter may not be applied on this host. Need to check `cat /proc/cmdline` next session.

This makes issue#11 even more urgent than the initial measurement suggested. It also raises a new question for `project_cpu3_isolation.md`: is the SCHED_FIFO + CPU 3 affinity enough on its own, or does the project need full `isolcpus=3 nohz_full=3 rcu_nocbs=3` kernel cmdline to actually reserve the core?

Diagnostic to run at next session start (Live mode active, ~30+ min uptime):
```bash
cat /proc/cmdline                         # check for isolcpus / nohz_full
cat /sys/fs/cgroup/cpu*/cpu.idle 2>/dev/null
PID=$(pgrep -f "/opt/godo-tracker/godo_tracker_rt" | head -1)
top -H -b -n 5 -d 2 -p $PID | tail -100
mpstat -P ALL 2 5 2>/dev/null            # if available
for i in 1 2 3 4 5; do
  for tid in $(ls /proc/$PID/task/); do
    awk -v tid=$tid '{printf "TID=%s state=%s last_cpu=%s utime=%s stime=%s prio=%s\n", tid, $3, $39, $14, $15, $18}' /proc/$PID/task/$tid/stat
  done
  echo "---"
  sleep 2
done
```

This will distinguish: (a) one cold thread saturated all cores (load spread by CFS) vs (b) MULTIPLE cold threads now busy vs (c) RT thread's CPU 3 truly contended (priority inversion or kernel-task interference).
