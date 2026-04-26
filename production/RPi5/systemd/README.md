# godo-tracker systemd units

Persisted bring-up artefacts for the `godo_tracker_rt` binary on
news-pi01 (RPi 5, Trixie). Closes the Phase 4-2 carry-over items
listed in `PROGRESS.md`:

- Persisted IRQ-pinning systemd unit
- `godo-tracker.service` (RT process under systemd)
- Hardware watchdog wiring (`RuntimeWatchdogSec=`)

Three units / one drop-in / one helper script:

```text
godo-irq-pin.sh                       Idempotent IRQ-pinning helper
godo-irq-pin.service                  Boot-time oneshot (calls the helper)
godo-tracker.service                  RT main process
system.conf.d/godo-watchdog.conf      systemd PID-1 hardware watchdog
install.sh                            Idempotent operator installer
```

---

## 1. Install

Run once on news-pi01 after `scripts/build.sh` has produced the
binary:

```bash
sudo bash production/RPi5/systemd/install.sh
```

The installer:

1. `install`s `godo_tracker_rt` and `godo-irq-pin.sh` into
   `/opt/godo-tracker/` (root:root, 0755).
2. `install`s the two `.service` files into `/etc/systemd/system/`.
3. `install`s the watchdog drop-in into
   `/etc/systemd/system.conf.d/`.
4. `systemctl daemon-reload`.
5. Does NOT enable / start the units — operator decides.

The installer is idempotent; re-run it after every rebuild to refresh
the binary at `/opt/godo-tracker/godo_tracker_rt`.

`/etc/godo/tracker.env` (optional) holds operator overrides for the
Tier-2 keys that `core/config_defaults.hpp` ships with. The unit's
`EnvironmentFile=-/etc/godo/tracker.env` line treats it as optional
(leading `-`).

---

## 2. Enable / disable

```bash
# Enable both units at boot, start now.
sudo systemctl enable --now godo-irq-pin.service
sudo systemctl enable --now godo-tracker.service

# Watchdog drop-in needs PID-1 re-exec (does NOT happen on
# daemon-reload alone).
sudo systemctl daemon-reexec

# Stop / disable.
sudo systemctl disable --now godo-tracker.service
sudo systemctl disable --now godo-irq-pin.service
```

`godo-tracker.service` declares `After=godo-irq-pin.service` +
`Wants=godo-irq-pin.service`, so enabling the tracker alone will
pull the IRQ-pin oneshot in by itself; enabling both explicitly is
documentation as much as configuration.

---

## 3. Verify

After `enable --now`:

```bash
# Status / live log.
systemctl status godo-tracker
journalctl -u godo-tracker -f

# IRQ pinning applied (sample IRQs from the boot pass).
cat /proc/irq/106/smp_affinity_list   # eth0    → 0-2
cat /proc/irq/161/smp_affinity_list   # mmc0    → 0-1
cat /proc/irq/183/smp_affinity_list   # spi     → 0-1

# Lazy IRQ pinned by ExecStartPost (registers only after the
# tracker opens /dev/ttyAMA0).
cat /proc/irq/125/smp_affinity_list   # ttyAMA0 → 0-2

# RT scheduling.
ps -L -o tid,comm,policy,rtprio -p "$(pidof godo_tracker_rt)"
# t_d thread should show policy=FF rtprio=50 on CPU 3.

# UDS socket for webctl.
ls -l /run/godo/ctl.sock              # srw-rw---- ncenter ncenter

# Hardware watchdog active.
journalctl -b 0 | grep -i watchdog | head
# Expected line: "Hardware watchdog 'Broadcom BCM2835 Watchdog timer',
#                 version 0, device /dev/watchdog0"
```

---

## 4. Capability model — Ambient over file caps under systemd

`scripts/setup-pi5-rt.sh` runs `setcap cap_sys_nice,cap_ipc_lock+ep`
on the binary so manual dev launches (`scripts/run-pi5-tracker-rt.sh`)
can call `mlockall(2)` and `sched_setscheduler(SCHED_FIFO, 50)`
without root.

Under systemd those file caps are inert: `NoNewPrivileges=yes`
(set in `godo-tracker.service` for hardening) drops file-cap
inheritance. The unit therefore grants the same two caps directly
via:

