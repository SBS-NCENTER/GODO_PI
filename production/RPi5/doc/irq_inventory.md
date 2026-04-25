# IRQ Inventory — RPi 5 (news-pi01)

> **Purpose**: enumerate the interrupt sources that can land on CPU 3 (the
> RT hot-path core for `godo_tracker_rt` Thread D) and propose
> `smp_affinity_list` values that keep CPU 3 clean. This is the IRQ-side
> companion to the RT setup in `setup-pi5-rt.sh` + the SCHED_FIFO 50 pin in
> `src/rt/rt_setup.cpp`.
>
> **Captured on**: 2026-04-25, news-pi01 (RPi 5, kernel
> `6.12.75+rpt-rpi-2712`, Debian 13 trixie). Run `scripts/setup-pi5-rt.sh`
> applied; tracker not running at capture time (so userspace-bound IRQs
> like ttyAMA0 do not appear in `/proc/interrupts`).

---

## 1. Topology

The RPi 5's interrupt landscape has TWO controllers in the path that GODO touches:

```
┌──────────────────────────────────────────────────────────┐
│ ARM GICv2 (Cortex-A76 SoC interrupt controller)          │
│  • per-CPU timers, arm-pmu (per-cpu)                     │
│  • mmc0 / mmc1 (SD), spi, codec, v3d                     │
│  • PCIe MSI / aerdrv root                                │
└──────────┬───────────────────────────────────────────────┘
           │ aggregate IRQ → RP1 chip via PCIe
           ▼
┌──────────────────────────────────────────────────────────┐
│ rp1_irq_chip (RP1 internal GIC, on the RP1 silicon)      │
│  • eth0 (PHY) — irq 106                                  │
│  • xhci-hcd usb1 / usb3 — irq 131, 136                   │
│  • dw_axi_dmac (DMA engine) — irq 140                    │
│  • PL011 UART0 (ttyAMA0) — irq 125 *                     │
│  • mailbox, i2c, spi, gpio                               │
└──────────────────────────────────────────────────────────┘
*The PL011 driver registers irq 125 ONLY when a process opens
 /dev/ttyAMA0 (verified 2026-04-25, three boots in a row). Before
 first open(), /proc/irq/125/smp_affinity_list does not exist, so
 IRQ pinning of ttyAMA0 must run AFTER something has opened the
 device. In production this means godo_tracker_rt's startup must
 re-apply the IRQ pinning step (or systemd `ExecStartPost=` runs
 it). The earlier claim that "PL011 registers at probe time" was
 wrong; it was caused by misreading a single Step-1 trial where
 godo_tracker_rt had been opened just before apply_irq_pin.sh ran.
```

Confirmed by `/sys/class/tty/ttyAMA0/device/uevent`:

```
OF_FULLNAME=/axi/pcie@1000120000/rp1/serial@30000
OF_COMPATIBLE_0=arm,pl011-axi
```

ttyAMA0 lives behind PCIe → RP1 → PL011. ttyAMA10 (the legacy BCM2712-side PL011) is unrelated and unused by GODO.

## 2. Inventory (snapshot 2026-04-25)

### IRQs that matter for the hot path

