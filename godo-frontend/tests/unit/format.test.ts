/**
 * Unit tests for `lib/format.ts` — covers the two new Track B-SYSTEM
 * formatters (`formatUptimeKo`, `formatBytesBinaryShort`) plus a sanity
 * pin on the existing trio (`formatRemaining`, `formatMeters`,
 * `formatDegrees`).
 */

import { describe, expect, it } from 'vitest';
import {
  backupMapNames,
  backupTsToUnix,
  formatBytesBinaryShort,
  formatDateTime,
  formatDegrees,
  formatMeters,
  formatRemaining,
  formatTimeOfDay,
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

describe('formatTimeOfDay (existing)', () => {
  // Sanity pin: the helper is still used by the dashboard activity feed
  // after the 2026-05-01 list-view migration to formatDateTime.
  it('renders host-local HH:MM:SS with zero-padding', () => {
    const unixSec = 1735776645; // arbitrary; reproducible across hosts.
    const d = new Date(unixSec * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    const expected = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    expect(formatTimeOfDay(unixSec)).toBe(expected);
  });
});

describe('formatDateTime (issue#13-list-view-timestamp)', () => {
  // We pin against host-local Date getters rather than a literal so the test
  // passes on KST CI as well as on a developer's UTC laptop. The contract
  // under test is the *shape* "YYYY-MM-DD HH:MM" + zero-padding, not a
  // particular wall-clock interpretation.
  it('renders "YYYY-MM-DD HH:MM" matching the host-local Date components', () => {
    const unixSec = 1735776645; // 2025-01-02T01:30:45Z (varies per TZ).
    const d = new Date(unixSec * 1000);
    const pad = (n: number) => String(n).padStart(2, '0');
    const expected =
      `${String(d.getFullYear()).padStart(4, '0')}-` +
      `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
      `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    expect(formatDateTime(unixSec)).toBe(expected);
  });
  it('zero-pads single-digit month / day / hour / minute', () => {
    // Pick a unix-second whose KST wall-clock components are all single-digit.
    // 2026-01-02T01:01:00Z = 2026-01-02 10:01 KST. We assert the *shape*
    // matches the regex regardless of host TZ.
    const unixSec = 1767315660;
    const out = formatDateTime(unixSec);
    expect(out).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  });
  it('matches no timezone marker (length is exactly 16 chars)', () => {
    // "YYYY-MM-DD HH:MM" is 16 characters; rule out an accidental " KST"
    // suffix or "Z" tail.
    expect(formatDateTime(1735776645)).toHaveLength(16);
  });
  it('handles unix epoch (0) without crashing', () => {
    expect(formatDateTime(0)).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
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

describe('backupTsToUnix (issue#32)', () => {
  // Pin both legacy UTC and post-PR #83 KST forms — the 9-hour offset
  // between them is what made operators notice the bug.
  it('parses Z-suffixed stamp as UTC', () => {
    // 2026-01-01T01:01:01Z → known unix-seconds.
    const expected = Date.UTC(2026, 0, 1, 1, 1, 1) / 1000;
    expect(backupTsToUnix('20260101T010101Z')).toBe(expected);
  });
  it('parses no-suffix stamp as KST (+09:00)', () => {
    // 2026-05-05T11:26:00+09:00 = 2026-05-05T02:26:00Z.
    const expected = Date.UTC(2026, 4, 5, 2, 26, 0) / 1000;
    expect(backupTsToUnix('20260505T112600')).toBe(expected);
  });
  it('Z and no-Z forms differing by 9 hours represent the SAME wall time', () => {
    // `20260505T112600Z` (UTC 11:26) ↔ `20260505T202600` (KST 20:26).
    // Both denote the same instant. This is the contract that makes the
    // operator-facing display correct on both legacy and post-PR-#83
    // backups.
    expect(backupTsToUnix('20260505T112600Z')).toBe(backupTsToUnix('20260505T202600'));
  });
  it('returns NaN on malformed stamp', () => {
    expect(backupTsToUnix('not-a-stamp')).toBeNaN();
    expect(backupTsToUnix('20260101010101Z')).toBeNaN(); // missing T
    expect(backupTsToUnix('')).toBeNaN();
  });
});

describe('backupMapNames (issue#33)', () => {
  it('extracts shared stem from pgm + yaml + sidecar.json triple', () => {
    expect(
      backupMapNames([
        'chroma.20260504-143000-wallcal01.pgm',
        'chroma.20260504-143000-wallcal01.yaml',
        'chroma.20260504-143000-wallcal01.sidecar.json',
      ]),
    ).toEqual(['chroma.20260504-143000-wallcal01']);
  });
  it('handles legacy pre-issue#30 backup with only pgm + yaml (no sidecar)', () => {
    expect(backupMapNames(['studio_v1.pgm', 'studio_v1.yaml'])).toEqual(['studio_v1']);
  });
  it('checks .sidecar.json suffix BEFORE .yaml/.pgm so the .sidecar segment is preserved', () => {
    // Regression guard: a naive `f.slice(0, f.lastIndexOf('.'))` would
    // strip only `.json` and leave `chroma.sidecar` in the stem. The
    // helper must strip `.sidecar.json` as one unit.
    expect(backupMapNames(['chroma.sidecar.json'])).toEqual(['chroma']);
  });
  it('returns sorted unique stems for a multi-map backup directory', () => {
    expect(
      backupMapNames([
        'beta.pgm',
        'alpha.pgm',
        'beta.yaml',
        'alpha.yaml',
        'alpha.sidecar.json',
      ]),
    ).toEqual(['alpha', 'beta']);
  });
  it('returns empty array for empty file list or unknown extensions', () => {
    expect(backupMapNames([])).toEqual([]);
    expect(backupMapNames(['README.txt', 'note.md'])).toEqual([]);
  });
});