```ini
AmbientCapabilities=CAP_SYS_NICE CAP_IPC_LOCK
CapabilityBoundingSet=CAP_SYS_NICE CAP_IPC_LOCK
```

`CAP_SYS_NICE` covers `sched_setscheduler(SCHED_FIFO, …)` and
`pthread_setaffinity_np`. `CAP_IPC_LOCK` covers `mlockall(MCL_*)`.
`LimitMEMLOCK=infinity` + `LimitRTPRIO=99` lift the corresponding
rlimits so the cap calls actually succeed.

`RestrictRealtime=` is **deliberately absent** — it would block
SCHED_FIFO and break the RT thread; webctl's unit sets it because
webctl never schedules RT.

---

## 5. IRQ-pinning two-pass design

Eight IRQs need to be off CPU 3:

| IRQ | Source | Affinity | Registers |
| --- | --- | --- | --- |
| 106 | eth0 | 0-2 | at boot |
| 131 | xhci-hcd:usb1 | 0-2 | at boot |
| 136 | xhci-hcd:usb3 | 0-2 | at boot |
| 140 | dw_axi_dmac_platform | 0-2 | at boot |
| 158 | 1f00008000.mailbox | 0-2 | at boot |
| 125 | ttyAMA0 PL011 | 0-2 | **lazily, when tracker opens /dev/ttyAMA0** |
| 161 | mmc0 | 0-1 | at boot |
| 162 | mmc1 | 0-1 | at boot |
| 183 | 107d004000.spi | 0-1 | at boot |

The lazy ttyAMA0 case is why a single boot-time oneshot is not
enough: at the time `godo-irq-pin.service` runs, `/proc/irq/125/`
does not exist yet. Two passes solve it:

1. **Boot oneshot** — `godo-irq-pin.service` runs `godo-irq-pin.sh`
   in verbose mode. Pins everything that is registered. Skips IRQ
   125 silently.
2. **Per-tracker-start re-pin** — `godo-tracker.service` declares
   `ExecStartPost=+/opt/godo-tracker/godo-irq-pin.sh --quiet`.
   The `+` prefix runs the helper as root regardless of the unit's
   `User=ncenter`. By this point the tracker has opened
   `/dev/ttyAMA0`, so IRQ 125 exists and gets pinned. `--quiet`
   suppresses stderr so each tracker restart does not spam the
   journal.

The IRQ numbers in the helper are a snapshot of `/proc/interrupts`
on news-pi01; re-snapshot if the kernel or hardware changes.

---

## 6. Watchdog drop-in (`system.conf.d/godo-watchdog.conf`)

```ini
[Manager]
RuntimeWatchdogSec=10s
```

systemd PID 1 pets the BCM2712 hardware watchdog at half this
interval; if PID 1 itself hangs, the kernel-level watchdog timer
fires and the system resets. The drop-in is installed under
`/etc/systemd/system.conf.d/` rather than edited into
`/etc/systemd/system.conf` directly, so packaging upgrades cannot
clobber it.

A plain `daemon-reload` does NOT pick this up — `Manager`-level
settings only refresh on `daemon-reexec`:

```bash
sudo systemctl daemon-reexec
```

After re-exec, confirm:

```bash
journalctl -b 0 | grep -i watchdog
# "Using hardware watchdog 'Broadcom BCM2835 Watchdog timer'"
```

If no line appears, the kernel never registered a watchdog device
(check `bcm2835_wdt` is loaded and `/dev/watchdog0` exists).

---

## 7. Uninstall

```bash
sudo systemctl disable --now godo-tracker.service
sudo systemctl disable --now godo-irq-pin.service
sudo rm -f /etc/systemd/system/godo-tracker.service
sudo rm -f /etc/systemd/system/godo-irq-pin.service
sudo rm -f /etc/systemd/system.conf.d/godo-watchdog.conf
sudo rm -rf /opt/godo-tracker
sudo systemctl daemon-reload
sudo systemctl daemon-reexec   # picks up the watchdog removal
```

The on-disk binary at `/opt/godo-tracker/godo_tracker_rt` is the
installer's copy; the build-tree binary under
`production/RPi5/build/` is unaffected and remains usable for
manual dev launches via `scripts/run-pi5-tracker-rt.sh`.
