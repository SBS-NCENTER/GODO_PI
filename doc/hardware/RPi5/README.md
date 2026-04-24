# Raspberry Pi 5 — hardware reference

This directory collects the official Raspberry Pi 5 reference material that
GODO depends on for wiring, pinout, and peripheral programming. The files
under `sources/` are fetched verbatim from the Raspberry Pi Product
Information Portal (`pip.raspberrypi.com` / `datasheets.raspberrypi.com`);
do not edit them.

Any GODO-authored derivations (pinout summary for this project, wiring
diagrams, boot-config instructions) live in this README and — when
specific to a subsystem — in the relevant `production/RPi5/doc/*.md`.

---

## Official sources (in `sources/`)

| File | Bytes | Upstream URL |
| --- | ---: | --- |
| `raspberry-pi-5-product-brief.pdf` | 1'095'537 | [raspberrypi.com](https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-product-brief.pdf) |
| `raspberry-pi-5-mechanical-drawing.pdf` | 174'949 | [raspberrypi.com](https://datasheets.raspberrypi.com/rpi5/raspberry-pi-5-mechanical-drawing.pdf) |
| `rp1-peripherals.pdf` | 3'513'008 | [raspberrypi.com](https://datasheets.raspberrypi.com/rp1/rp1-peripherals.pdf) |
| `raspberry-pi-uart-connector.pdf` | 240'769 | [pip.raspberrypi.com](https://pip.raspberrypi.com/documents/RP-008189-DS) |

Fetched on 2026-04-24. Re-fetch when Raspberry Pi revises any of these
(check the footer revision number in each PDF).

### What is NOT here, and why

- **Full Pi 5 schematic**: Raspberry Pi has **not released** a public
  schematic PDF for Pi 5, unlike every prior model (Pi 4B / Pi 3
  family / Pi 2B / Pi 1 / Zero all have public schematics at
  `pip.raspberrypi.com`). GODO does not need net-level schematic
  detail for Phase 4 work — the 40-pin header, USB 3.0, and Ethernet
  interfaces are all covered by the product brief + RP1 peripherals
  manual. If a future phase needs schematic-level tracing, consult
  the [compliance test reports](https://pip.raspberrypi.com) which
  include block-level diagrams.
- **BCM2712 SoC datasheet**: not public. The RP1 peripherals doc
  covers everything on the PCIe-attached southbridge; the BCM2712's
  own peripherals (PCIe, memory controller) are not exposed to GODO.

---

## 40-pin GPIO header — pinout quick reference

Pin numbering follows the physical position on the 2x20 header,
viewed with the board face-up and the header at the top edge.

```text
                     ┌──────────────┐
              3V3 ●  │   1 │   2   │  ● 5V
         SDA GPIO2 ●  │   3 │   4   │  ● 5V
         SCL GPIO3 ●  │   5 │   6   │  ● GND
             GPIO4 ●  │   7 │   8   │  ● GPIO14 (UART0 TX)
              GND ●  │   9 │  10   │  ● GPIO15 (UART0 RX)  ◄── FreeD via YL-128
            GPIO17 ●  │  11 │  12   │  ● GPIO18 (PWM0)
            GPIO27 ●  │  13 │  14   │  ● GND
            GPIO22 ●  │  15 │  16   │  ● GPIO23
              3V3 ●  │  17 │  18   │  ● GPIO24
       MOSI GPIO10 ●  │  19 │  20   │  ● GND
        MISO GPIO9 ●  │  21 │  22   │  ● GPIO25
       SCLK GPIO11 ●  │  23 │  24   │  ● GPIO8  (SPI CE0)
              GND ●  │  25 │  26   │  ● GPIO7  (SPI CE1)
             GPIO0 ●  │  27 │  28   │  ● GPIO1                ← ID_SD/ID_SC (avoid)
             GPIO5 ●  │  29 │  30   │  ● GND
             GPIO6 ●  │  31 │  32   │  ● GPIO12 (PWM0)
            GPIO13 ●  │  33 │  34   │  ● GND
            GPIO19 ●  │  35 │  36   │  ● GPIO16
            GPIO26 ●  │  37 │  38   │  ● GPIO20
              GND ●  │  39 │  40   │  ● GPIO21
                     └──────────────┘
```

### Category summary

| Category | Pins (physical) | Notes |
| --- | --- | --- |
| 3V3 power | 1, 17 | ≈ 500 mA total on Pi 5 across both rails |
| 5V power | 2, 4 | Limited by USB-PD / the 27 W PSU spec |
| GND | 6, 9, 14, 20, 25, 30, 34, 39 | Pick the closest ground pin |
| UART0 (PL011) | 8 (TX=GPIO14), 10 (RX=GPIO15) | **FreeD target**; `/dev/ttyAMA0` |
| I²C-1 | 3 (SDA=GPIO2), 5 (SCL=GPIO3) | Future sensor / display use |
| SPI-0 | 19, 21, 23, 24, 26 | Not used by GODO currently |
| PWM | 12 (GPIO18), 32 (GPIO12), 33 (GPIO13), 35 (GPIO19) | Optional status LED |
| ID EEPROM (reserved) | 27 (GPIO0), 28 (GPIO1) | Avoid — HAT auto-detect |
| General GPIO | 7, 11, 13, 15, 16, 18, 22, 29, 31, 36, 37, 38, 40 | Calibrate button, LEDs |

RP1 exposes **five UARTs** total (UART0…UART5, with UART1 being the
mini-UART). Additional UARTs can be enabled via `dtoverlay=uartN` in
`/boot/firmware/config.txt` if a future phase needs more serial channels;
UART0 is the canonical primary and is the only one GODO uses.

---

## GODO-specific wiring (Phase 4-1)

Authoritative source of truth:
[`production/RPi5/doc/freed_wiring.md`](../../../production/RPi5/doc/freed_wiring.md).
The summary below is a cross-reference only.

```text
┌─── YL-128 (MAX3232, TTL side) ──┬───── RPi 5 (40-pin) ────────────┐
│  VCC  (3V3 rail!)                │  Pin 1  (3V3)                   │
│  GND                             │  Pin 6  (GND)                   │
│  TXD  (emits FreeD data)         │  Pin 10 (GPIO15 / UART0 RX)     │
│  RXD  (not used — FreeD is 1-way)│  — unconnected                  │
└──────────────────────────────────┴─────────────────────────────────┘
```

Critical rules (learned from the Arduino R4 generation):

1. **YL-128 VCC → Pi 3V3 only.** Never 5 V. Both sides of the TTL link
   must run at 3.3 V CMOS for clean noise margins on the Pi's GPIO.
2. **No resistor dividers on the RX line.** A prior Arduino R4 build
   hit intermittent framing errors until the "safety" dividers were
   removed. Same rule applies here.
3. **Kernel serial console must be disabled** on `/dev/ttyAMA0` before
   `godo_tracker_rt` can open the port. `enable_uart=1` +
   `dtparam=uart0=on` in `config.txt`, and `console=serial0,115200`
   removed from `cmdline.txt`. See `freed_wiring.md §B`.

---

## Where to look when…

| Need | Go to |
| --- | --- |
| GPIO pull-up / pull-down behaviour, drive strength | `sources/rp1-peripherals.pdf` Chapter 3 (GPIO) |
| UART termios flags that PL011 honours vs rejects | `sources/rp1-peripherals.pdf` Chapter 13 (UART) |
| Connector placement, board outline, mounting holes | `sources/raspberry-pi-5-mechanical-drawing.pdf` |
| Power budget for USB + display + HAT + peripherals | `sources/raspberry-pi-5-product-brief.pdf` page 4 |
| Live pin state on the target host | `pinctrl get` (replaces the old `raspi-gpio get`) |
| Interactive pinout with alternate functions | <https://pinout.xyz> (not part of this repo) |

---

## Related GODO documents

- [`production/RPi5/doc/freed_wiring.md`](../../../production/RPi5/doc/freed_wiring.md) — authoritative wiring + boot-config procedure.
- [`SYSTEM_DESIGN.md §6.3`](../../../SYSTEM_DESIGN.md) — ops checklist including IRQ inventory, CPU governor, watchdog.
- [`SYSTEM_DESIGN.md §11`](../../../SYSTEM_DESIGN.md) — two-tier constants (`core/constants.hpp`, `core/config_defaults.hpp`) where pin numbers and port names live in code.
