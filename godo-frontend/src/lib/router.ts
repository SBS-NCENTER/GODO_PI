/**
 * Minimal hash-router for Svelte 5.
 *
 * Why home-grown: per N9 in the plan, `svelte-spa-router@4` declares itself
 * as "Router for SPAs using Svelte 4" and Svelte 5's runes/rendering pipeline
 * has subtle behavioural differences. A 30-line hash router is lower risk
 * than depending on a library that explicitly targets a prior major version.
 *
 * Behaviour:
 *   - Reads `location.hash` (the "/foo" part, with a `#` prefix in the URL).
 *   - Empty hash maps to "/" so the first paint matches the dashboard.
 *   - `navigate(path)` updates `location.hash`, which fires `hashchange`
 *     and pushes the entry into the browser history (back-button works).
 *   - The exported `currentPath` is a Svelte 5 rune; subscribers re-render
 *     when the hash changes.
 *
 * Param-style routes (e.g. `/users/:id`) are NOT supported because we don't
 * need them in P0 — every P0 route is a static path.
 */

const DEFAULT_PATH = '/';

function readHashPath(): string {
  // location.hash includes the leading '#'; strip it.
  const raw = typeof window === 'undefined' ? '' : window.location.hash.replace(/^#/, '');
  return raw || DEFAULT_PATH;
}

// Svelte 5 rune-backed reactive state. We use `$state` indirectly via the
// `route` store class so this module stays plain TS (not .svelte.ts) and
// can be unit-tested without a Svelte runtime.
class RouteState {
  private _path: string;
  private _listeners = new Set<(p: string) => void>();

  constructor() {
    this._path = readHashPath();
    if (typeof window !== 'undefined') {
      window.addEventListener('hashchange', () => this._update(readHashPath()));
    }
  }

  get path(): string {
    return this._path;
  }

  subscribe(fn: (p: string) => void): () => void {
    this._listeners.add(fn);
    fn(this._path);
    return () => this._listeners.delete(fn);
  }

  private _update(p: string): void {
    if (p === this._path) return;
    this._path = p;
    for (const fn of this._listeners) fn(p);
  }
}

export const route = new RouteState();

export function navigate(path: string): void {
  if (typeof window === 'undefined') return;
  if (!path.startsWith('/')) path = '/' + path;
  // Setting location.hash dispatches the hashchange event for us.
  window.location.hash = path;
}

/**
 * Resolve a path against a route table. Returns the matched component or
 * null. Exact match only (no params).
 */
export function matchRoute<T>(path: string, table: Record<string, T>): T | null {
  if (path in table) return table[path] as T;
  return null;
}
