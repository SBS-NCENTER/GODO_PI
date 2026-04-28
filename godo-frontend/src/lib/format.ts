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
