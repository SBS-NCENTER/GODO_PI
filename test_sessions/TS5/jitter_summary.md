# TS5 / 2026-04-25 — godo_jitter RT measurements (news-pi01)

> **Session purpose**: Measure the RPi 5 RT scheduling jitter for the
> 59.94 Hz hot-path send loop, **phased through the four-layer
> isolation stack** so each layer's contribution stays auditable.
> Compared against the SYSTEM_DESIGN.md §6.2 design goal (p99 < 200 µs).
>
> **TS5 = 부조정실 5** (Sub-Control Room 5), paired with **ST-5**
> (Studio 5). The RPi 5 (`news-pi01`) is deployed in TS5; the SHOTOKU
> crane + camera + LiDAR live in ST-5; cable runs between the two
> rooms. All GODO measurements collected at this site go under
> `<repo-root>/test_sessions/TS5/<topic>.md`, regardless of which of
> the two rooms physically holds the sensor.

---

## Host

| Field | Value |
| --- | --- |
| Hostname | news-pi01 |
| Hardware | Raspberry Pi 5 (revision `d04171`, 8 GB RAM) |
| OS | Debian GNU/Linux 13 (trixie) |
| Kernel | `6.12.75+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.12.75-1+rpt1 (2026-03-11) aarch64` |
| Preemption | voluntary `PREEMPT` (NOT `PREEMPT_RT`) — matches SYSTEM_DESIGN.md design choice |

## RT setup state (steady)

- `setcap cap_sys_nice,cap_ipc_lock+ep` applied to both `godo_tracker_rt` and `godo_jitter`.
- `/etc/security/limits.conf` appended with:
  - `@godo - rtprio 99` + `@godo - memlock unlimited` (production user, group does not exist on this dev host — no-op but kept for production parity)
  - `ncenter - rtprio 99` + `ncenter - memlock unlimited` (the live user on this host)
- Verified inside a fresh PAM session: `ulimit -l = unlimited`, `ulimit -r = 99`.

## Command

```bash
sudo -i -u ncenter \
  /home/ncenter/projects/GODO/production/RPi5/build/src/godo_jitter/godo_jitter \
  --duration-sec 60 --cpu 3 --prio 50
```

- `sudo -i -u ncenter` opens a fresh PAM session so `pam_limits.so` applies the new rlimits.
- `--cpu 3` pins the measurement thread to CPU 3 (the planned isolated hot-path core).
- `--prio 50` sets `SCHED_FIFO` priority 50 (production design value from SYSTEM_DESIGN.md §6.2).
- `--duration-sec 60` runs for one minute → 3596 ticks at the 59.94 Hz period.

`rt::lock_all_memory: skipped` did NOT appear in any run, confirming `mlockall(MCL_CURRENT|MCL_FUTURE)` succeeded across the board.

---

## Phased isolation plan (per `.claude/memory/project_cpu3_isolation.md`)

```text
Step 0 — SCHED_FIFO 50 only                                   ◄ measured
Step 1 — + IRQ pinning (eth/xhci/uart/dma → 0-2, mmc → 0-1)   ◄ measured
Step 2 — + isolcpus=3                                         ◄ measured
Step 3 — + nohz_full=3 + rcu_nocbs=3                          ◄ measured (nohz_full ignored by kernel)
```

## Measurements

All values in nanoseconds. Each run is 3596 ticks over 60 s.

| Step | Run | mean | p50 | p95 | p99 | max | Notes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0 | #1 | 5797.6 | 3617 | 15427 | 29433 | 56807 | First baseline; turned out to be best-case |
| 0 | #2 | 7047.6 | 4285 | 18142 | 33359 | 83948 | Re-measure (IRQ pin command was broken; effectively still Step 0) |
| 1 | #1 | 6985.8 | 4179 | 18267 | 36836 | 100580 | First run after IRQ pin actually applied |
| 1 | #2 | 6915.9 | 4003 | 18214 | 34452 | 71976 | Second run |
| 1 | #3 | 6986.5 | 4122 | 18204 | 34182 | 111309 | Third run |
| 1 | mean of 3 | 6962.7 | 4101 | 18228 | 35157 | 94621 (avg) / 71976-111309 | |
| **2** | **#1** | **2804.8** | **2140** | **6224** | **10851** | **22178** | **First run after `isolcpus=3` reboot + IRQ pin re-applied** |
| **2** | **#2** | **3183.9** | **2419** | **7324** | **11683** | **17434** | Second run |
| **2** | **#3** | **3580.7** | **2754** | **7794** | **13483** | **20454** | Third run |
| **2** | **mean of 3** | **3189.8** | **2438** | **7114** | **12006** | **20022 (avg) / 17434-22178** | |
| **3** | **#1** | **2866.3** | **2038** | **6742** | **13087** | **18597** | **First run after `nohz_full=3 rcu_nocbs=3` reboot. nohz_full=3 was IGNORED — `/sys/devices/system/cpu/nohz_full` does not exist (CONFIG_NO_HZ_FULL=n in stock RPi Debian Trixie kernel). rcu_nocbs=3 likely active.** |
| **3** | **#2** | **2903.9** | **2055** | **7154** | **12477** | **28585** | Second run |
| **3** | **#3** | **2873.5** | **2046** | **6727** | **12573** | **19170** | Third run |
| **3** | **mean of 3** | **2881.2** | **2046** | **6874** | **12712** | **22117 (avg) / 18597-28585** | |

