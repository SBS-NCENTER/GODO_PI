#!/usr/bin/env bash
# Atomic CP2102N driver unbind+rebind. Reads USB_PATH from environment.
# Triggered by mapping.recover_cp210x via `systemctl start
# godo-cp210x-recover.service` (polkit-gated by 49-godo-systemctl.rules
# rule (d)). Issue#16 short-term mitigation; long-term path is issue#17
# (GPIO UART direct).
#
# Spec memory:
#   .claude/memory/project_mapping_precheck_and_cp210x_recovery.md
set -euo pipefail
: "${USB_PATH:?USB_PATH unset; expected envfile at /run/godo/cp210x-recover.env}"
# Validate sysfs USB INTERFACE notation: `<bus>-<port-chain>:<cfg>.<intf>`
# (e.g. "1-1.4:1.0", "3-2:1.0"). The cp210x driver is a USB interface
# driver — its bind/unbind sysfs files require interface notation.
# Issue#16 HIL hot-fix v4 (2026-05-02 KST): v1/v2/v3 used bare device
# notation `^[0-9]+-[0-9.]+$` which the kernel rejected with
# `write error: No such device`. Defence-in-depth — webctl already
# validates upstream with the same regex.
if ! [[ "$USB_PATH" =~ ^[0-9]+-[0-9.]+:[0-9]+\.[0-9]+$ ]]; then
    echo "godo-cp210x-recover: invalid USB_PATH=$USB_PATH" >&2
    exit 2
fi
DRV=/sys/bus/usb/drivers/cp210x
echo "$USB_PATH" > "$DRV/unbind"
sleep 1
echo "$USB_PATH" > "$DRV/bind"
# Wait for the rebind's udev events to flush so /dev/ttyUSB* is
# recreated before mapping.start() goes on to the systemctl call.
# `--timeout=3` caps total wait so a deeply broken udev queue can't
# stall the whole recovery beyond TimeoutStartSec=10s.
udevadm settle --timeout=3 || true
echo "godo-cp210x-recover: $USB_PATH unbound+rebound"
