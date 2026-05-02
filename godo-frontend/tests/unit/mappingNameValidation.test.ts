/**
 * issue#14 — Mapping name regex parity + matrix.
 *
 * Pinned by:
 *   - byte-equality vs. webctl `MAPPING_NAME_REGEX_PATTERN_STR` mirror.
 *   - per-input acceptance / rejection table covering the C5 fix
 *     (leading-dot REJECTED) and L5 inner-char set.
 */

import { describe, expect, it } from 'vitest';
import {
  MAPPING_NAME_MAX_LEN,
  MAPPING_NAME_REGEX_SOURCE,
  MAPPING_RESERVED_NAMES,
} from '../../src/lib/constants';
import { MAPPING_NAME_REGEX_PATTERN_STR } from '../../src/lib/protocol';

describe('mapping name validation', () => {
  it('constants.MAPPING_NAME_REGEX_SOURCE byte-equals protocol mirror', () => {
    expect(MAPPING_NAME_REGEX_SOURCE).toBe(MAPPING_NAME_REGEX_PATTERN_STR);
  });

  it.each([
    'studio',
    'studio_v1',
    'control_room_2026',
    'studio.2026.05.01',
    'studio.v1',
    '(prefix)tail',
    'studio(1)',
    'Date,Loc',
    'a',
    'a'.repeat(MAPPING_NAME_MAX_LEN),
  ])('accepts %s', (name) => {
    expect(new RegExp(MAPPING_NAME_REGEX_SOURCE).test(name)).toBe(true);
  });

  it.each([
    '', // empty
    ' ', // whitespace
    'with space',
    'tab\tname',
    'studio/path',
    '../etc/passwd',
    'a'.repeat(MAPPING_NAME_MAX_LEN + 1), // 65
    'a*b', // glob
    'shell;injection',
  ])('rejects %s', (name) => {
    expect(new RegExp(MAPPING_NAME_REGEX_SOURCE).test(name)).toBe(false);
  });

  it.each(['.foo', '..bar', '.hidden', '.'])(
    'rejects leading-dot %s (C5 fix)',
    (name) => {
      expect(new RegExp(MAPPING_NAME_REGEX_SOURCE).test(name)).toBe(false);
    },
  );

  it('reserved names set pinned', () => {
    expect(MAPPING_RESERVED_NAMES.has('.')).toBe(true);
    expect(MAPPING_RESERVED_NAMES.has('..')).toBe(true);
    expect(MAPPING_RESERVED_NAMES.has('active')).toBe(true);
    expect(MAPPING_RESERVED_NAMES.has('studio_v1')).toBe(false);
  });

  it('MAPPING_NAME_MAX_LEN pinned at 64', () => {
    expect(MAPPING_NAME_MAX_LEN).toBe(64);
  });
});