| IRQ | Device | Current `smp_affinity_list` | Counts at capture (CPU0/1/2/3) | Activates when |
| ---: | --- | --- | --- | --- |
| 106 | eth0 (RP1 PHY) | `0-3` | 0 / 0 / 0 / 0 | NIC traffic — including UDP RX from `godo-webctl` clients in Phase 4-3, and any host-network noise |
| 131 | xhci-hcd usb1 | `0-3` | 1 / 0 / 0 / 0 | USB device activity — RPLIDAR C1 plugs here in Phase 4-2 |
| 136 | xhci-hcd usb3 | `0-3` | 1 / 0 / 0 / 0 | second USB controller; spare LiDAR / USB-serial |
| 140 | dw_axi_dmac | `0-3` | 0 / 0 / 0 / 0 | DMA engine on RP1 (used by xhci, MMIO blocks) |
| 125 | ttyAMA0 PL011 | (only exists after first open() of /dev/ttyAMA0) | — | FreeD line; pin AFTER tracker has started reading |
| 161 | mmc0 (SD card) | `0-3` | 39855 / 0 / 0 / 0 | logging, journald flush, paging, `apt` |
| 162 | mmc1 (SD card) | `0-3` | 149505 / 0 / 0 / 0 | as above; mmc0 vs mmc1 split is the RPi 5's two SD-controller layout |
| 158 | RP1 mailbox | `0-3` | 2 / 0 / 0 / 0 | RP1 doorbell (firmware ↔ host) |
| 13  | arch_timer | `0-3` | 102576 / 79181 / 80195 / 88879 | per-CPU clock event — **must NOT be re-pinned** |
| 34/35/36/37 | arm-pmu CPU0/1/2/3 | `0` / `1` / `2` / `3` | 0/0/0/0 | per-CPU PMU — already correctly pinned |

### IRQs unrelated to the hot path (informational)

`v3d_core0`, `v3d_hub`, `vc4 hdmi *`, `vc4 crtc`, `pwr_button`, `i2c`, `spi`, `pispbe`, `1000800000.codec`, `PCIe PME` — none of these fire during steady-state GODO operation. Default `0-3` is fine; no pinning required for Phase 4-1.

### Sleeping / unused

- `ttyS0` (irq 33) — 8250 driver, not used (FreeD is on ttyAMA0). Counts only from kernel boot console activity.
- `kvm guest *` (irq 11, 12), `vgic` (irq 9) — KVM hooks, dormant on this host (no virtualization).

### IPIs (inter-processor interrupts)

`IPI0` rescheduling and `IPI1` function call dominate, but these follow scheduler/userspace activity rather than IRQ pinning. Reducing them is a CPU-isolation problem (`isolcpus=`, `nohz_full=`), not an IRQ-affinity problem. Out of scope for Phase 4-1.

## 3. Recommended affinity for Phase 4-1

Goal: keep CPU 3 free of all hot-path-irrelevant IRQs. Hot-path-relevant IRQs (eth0, xhci, ttyAMA0, dw_axi_dmac) are constrained to CPUs 0–2.

```text
# /etc/godo/irq-pinning.conf (proposed, applied at boot)
#
# Format: irq_pattern   smp_affinity_list
# Wildcard 'irq_pattern' is matched against the device descriptor in
# /proc/interrupts column 4+.

eth0                    0-2
xhci-hcd:usb1           0-2
xhci-hcd:usb3           0-2
dw_axi_dmac_platform    0-2
1f00008000.mailbox      0-2
mmc0                    0-1
mmc1                    0-1
107d004000.spi          0-1
```

Rationale:

- **eth0 / xhci / dw_axi_dmac → 0–2**: spreads the heavy NIC + LiDAR + DMA load across three cores while leaving CPU 3 fully reserved for the FreeD send loop.
- **mmc0 / mmc1 → 0–1**: SD activity is bursty (journald flush, `apt`, log rotation). Tighter pin to CPU 0–1 avoids letting an MMC burst drift onto CPU 2 mid-run; CPU 2 stays a clean spillover for eth/xhci.
- **arch_timer (irq 13) NOT touched**: it is a per-CPU local timer; re-pinning it would silently break preemption tick.
- **arm-pmu (irq 34–37) NOT touched**: already correctly `[CPUx → cpu_x]`.
- **ttyAMA0 (irq 125) → matches eth/xhci pool (0–2)**: the FreeD line opens only when the tracker is running. Same pinning rule.

> Why not include `isolcpus=3` in `/proc/cmdline`? Because a CFS task fail-safe still helps if SCHED_FIFO 50 ever yields. Booting with full isolation is a Phase 5 hardening decision after a long-run jitter test confirms whether SCHED_FIFO alone is sufficient. If TS5/Phase 5 measurements show p99 inflation correlated with CPU3 RX bursts, revisit `isolcpus=3 nohz_full=3 rcu_nocbs=3`.

