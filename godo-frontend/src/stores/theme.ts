/**
 * Theme store: 'light' | 'dark', persisted in localStorage.
 *
 * Default is 'light' (per FRONT_DESIGN §3 G-Q4). Changes are reflected
 * onto the document root via the `data-theme` attribute, which the CSS
 * variable map in `styles/tokens.css` keys off.
 */

import { writable, type Writable } from 'svelte/store';
import { STORAGE_KEY_THEME } from '$lib/constants';

export type Theme = 'light' | 'dark';

const VALID_THEMES: ReadonlySet<Theme> = new Set<Theme>(['light', 'dark']);

function loadInitial(): Theme {
  if (typeof localStorage === 'undefined') return 'light';
  const raw = localStorage.getItem(STORAGE_KEY_THEME);
  if (raw && (VALID_THEMES as Set<string>).has(raw)) return raw as Theme;
  return 'light';
}

export const theme: Writable<Theme> = writable(loadInitial());

theme.subscribe((t) => {
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', t);
  }
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY_THEME, t);
  }
});

export function toggleTheme(): void {
  theme.update((t) => (t === 'light' ? 'dark' : 'light'));
}
