#!/usr/bin/env bash
# Persisted IRQ pinning — keeps CPU 3 free for the RT thread (t_d).
#
# Invoked by:
#   - godo-irq-pin.service at boot (pins what's already registered:
#     eth0, USB, dma, mailbox, mmc, spi).
#   - godo-tracker.service ExecStartPost (catches the lazy ttyAMA0
#     IRQ which only appears after the tracker opens /dev/ttyAMA0).
#
# Idempotent: re-running re-applies the same affinities. IRQs not yet
# registered are skipped silently (verbose output goes to stderr only on
# the first-pass boot run; ExecStartPost runs in --quiet mode).
#
# All IRQ numbers are from /proc/interrupts on news-pi01 (RPi 5 BCM2712,
# Trixie 6.12.75+). Re-snapshot if the kernel or hardware changes.

set -euo pipefail

QUIET="${1:-}"
log() { [[ "$QUIET" == "--quiet" ]] || echo "$@" >&2; }

if [[ $EUID -ne 0 ]]; then
    log "godo-irq-pin: must run as root"
    exit 1
fi

# Hot-path-relevant IRQs → CPU 0-2.
# eth0 = 106, ttyAMA0 PL011 = 125, xhci-hcd:usb1 = 131,
# xhci-hcd:usb3 = 136, dw_axi_dmac_platform = 140,
# 1f00008000.mailbox = 158.
HOT_IRQS=(106 131 136 140 158 125)
# Bursty SD/SPI → CPU 0-1 (tighter pin).
# mmc0 = 161, mmc1 = 162, 107d004000.spi = 183.
BURSTY_IRQS=(161 162 183)

pin() {
    local irq="$1" cpus="$2"
    local f="/proc/irq/${irq}/smp_affinity_list"
    if [[ -w "$f" ]]; then
        echo "$cpus" > "$f"
        log "  irq ${irq} → ${cpus}"
    fi
}

log "=== godo-irq-pin (CPU 3 isolation) ==="
for irq in "${HOT_IRQS[@]}";    do pin "$irq" "0-2"; done
for irq in "${BURSTY_IRQS[@]}"; do pin "$irq" "0-1"; done
log "done."
