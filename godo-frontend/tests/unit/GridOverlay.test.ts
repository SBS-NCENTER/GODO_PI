/**
 * issue#28 — `<GridOverlay>` interval-schedule pin.
 *
 * The component delegates to `pickInterval` (closure) for the
 * zoom→interval lookup. We can't reach that closure from the outside,
 * but we can pin the equivalent from `GRID_INTERVAL_SCHEDULE` so any
 * future schedule edit surfaces in CI.
 */

import { describe, expect, it } from 'vitest';

import { GRID_INTERVAL_SCHEDULE } from '../../src/lib/constants';

function pickIntervalFromSchedule(zoom: number) {
  for (const entry of GRID_INTERVAL_SCHEDULE) {
    if (entry.maxZoom === null) return entry;
    if (zoom <= entry.maxZoom) return entry;
  }
  return GRID_INTERVAL_SCHEDULE[GRID_INTERVAL_SCHEDULE.length - 1];
}

describe('GridOverlay interval schedule', () => {
  it('selects 5 m grid for very low zoom (< 0.3 px/m)', () => {
    const e = pickIntervalFromSchedule(0.1);
    expect(e.intervalM).toBe(5);
  });

  it('selects 1 m grid for moderate zoom', () => {
    const e = pickIntervalFromSchedule(0.5);
    expect(e.intervalM).toBe(1);
  });

  it('selects 0.5 m grid for higher zoom', () => {
    const e = pickIntervalFromSchedule(2);
    expect(e.intervalM).toBe(0.5);
  });

  it('selects 0.1 m grid as catch-all sentinel for extreme zoom', () => {
    const e = pickIntervalFromSchedule(100);
    expect(e.intervalM).toBe(0.1);
    expect(e.maxZoom).toBeNull();
  });

  it('schedule has a non-empty catch-all sentinel as the trailing entry', () => {
    const last = GRID_INTERVAL_SCHEDULE[GRID_INTERVAL_SCHEDULE.length - 1];
    expect(last.maxZoom).toBeNull();
  });
});
