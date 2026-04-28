/**
 * Track B-CONFIG (PR-CONFIG-β) — protocol.ts mirror discipline.
 *
 * The TS schema/type interfaces are hand-mirrored from the Python
 * NamedTuple in `godo-webctl/src/godo_webctl/config_schema.py`. Drift
 * is detected by inspection during code review (per
 * godo-frontend/CODEBASE.md invariant). These tests pin the values
 * + structural shape, not the wire bytes.
 */

import { describe, expect, it } from 'vitest';
import {
  RELOAD_CLASS_HOT,
  RELOAD_CLASS_RESTART,
  RELOAD_CLASS_RECALIBRATE,
  VALID_RELOAD_CLASSES,
  type ConfigSchemaRow,
  type ConfigKV,
  type ConfigSetResult,
  type ConfigGetResponse,
  type RestartPendingResponse,
} from '../../src/lib/protocol';

describe('protocol — Track B-CONFIG mirrors', () => {
  it('reload-class enum strings match the C++ source', () => {
    expect(RELOAD_CLASS_HOT).toBe('hot');
    expect(RELOAD_CLASS_RESTART).toBe('restart');
    expect(RELOAD_CLASS_RECALIBRATE).toBe('recalibrate');
  });

  it('VALID_RELOAD_CLASSES contains all 3 classes', () => {
    expect(VALID_RELOAD_CLASSES.size).toBe(3);
    expect(VALID_RELOAD_CLASSES.has('hot')).toBe(true);
    expect(VALID_RELOAD_CLASSES.has('restart')).toBe(true);
    expect(VALID_RELOAD_CLASSES.has('recalibrate')).toBe(true);
  });

  it('ConfigSchemaRow accepts the 7 fields the wire emits', () => {
    const row: ConfigSchemaRow = {
      name: 'smoother.deadband_mm',
      type: 'double',
      min: 0,
      max: 200,
      default: '10.0',
      reload_class: 'hot',
      description: 'Deadband on translation (mm).',
    };
    expect(row.name).toBe('smoother.deadband_mm');
    expect(row.type).toBe('double');
  });

  it('ConfigKV accepts string / number / boolean values', () => {
    const a: ConfigKV = { name: 'k', value: 42 };
    const b: ConfigKV = { name: 'k', value: '/dev/ttyUSB0' };
    const c: ConfigKV = { name: 'k', value: true };
    expect(typeof a.value).toBe('number');
    expect(typeof b.value).toBe('string');
    expect(typeof c.value).toBe('boolean');
  });

  it('ConfigSetResult shape pins reload_class', () => {
    const r: ConfigSetResult = { ok: true, reload_class: 'hot' };
    expect(r.ok).toBe(true);
    expect(VALID_RELOAD_CLASSES.has(r.reload_class)).toBe(true);
  });

  it('ConfigGetResponse is a flat dict', () => {
    const c: ConfigGetResponse = {
      'smoother.deadband_mm': 10,
      'amcl.map_path': '/etc/godo/maps/studio_v1.pgm',
    };
    expect(c['smoother.deadband_mm']).toBe(10);
    expect(c['amcl.map_path']).toBe('/etc/godo/maps/studio_v1.pgm');
  });

  it('RestartPendingResponse shape', () => {
    const ok: RestartPendingResponse = { pending: false };
    const set: RestartPendingResponse = { pending: true };
    expect(ok.pending).toBe(false);
    expect(set.pending).toBe(true);
  });
});
