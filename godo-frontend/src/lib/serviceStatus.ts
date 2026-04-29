/**
 * Track B-SYSTEM PR-2 — chip-class SSOT for systemd service ActiveState.
 *
 * Both `ServiceCard.svelte` (loopback-admin actions) and
 * `ServiceStatusCard.svelte` (anon read + admin actions on /system) import
 * from this module so the visual layer cannot drift between the two.
 *
 * Pin: `tests/unit/serviceStatus.test.ts`.
 */

export const STATUS_TO_CHIP: Readonly<Record<string, string>> = {
  active: 'ok',
  activating: 'warn',
  deactivating: 'warn',
  inactive: 'idle',
  failed: 'err',
  timeout: 'err',
  unknown: 'idle',
};

export function statusChipClass(s: string): string {
  return STATUS_TO_CHIP[s] ?? 'idle';
}