## 4. Application script (Phase 4-1, manual; Phase 5, systemd)

For Phase 4-1 verification, apply by hand and re-measure `godo_jitter`:

```bash
# Run as root.
for irq in $(awk -F: '
  /eth0|xhci-hcd|dw_axi_dmac|1f00008000\.mailbox|ttyAMA/ {
    gsub(/ /,"",$1); print $1
  }' /proc/interrupts); do
    echo "0-2" | tee /proc/irq/$irq/smp_affinity_list
done
for irq in $(awk -F: '/mmc[01]|107d004000\.spi/ { gsub(/ /,"",$1); print $1 }' /proc/interrupts); do
    echo "0-1" | tee /proc/irq/$irq/smp_affinity_list
done
```

The pinning is **runtime-only** until persisted. For Phase 5 (production), wrap this in a small `irq-pinning.service` systemd unit run after `multi-user.target` so a reboot re-applies. Out of scope for this Phase 4-1 inventory.

## 5. Verification

After applying, three checks:

1. **Pinning took effect**: `for irq in 106 131 136 140 161 162; do echo -n "$irq: "; cat /proc/irq/$irq/smp_affinity_list; done` should reflect the new values.
2. **No CPU3 deltas during a load run**: while `godo_tracker_rt` is active for ≥ 60 s, snapshot `/proc/interrupts`, run, snapshot again, diff. CPU 3 column for eth0/xhci/uart/mmc/dma should remain 0 (or only bumped by the per-CPU arch_timer / IPI rows, which are unavoidable).
3. **Re-run TS5 jitter**: `sudo -i -u ncenter godo_jitter --duration-sec 60 --cpu 3 --prio 50` and append the result to `test_sessions/TS5/jitter_summary.md` as a new "post-IRQ-pin" comparison row. Expectation: p99/max should equal or beat the pre-pinning baseline (mean 5.8 µs / p99 29.4 µs / max 56.8 µs). Even on this lightly loaded dev host the gain may be small; the pinning's real value is under Phase 5's loaded conditions.

## 6. Open items / Phase 5 follow-ups

- **Persisted IRQ pinning** via systemd unit (Phase 4-2 candidate).
- **`isolcpus=3 nohz_full=3 rcu_nocbs=3`** kernel cmdline tuning — defer until Phase 5 measurement shows whether SCHED_FIFO + IRQ pinning alone meets the p99 < 200 µs goal under load.
- **`irqbalance`**: the Debian default may or may not be running on news-pi01 (`systemctl status irqbalance` to check). If active, the IRQ pin will be re-shuffled within minutes. Either disable `irqbalance` and apply this manual pinning, or configure `/etc/default/irqbalance` `IRQBALANCE_BANNED_CPUS` to keep CPU 3 off-limits to the balancer.
- **ttyAMA0 (irq 125) registration is lazy** — `/proc/irq/125/smp_affinity_list` only exists once a process has opened `/dev/ttyAMA0`. Production startup sequence must therefore: (1) launch `godo_tracker_rt` (which opens ttyAMA0); (2) re-apply IRQ pinning; or implement the pin inside the tracker binary itself after the SerialReader successfully opens the device. Phase 4-2 systemd unit will use `ExecStartPost=` for this.

## 7. References

- `/proc/interrupts` snapshot, `/proc/cmdline`, `lscpu` output: see this session's `bash` capture in PROGRESS.md.
- RP1 peripheral map and PL011 IRQ wiring: `doc/hardware/RPi5/sources/rp1-peripherals.pdf` § 3.5.
- The `setcap cap_sys_nice,cap_ipc_lock+ep` hook on `godo_tracker_rt` is the userspace half of CPU 3 protection; `smp_affinity_list` is the IRQ half.
