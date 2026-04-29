/**
 * Korean-friendly formatters for the topbar countdown and pose readouts.
 *
 * Engineering terms (Hz, std, m, deg) stay in English per CLAUDE.md.
 */

const SECS_PER_HOUR = 3600;
const SECS_PER_MIN = 60;

/**
 * Render `secondsRemaining` as "Xh Ym" (or "Ym Zs" when < 1 h).
 * Used by the topbar "X후 만료" countdown.
 */
export function formatRemaining(secondsRemaining: number): string {
  if (secondsRemaining <= 0) return '만료됨';
  const total = Math.floor(secondsRemaining);
  const h = Math.floor(total / SECS_PER_HOUR);
  const m = Math.floor((total % SECS_PER_HOUR) / SECS_PER_MIN);
  const s = total % SECS_PER_MIN;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

/**
 * Render unix-seconds as a HH:MM:SS local-time string. Used by the
 * activity feed.
 */
export function formatTimeOfDay(unixSec: number): string {
  const d = new Date(unixSec * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * Format a meter value as "X.XX m" (2 decimal places).
 */
export function formatMeters(m: number): string {
  return `${m.toFixed(2)} m`;
}

/**
 * Format a degree value as "X.X°".
 */
export function formatDegrees(d: number): string {
  return `${d.toFixed(1)}°`;
}

const SECS_PER_DAY = 86400;

/**
 * Render a duration (in seconds) as a Korean uptime string.
 *
 *   0       → "0초"
 *   90      → "1분 30초"
 *   3700    → "1시간 1분"
 *   90000   → "1일 1시간"
 *
 * `now_unix` is the wall-clock the SPA reads for "now"; the caller passes
 * `Date.now() / 1000` (or a frozen value in tests). When
 * `active_since_unix` is null/0 (service is not active), returns "—".
 */
export function formatUptimeKo(active_since_unix: number | null, now_unix: number): string {
  if (!active_since_unix || active_since_unix <= 0) return '—';
  const total = Math.max(0, Math.floor(now_unix - active_since_unix));
  if (total === 0) return '0초';
  const d = Math.floor(total / SECS_PER_DAY);
  const h = Math.floor((total % SECS_PER_DAY) / SECS_PER_HOUR);
  const m = Math.floor((total % SECS_PER_HOUR) / SECS_PER_MIN);
  const s = total % SECS_PER_MIN;
  if (d > 0) return h > 0 ? `${d}일 ${h}시간` : `${d}일`;
  if (h > 0) return m > 0 ? `${h}시간 ${m}분` : `${h}시간`;
  if (m > 0) return s > 0 ? `${m}분 ${s}초` : `${m}분`;
  return `${s}초`;
}

const KIB = 1024;
const MIB = KIB * 1024;
const GIB = MIB * 1024;

/**
 * Format a byte count using base-1024 units (KiB / MiB / GiB).
 *
 *   null    → "—"
 *   1024    → "1 KiB"
 *   53477376 → "51 MiB"
 *
 * S4 fold rename: was `formatBytesShort`; renamed to `formatBytesBinaryShort`
 * to make the base-1024 contract explicit (vs. a base-1000 sibling).
 */
export function formatBytesBinaryShort(n: number | null): string {
  if (n === null || n === undefined) return '—';
  if (n < KIB) return `${n} B`;
  if (n < MIB) return `${Math.round(n / KIB)} KiB`;
  if (n < GIB) return `${Math.round(n / MIB)} MiB`;
  return `${(n / GIB).toFixed(2)} GiB`;
}
