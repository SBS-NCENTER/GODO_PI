# GPIO wiring — calibrate + Live-toggle buttons

> Phase 4-2 D operator input surface for `godo_tracker_rt`. The two buttons
> trigger AMCL state-machine transitions via `godo::rt::g_amcl_mode`.

## A. Pinout (Pi 5 40-pin header — BCM)

| Function     | BCM | Header pin | Notes                                  |
|--------------|----:|-----------:|----------------------------------------|
| Calibrate    |  16 |         36 | Falling edge → `g_amcl_mode = OneShot` |
| Live toggle  |  20 |         38 | Falling edge → toggle Idle ↔ Live      |
| Ground       |   — |    9 / 25  | Common ground for both switches        |

Defaults are `cfg.gpio_calibrate_pin = 16` and `cfg.gpio_live_toggle_pin = 20`
(`production/RPi5/src/core/config_defaults.hpp`). Override per environment
via TOML, env, or CLI; allowed range is `[0, 27]` (Pi 5 40-pin BCM header).

## B. Schematic

```text
   3V3 ────┐               ┌──── 3V3
           │               │
           ║ (internal     ║ (internal
           ║  PULL_UP set  ║  PULL_UP set
           ║  by libgpiod) ║  by libgpiod)
           │               │
   BCM 16 ─┴────[BTN1]──┐  BCM 20 ─┴────[BTN2]──┐
                        │                       │
                       GND                     GND
```

Buttons are **active-low**: the line idles HIGH (pulled up internally),
falls to LOW when pressed. libgpiod requests `bias = PULL_UP` and
`edge = FALLING`. No external pull-up resistor is required, but adding a
~10 kΩ external pull-up improves noise immunity on long cable runs.

Both BTN1 and BTN2 are tactile momentary push-buttons (NO contact). Common
debounce-tolerant parts: Omron B3F-1000, Diptronics DTSGV-66.

## C. libgpiod install

`libgpiod-dev` is required at build time and `libgpiod2` (runtime). On
Debian Trixie:

```bash
sudo apt install libgpiod-dev libgpiod2
```

Verify:

```bash
pkg-config --modversion libgpiod
# expect: 2.x.y
ls /dev/gpiochip0
# expect: present
```

The build links `libgpiodcxx` (C++ wrapper) and `libgpiod` (C base). Both
ship in the same `libgpiod-dev` package.

## D. Permissions

The operator user must be in the `gpio` group on Trixie:

```bash
sudo usermod -aG gpio ncenter
# log out and back in (group membership refresh)
```

Verify after re-login:

```bash
id ncenter | tr ',' '\n' | grep gpio
# expect: 997(gpio) or similar group
```

Without group membership, `GpioSourceLibgpiod::open()` throws on the
`gpiod::chip("/dev/gpiochip0")` call. `godo_tracker_rt` treats this as
non-fatal: GPIO triggers are disabled, but UDS / future HTTP triggers
still work (graceful degradation).

## E. Debounce policy

Software debounce window: **50 ms**, defined as
`godo::constants::GPIO_DEBOUNCE_NS = 50'000'000` (Tier-1; not exposed to
operator config — changing it would invalidate the bounce-filter
reasoning and require re-validation).

**Last-accepted semantics** (per Mode-A amendment M2): rejected events do
NOT advance the per-line `last_event_ns`. A burst of bounces within the
window cannot let a spurious press through; only a 50 ms quiet period
re-arms the line. The first press after construction is always accepted
(sentinel `last_event_ns = INT64_MIN`).

**CLOCK_MONOTONIC time source** (per Mode-A amendment M2): the production
driver requests `gpiod::line::clock::MONOTONIC` for kernel event
timestamps and reads `clock_gettime(CLOCK_MONOTONIC)` at dispatch time.
System time changes (NTP correction, manual `date` set) do NOT affect
bounce filtering.

If field testing on news-pi01 shows the 50 ms window is too short for a
particular tactile switch, raise `GPIO_DEBOUNCE_NS` to 100 ms (Tier-1 —
no Config exposure needed; this is a code change with a test refresh).

## F. UX notes

### Live-toggle press during a OneShot is dropped (not queued)

While the cold writer is running OneShot, a Live-toggle press is rejected
by the compare-and-swap at the dispatch site — the press is **dropped,
NOT queued** (per Mode-A amendment S5). Wait for the
`cold_writer: OneShot complete` log line before toggling Live.

Reasoning: OneShot is the operator's authoritative calibration step;
silently switching to Live mid-calibration would corrupt the Offset
that's about to publish. The operator gesture "press OneShot then Live"
must be sequenced explicitly, not buffered.

### CLOCK_MONOTONIC is unaffected by system time

NTP corrections, manual `date` adjustments, and DST changes do not affect
the debounce window. The window is measured purely against
`CLOCK_MONOTONIC`, which is monotonic across the device's uptime.

### Graceful degradation on libgpiod failure

If `/dev/gpiochip0` is missing, the user lacks `gpio` group, or the
configured pins are already requested by another process,
`GpioSourceLibgpiod::open()` throws and the GPIO thread exits cleanly.
`godo_tracker_rt` continues without GPIO triggers — the operator can
still drive `g_amcl_mode` via UDS (`nc -U /run/godo/ctl.sock`).

## G. Hardware verification

Hardware-required test (LABEL `hardware-required-gpio`):

```bash
cd production/RPi5/build
ctest -L hardware-required-gpio --output-on-failure
```

Asserts the chip is openable and both lines can be requested. Does NOT
press buttons (would require a hardware harness). Manual press-and-release
verification is part of the Phase 4-2 D bring-up checklist (CODEBASE.md
"2026-04-26 (Wave B)" section).