### Reading the numbers

- **Step 0 baseline (run #1) is an outlier on the lucky side.** It was the only single-run snapshot we recorded with that combination of starting cache state and zero co-load events. Step 0 run #2 — same configuration, broken IRQ pin command but still effectively Step 0 — already shows p99=33.4 µs and max=84 µs, which sits inside the Step 1 distribution.
- **Step 1 (IRQ pinning applied) and Step 0 run #2 are statistically indistinguishable on this idle dev host.** Mean / p50 / p95 are within ~1% of each other; p99 differences (33-37 µs) are inside the 60-s sample's expected variance; max is the noisiest metric (72-111 µs across Step 1 runs). The pinning's value will materialize under Phase 5 production load (LiDAR USB + UE network + journald) and over the 8-hour long-run window.
- **Step 2 (`isolcpus=3` added) is dramatic.** Every metric improved 1.7-4.3× over Step 1 mean. Unlike Step 1, Step 2 *did* show measurable benefit on the idle dev host — meaning the host wasn't actually as idle as it looked. Background CPU 3 work (kworker/3, migration/3, rcu_sched/3, ksoftirqd/3, journald, timer tick) was contributing micro-bursts that inflated mean / p99 / max. `isolcpus=3` evicts all of those to CPU 0-2 and leaves CPU 3 with only the RT task — no cache pollution, no context-switch overhead, no scheduler decisions.
- **The max metric showed the biggest improvement (4.3×, 95→22 µs)**. That matches the theoretical prediction: `isolcpus` cuts outlier (tail) latency rather than mean, because outliers are exactly where "rare CPU 3 contention" surfaces.

### Per-step contribution summary (means)

| Metric | Step 0/1 (no isolation) | Step 2 (`isolcpus=3`) | Step 3 (+`rcu_nocbs=3`) | 1→2 | 2→3 |
| --- | ---: | ---: | ---: | ---: | ---: |
| mean | 6.96 µs | 3.19 µs | **2.88 µs** | -54 % | -10 % |
| p50  | 4.10 µs | 2.44 µs | **2.05 µs** | -40 % | -16 % |
| p95  | 18.23 µs | 7.11 µs | **6.87 µs** | -61 % | -3 % |
| p99  | 35.16 µs | **12.01 µs** | 12.71 µs | -66 % | +6 % (noise) |
| max (worst of 3) | 111.31 µs | **22.18 µs** | 28.59 µs | -80 % | +29 % (noise) |

### Where each step's gain comes from

- **Step 1 (IRQ pinning)** had no measurable effect on this idle host (Step 0 #2 ≈ Step 1 mean). Real effect requires production load.
- **Step 2 (`isolcpus=3`) was the dominant gain.** Removed background CPU 3 work (kworker, migration, journald, cache pollution) → mean and tail latency both fell sharply.
- **Step 3 (`rcu_nocbs=3` only — nohz_full was IGNORED)** gave a small mean / p50 gain (10-16 %), but tail (p99 / max) is dominated by **timer tick on CPU 3**, which is exactly what nohz_full was supposed to remove. Without it, Step 3 cannot beat Step 2 on tail latency.

### Stock kernel ceiling (production planning)

`/sys/devices/system/cpu/nohz_full` does not exist on this kernel:
```
Linux 6.12.75+rpt-rpi-2712 #1 SMP PREEMPT Debian 1:6.12.75-1+rpt1
```
That means `CONFIG_NO_HZ_FULL=n` in the stock RPi Debian Trixie kernel build. `nohz_full=3` is silently ignored. The cmdline option is **kept** anyway because it is harmless and signals design intent — a future custom kernel or OS migration with `CONFIG_NO_HZ_FULL=y` will activate it automatically.

**Practical conclusion**: Step 2 is the realistic ceiling on the stock RPi 5 Debian Trixie kernel. p99 = 12 µs sits at 1/17 of the design goal (200 µs). Custom kernel build (for nohz_full) is **not justified** by the cost/benefit ratio for GODO's 1-2 cm accuracy target.

### Results vs. design goal (final, Step 3 = production target)

| Metric | SCHED_OTHER baseline (2026-04-24) | **Step 3 mean (this session)** | Improvement | Design goal |
| --- | ---: | ---: | ---: | --- |
| mean | 110 µs | **2.9 µs** | **38×** | — |
| p50 | 58 µs | **2.0 µs** | **29×** | — |
| p95 | 145 µs | **6.9 µs** | **21×** | — |
| **p99** | **2028 µs** | **12.7 µs** | **160×** | **< 200 µs** ✅ |
| max | 5338 µs | **28.6 µs (worst of 3)** | **187×** | — |

p99 sits at ~1/16 of the design target. Worst max (28.6 µs) consumes 0.17 % of the period budget (16683 µs).

> Step 2 had a slightly better p99/max in this session (worst max 22.2 µs vs 28.6 µs), but the difference is run-to-run noise on a 60 s window with 3 samples. Production target = Step 3 (= Step 2 + rcu_nocbs + cosmetic nohz_full marker), because the cmdline reflects the full intended isolation stack.

## Caveats

- **Idle dev host, not production load.** The host has zero LiDAR traffic (USB unplugged), almost zero network I/O, and a quiet user session. Production adds all of those concurrently. Step 2/3 numbers are a "ceiling" — production loaded numbers will sit somewhere between Step 3 and Step 0.
- **60 s sample window is short** for tail latency. The max metric swings 30-50 % between runs even within a single configuration. Phase 5's 8-hour long-run is what will gate on max with statistical confidence.
- **`CONFIG_NO_HZ_FULL=n` in stock RPi Debian Trixie kernel.** `nohz_full=3` was set on the cmdline but the kernel ignored it (the sysfs file `/sys/devices/system/cpu/nohz_full` does not exist). The cmdline marker is kept for design-intent clarity; effect is zero. Custom kernel build is the only way to activate it, and the cost/benefit does not justify it for GODO's accuracy budget.
- **PL011 / ttyAMA0 IRQ caveat** (verified 2026-04-25): The PL011 driver registers irq 125 lazily — only after a process opens `/dev/ttyAMA0`. Right after a fresh boot, `/proc/irq/125/smp_affinity_list` does not exist and `apply_irq_pin.sh` skips it. This does NOT affect `godo_jitter` runs (it does not open ttyAMA0), but in production `godo_tracker_rt` opens ttyAMA0 at startup and irq 125 will land on CPU 3 by default until pinned. Phase 4-2 must wire the IRQ-pin step into the tracker's startup (or systemd `ExecStartPost=`) to cover this gap. The `irq_inventory.md` doc text describing "registers at probe time" is wrong — pending fix.

## Next

- **Phase 5 long-run** under production load (LiDAR + AMCL + UE traffic): repeat Step 0 → 3 measurement under load. This is the measurement that will actually validate the isolation stack's value, since the idle-host variance floor here masks per-step contributions for Step 1 (and largely for Step 3).
- **Phase 5 Arduino head-to-head**: run an equivalent jitter measurement on the legacy XR_FreeD_to_UDP firmware (Arduino R4 WiFi) for direct comparison.
- **Phase 4-2 IRQ-pin wiring**: cover the PL011 (irq 125) lazy-registration gap by re-applying IRQ pinning at tracker startup (systemd `ExecStartPost=` or in-binary).
- **Phase 4-2 persisted IRQ + isolation**: lift the runtime-only IRQ pinning into a systemd unit so it survives reboot. cmdline cargo (`isolcpus=3 nohz_full=3 rcu_nocbs=3`) is already persisted in `cmdline.txt`.
- **doc fix**: update `production/RPi5/doc/irq_inventory.md` to replace the "PL011 registers at probe time" claim with "PL011 registers irq 125 only when /dev/ttyAMA0 is first opened". Pending — folded with Phase 4-1 closeout commit.
