# FreeD hardware-UART wiring (Raspberry Pi 5)

FreeD from the SHOTOKU crane arrives as RS-232 ±12 V. The Pi 5 cannot
read that directly, so we use a YL-128 (MAX3232) level converter to
produce 3.3 V TTL and wire it to the Pi's PL011 UART0 on the 40-pin
header.

This file is the **only** place that captures the pin map, the
`/boot/firmware/` changes, and the verification procedure. The design
reasoning lives in [`../../../SYSTEM_DESIGN.md` §6.3](../../../SYSTEM_DESIGN.md).

---

## A. Wiring

```text
┌───────────────────────────────────────────────────────────────┐
│                  SHOTOKU crane (FreeD, RS-232)                │
│                                                               │
│   TXD ─────────┐                                              │
│                │                                              │
│   GND ──────┐  │                                              │
└─────────────┼──┼──────────────────────────────────────────────┘
              │  │
              │  │  RS-232  ±12 V
              ▼  ▼
┌────────────────────────────────────┐
│   YL-128   (MAX3232 module)        │
│                                    │
│   RS-232 side ┐                    │
│       TXD ◄───┘                    │
│       GND ◄───                     │
│                                    │
│   TTL side                         │
│       VCC ──── 3V3 ◄── Pi pin 1 or 17    (NOT 5 V)
│       GND ──── Pi pin 6 / 9 / 14 / etc.  (any GND)
│       RXD ──── Pi pin 10 (GPIO 15, UART0 RX)  ← see "label caveat" below
│       TXD     unconnected  (crane is read-only)
└────────────────────────────────────┘
```

Rules, with field rationale:

- **VCC = 3.3 V**, not 5 V. With 5 V the TTL side swings beyond the Pi's
  VIH_MAX (3.3 V) and can damage the SoC on long runs. A 3.3 V supply
  also means both endpoints of the TTL link live on the same rail, so
  noise margins are uniform.
- **No resistor dividers on RX.** An earlier Arduino R4 WiFi build used
  a 10 kΩ / 15 kΩ divider "for safety" on a 5 V module, and suffered
  intermittent framing errors from eroded VIH/VIL margins. The verified
  fix is identical 3.3 V rails with no divider. Do not reintroduce the
  divider "just in case".
- **YL-128 TTL output → Pi GPIO 15 (pin 10)**. That is UART0 RX on the
  RP1 (40-pin header on Pi 5).
- **The other TTL pin is unwired**. FreeD is unidirectional from the
  crane to the host. Leaving the Pi's TX (GPIO 14 / pin 8) unconnected
  is the intended configuration.
- **Ground common**. Tie the module GND and the Pi GND together.

### YL-128 pin label caveat (read this before wiring)

YL-128 modules from different manufacturers do not agree on whose
perspective the TTL pin labels take:

- Some label from the **module's perspective** — `TXD` = module
  transmits TTL = the line that goes to the host's RX.
- Others label from the **host's perspective** — `RXD` = host receives
  TTL = the line that goes to the host's RX.

**The YL-128 used in this build (and historically with the legacy
Arduino R4 firmware) follows the host-perspective convention**: the
TTL output pin (the one carrying converted RS-232 data) is the pin
labelled `RXD`, not `TXD`. This was confirmed empirically: connecting
the pin labelled `TXD` produced zero data; connecting the pin labelled
`RXD` produced the expected FreeD stream.

The diagram above uses the as-wired label (`RXD`) for this specific
module. If you ever swap in a different YL-128 (different vendor
silkscreen), do **not** trust the silkscreen — verify by following the
working signal:

```sh
# With everything wired and Pi booted, run the passthrough briefly:
scripts/run-pi5-freed-passthrough.sh > /tmp/p.log 2>&1 &
sleep 3 && kill -INT %1
grep -E '\[stat\]|shutdown' /tmp/p.log | tail -5
```

