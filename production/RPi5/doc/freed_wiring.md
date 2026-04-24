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
│       TXD ──── Pi pin 10 (GPIO 15, UART0 RX)
│       RXD     unconnected  (crane is read-only)
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
- **YL-128 TXD → Pi GPIO 15 (pin 10)**. That is UART0 RX on the BCM2712.
- **RXD unwired**. FreeD is unidirectional from the crane to the host.
  Leaving the Pi's TX (GPIO 14 / pin 8) unconnected is the intended
  configuration.
- **Ground common**. Tie the module GND and the Pi GND together.

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
