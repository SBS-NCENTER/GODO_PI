/**
 * issue#27 — hover-coord visibility via the shared `MapViewport`.
 *
 * The Mode-A M2 lock moves hover-coord ownership from `<MapUnderlay/>`'s
 * local `$state` into the shared `viewport.hoverWorld` getter/setter so
 * overlay layers (mask, pose-hint) can push their own pointer-move
 * coordinates without losing the always-on top-right readout.
 *
 * These tests pin the factory-level contract:
 *   - default state is null (no readout rendered).
 *   - setHoverWorld(wx, wy) populates the value.
 *   - setHoverWorld(null) clears it.
 *   - setHoverWorld(wx) without wy clears (defensive — caller bug).
 */

import { describe, expect, it } from 'vitest';

import { createMapViewport } from '../../src/lib/mapViewport.svelte';

describe('mapViewport.hoverWorld (issue#27 — M2 fold)', () => {
  it('default state is null', () => {
    const v = createMapViewport();
    expect(v.hoverWorld).toBeNull();
  });

  it('setHoverWorld populates the value', () => {
    const v = createMapViewport();
    v.setHoverWorld(1.5, -2.0);
    expect(v.hoverWorld).toEqual({ x: 1.5, y: -2.0 });
  });

  it('setHoverWorld(null) clears the value', () => {
    const v = createMapViewport();
    v.setHoverWorld(1.5, -2.0);
    v.setHoverWorld(null);
    expect(v.hoverWorld).toBeNull();
  });

  it('setHoverWorld(wx) without wy clears defensively', () => {
    const v = createMapViewport();
    v.setHoverWorld(1.0, 2.0);
    v.setHoverWorld(3.0);  // missing wy — treat as clear
    expect(v.hoverWorld).toBeNull();
  });

  it('two viewports do not share hover state', () => {
    const a = createMapViewport();
    const b = createMapViewport();
    a.setHoverWorld(1, 2);
    expect(a.hoverWorld).toEqual({ x: 1, y: 2 });
    expect(b.hoverWorld).toBeNull();
  });
});