`pps > 0` (typically 60) means the wire is on the right YL-128 pin and
the crane is transmitting. `pps=0 unknown_type=0` for several seconds
means **no bytes are reaching PL011** — try the OTHER TTL pin on the
YL-128 first; if still zero, work outward (cable seating, crane FreeD
output enabled, RS-232 cable to YL-128).

#### Why the obvious GPIO probes don't work here

These two checks **fail to detect a working signal** on Pi 5 even when
data is flowing — do not rely on them:

- `pinctrl get 15` always reports `hi` once GPIO 15 is in alt 4 (UART
  mode). RP1 routes the alt-function signal directly to the PL011
  peripheral, bypassing the GPIO input register, so the snapshot is
  meaningless for diagnosing live UART traffic.
- `/proc/tty/driver/ttyAMA` shows `rx:0` until **someone has the
  device open**. The kernel only enables the PL011 receiver path on
  `open()`; an unopened device never increments its byte counter even
  when bits are arriving on the wire.

The `run-pi5-freed-passthrough.sh` PPS counter is the ground truth —
it actually opens PL011, programs termios, and counts framed packets.

---

## B. Boot configuration

PL011 UART0 is shared with the kernel serial console by default on a
fresh Raspberry Pi OS install. Two files on the FAT boot partition need
edits, then a reboot.

### `/boot/firmware/config.txt`

Append (or uncomment) these lines near the bottom, outside any
`[filter]` section so they apply on every boot:

```diff
+enable_uart=1
+dtparam=uart0=on
```

`enable_uart=1` alone is not sufficient on Pi 5 — `dtparam=uart0=on`
explicitly selects PL011 UART0 (`/dev/ttyAMA0`) over the Bluetooth
AUX UART.

### `/boot/firmware/cmdline.txt`

A stock `cmdline.txt` includes `console=serial0,115200` which gives the
kernel serial console ownership of `/dev/ttyAMA0`. As long as that is
present, any `open(/dev/ttyAMA0)` from userspace returns `EBUSY`.

Before (example):

```text
console=serial0,115200 console=tty1 root=PARTUUID=... rootfstype=ext4 ...
```

After:

```text
console=tty1 root=PARTUUID=... rootfstype=ext4 ...
```

Leave every other token untouched. `cmdline.txt` is a single line.

Reboot after both edits:

```sh
sudo reboot
```

---

## C. Verification

After the reboot, three quick checks:

### 1. The device exists and is not owned by a console

```sh
ls -l /dev/ttyAMA0
# crw-rw---- 1 root dialout ... /dev/ttyAMA0  ← good (dialout group owns it)

sudo lsof /dev/ttyAMA0
# (empty output)                              ← good, nothing has it open

sudo stty -F /dev/ttyAMA0 38400 parenb parodd cs8 -cstopb
sudo stty -F /dev/ttyAMA0 -a
# speed 38400 baud; ... cs8 parenb parodd -cstopb ...   ← 8O1 active
```

### 2. Current user is in `dialout`

```sh
id
# uid=1000(godo) gid=1000(godo) groups=...,20(dialout),...
```

If not:

```sh
sudo usermod -aG dialout "$USER"
# log out and back in for the group to take effect
```

### 3. Optional: loopback test with a jumper wire

With the crane disconnected, short GPIO 14 (pin 8, UART0 TX) to
GPIO 15 (pin 10, UART0 RX) with a jumper wire. Then:

```sh
# Terminal 1 — read one byte with a 2 s timeout
stty -F /dev/ttyAMA0 38400 parenb parodd cs8 -cstopb -echo
head -c 1 /dev/ttyAMA0 | xxd

# Terminal 2 — write a distinctive byte
printf '\xA5' > /dev/ttyAMA0
```

Terminal 1 should print `a5`. Remove the jumper before reconnecting the
crane.

Once `/dev/ttyAMA0` is verified, run `scripts/setup-pi5-rt.sh` once as
root, then `scripts/run-pi5-tracker-rt.sh`.
