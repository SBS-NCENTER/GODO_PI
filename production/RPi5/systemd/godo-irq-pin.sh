#!/usr/bin/env bash
# Persisted IRQ pinning — keeps CPU 3 free for the RT thread (t_d).
#
# Invoked by:
#   - godo-irq-pin.service at boot (pins what's already registered:
#     eth0, USB, dma, mailbox, mmc, spi).
#   - godo-tracker.service ExecStartPost (catches the lazy ttyAMA0
#     IRQ which only appears after the tracker opens /dev/ttyAMA0).
#
# Idempotent: re-running re-applies the same affinities. IRQs that are
# not yet registered or that the kernel marks affinity-fixed (e.g.
# pwr_button GPIO) are skipped silently — the script continues with
# whatever IS pinnable. `--quiet` suppresses stderr (used by the
# tracker's ExecStartPost so each restart does not spam the journal).
#
# **IRQ numbers are NOT stable across reboots.** Earlier revisions of
# this script hardcoded IRQ numbers from a single `/proc/interrupts`
# snapshot; the 2026-04-30 reboot during PR-A surfaced the failure
# mode (IRQ 183 had moved from `107d004000.spi` to a kernel-fixed
# `pwr_button` GPIO line, and the affinity write returned EPERM).
# We now look up IRQ numbers by device name from /proc/interrupts at
# every boot, so the script is reboot-stable.

set -euo pipefail

QUIET="${1:-}"
log() { [[ "$QUIET" == "--quiet" ]] || echo "$@" >&2; }

if [[ $EUID -ne 0 ]]; then
    log "godo-irq-pin: must run as root"
    exit 1
fi

# Device names as they appear in the LAST whitespace-separated token of
# each /proc/interrupts row. We match the trailing token rather than
# substring so e.g. `mmc0` does not also match a hypothetical
# `someprefix-mmc0` row.
#
# Hot-path-relevant devices → CPU 0-2.
HOT_DEVICES=(eth0 ttyAMA0 xhci-hcd:usb1 xhci-hcd:usb3 dw_axi_dmac_platform 1f00008000.mailbox)
# Bursty SD/SPI → CPU 0-1 (tighter pin).
BURSTY_DEVICES=(mmc0 mmc1 107d004000.spi)

# Print the IRQ number whose /proc/interrupts row's trailing token
# equals $1, or empty string if no match. Single-shot — picks the
# first match if there are multiple (none expected on this hardware).
irq_for_device() {
    local devname="$1"
    awk -v dev="$devname" '
        # Skip header line + non-IRQ rows (continued from columns >NF).
        NR == 1 { next }
        # Trailing token must equal $devname; the IRQ number is the
        # first column with a trailing colon. Strip the colon.
        $NF == dev { irq = $1; sub(":", "", irq); print irq; exit }
    ' /proc/interrupts
}

pin() {
    local devname="$1" cpus="$2"
    local irq f
    irq="$(irq_for_device "$devname")"
    if [[ -z "$irq" ]]; then
        log "  ${devname} → (not registered yet, skipped)"
        return 0
    fi
    f="/proc/irq/${irq}/smp_affinity_list"
    if [[ ! -w "$f" ]]; then
        log "  irq ${irq} (${devname}) → (affinity file not writable, skipped)"
        return 0
    fi
    # The kernel can still reject the write at echo time for
    # affinity-fixed IRQs (NO_BALANCE / NO_AFFINITY flags) — those
    # surface as EPERM. Capture and log; don't fail the unit.
    if echo "$cpus" > "$f" 2>/dev/null; then
        log "  irq ${irq} (${devname}) → ${cpus}"
    else
        log "  irq ${irq} (${devname}) → (kernel rejected affinity write, skipped)"
    fi
}

log "=== godo-irq-pin (CPU 3 isolation) ==="
for dev in "${HOT_DEVICES[@]}";    do pin "$dev" "0-2"; done
for dev in "${BURSTY_DEVICES[@]}"; do pin "$dev" "0-1"; done
log "done."
