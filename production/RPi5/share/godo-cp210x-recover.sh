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
# Validate sysfs USB path: digits + dots + hyphens only, e.g. "1-1.4".
# Defence-in-depth — webctl already validates upstream with the same regex.
if ! [[ "$USB_PATH" =~ ^[0-9]+-[0-9.]+$ ]]; then
    echo "godo-cp210x-recover: invalid USB_PATH=$USB_PATH" >&2
    exit 2
fi
DRV=/sys/bus/usb/drivers/cp210x
echo "$USB_PATH" > "$DRV/unbind"
sleep 1
echo "$USB_PATH" > "$DRV/bind"
echo "godo-cp210x-recover: $USB_PATH unbound+rebound"
