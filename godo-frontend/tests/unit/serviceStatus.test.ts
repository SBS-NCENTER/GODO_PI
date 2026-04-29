/**
 * Unit tests for `lib/serviceStatus.ts` — chip-class SSOT.
 *
 * Drift catch: the map keys + values are pinned literal so a future
 * writer who renames a chip class (e.g. 'warn' → 'warning') breaks
 * BOTH `ServiceCard` AND `ServiceStatusCard` consistently rather than
 * silently breaking just one. Without this pin, the `STATUS_TO_CHIP`
 * map drift has no test coverage.
 */

import { describe, expect, it } from 'vitest';
import { STATUS_TO_CHIP, statusChipClass } from '../../src/lib/serviceStatus';

describe('STATUS_TO_CHIP map', () => {
  it('pins all 7 known status words to their chip class', () => {
    expect(STATUS_TO_CHIP).toEqual({
      active: 'ok',
      activating: 'warn',
      deactivating: 'warn',
      inactive: 'idle',
      failed: 'err',
      timeout: 'err',
      unknown: 'idle',
    });
  });

  it('returns the mapped class for a known status', () => {
    expect(statusChipClass('active')).toBe('ok');
    expect(statusChipClass('activating')).toBe('warn');
    expect(statusChipClass('failed')).toBe('err');
  });

  it('falls back to "idle" for an unknown status word', () => {
    // A future systemd version that emits a state we do NOT know about
    // (e.g. "reloading") must not crash the render — fallback to idle.
    expect(statusChipClass('reloading')).toBe('idle');
    expect(statusChipClass('not-a-real-state')).toBe('idle');
    expect(statusChipClass('')).toBe('idle');
  });
});
