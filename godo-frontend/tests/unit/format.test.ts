/**
 * Unit tests for `lib/format.ts` — covers the two new Track B-SYSTEM
 * formatters (`formatUptimeKo`, `formatBytesBinaryShort`) plus a sanity
 * pin on the existing trio (`formatRemaining`, `formatMeters`,
 * `formatDegrees`).
 */

import { describe, expect, it } from 'vitest';
import {
  formatBytesBinaryShort,
  formatDegrees,
  formatMeters,
  formatRemaining,
  formatUptimeKo,
} from '../../src/lib/format';

describe('formatRemaining (existing)', () => {
  it('renders 0 as 만료됨', () => {
    expect(formatRemaining(0)).toBe('만료됨');
  });
  it('renders 30 s as "30s"', () => {
    expect(formatRemaining(30)).toBe('30s');
  });
});

describe('formatMeters / formatDegrees (existing)', () => {
  it('formats meters with 2 decimals', () => {
    expect(formatMeters(1.234)).toBe('1.23 m');
  });
  it('formats degrees with 1 decimal', () => {
    expect(formatDegrees(45)).toBe('45.0°');
  });
});

describe('formatUptimeKo (Track B-SYSTEM PR-2)', () => {
  it('returns "—" when active_since_unix is null', () => {
    expect(formatUptimeKo(null, 1_000_000_000)).toBe('—');
  });
  it('returns "—" when active_since_unix is 0', () => {
    expect(formatUptimeKo(0, 1_000_000_000)).toBe('—');
  });
  it('returns "0초" when started just now', () => {
    expect(formatUptimeKo(1000, 1000)).toBe('0초');
  });
  it('renders sub-minute uptime as "Xs초"', () => {
    expect(formatUptimeKo(1000, 1030)).toBe('30초');
  });
  it('renders sub-hour uptime as "M분 S초"', () => {
    expect(formatUptimeKo(1000, 1090)).toBe('1분 30초');
  });
  it('renders sub-hour even minute as just "M분"', () => {
    expect(formatUptimeKo(1000, 1180)).toBe('3분');
  });
  it('renders sub-day uptime as "Hh M분"', () => {
    // 3700 s = 1 h 1 min 40 s; output truncates to "1시간 1분".
    expect(formatUptimeKo(1, 3701)).toBe('1시간 1분');
  });
  it('renders multi-day uptime as "Dd Hh"', () => {
    // 90000 s = 1 day 1 hour.
    expect(formatUptimeKo(1, 90001)).toBe('1일 1시간');
  });
  it('renders an exact day boundary as just "D일"', () => {
    expect(formatUptimeKo(1, 86401)).toBe('1일');
  });
  it('clamps to 0 when active_since is in the future (clock skew)', () => {
    expect(formatUptimeKo(1000, 500)).toBe('0초');
  });
});

describe('formatBytesBinaryShort (Track B-SYSTEM PR-2)', () => {
  it('returns "—" for null', () => {
    expect(formatBytesBinaryShort(null)).toBe('—');
  });
  it('renders sub-KiB as raw bytes', () => {
    expect(formatBytesBinaryShort(1023)).toBe('1023 B');
  });
  it('renders 1024 as 1 KiB', () => {
    expect(formatBytesBinaryShort(1024)).toBe('1 KiB');
  });
  it('renders ~51 MiB as "51 MiB" (S4 fold corpus)', () => {
    expect(formatBytesBinaryShort(53477376)).toBe('51 MiB');
  });
  it('renders 2 GiB with 2 decimals', () => {
    expect(formatBytesBinaryShort(2 * 1024 * 1024 * 1024)).toBe('2.00 GiB');
  });
});
