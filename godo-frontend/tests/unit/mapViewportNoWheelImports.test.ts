/**
 * PR β — Mode-A T5 mechanical wheel-zoom-removal pin.
 *
 * Operator-locked Rule 1: mouse-wheel zoom is forbidden. This test
 * makes the absence of wheel-zoom code STRUCTURAL — a writer who
 * leaves a stale constant or sneaks in a `wheel`/`onwheel` listener
 * fails CI even if their UX-level test happens to pass.
 *
 * Three pins:
 *   1. `MAP_WHEEL_ZOOM_FACTOR` is undefined in `lib/constants.ts`.
 *   2. No `.svelte` file under `src/components` or `src/routes`
 *      contains `onwheel=` or `onWheel`.
 *   3. No `.svelte` or `.ts` file under those folders registers a
 *      `'wheel'` listener via `addEventListener`.
 *
 * Belt-and-braces against drive-by-leaving (the constant is unused →
 * type-checks pass → bundle ships → "harmless" but it's structural rot).
 */

import { describe, expect, it } from 'vitest';
import * as constants from '../../src/lib/constants';

// Vite's import.meta.glob with `?raw` reads file contents at build
// time — same idiom used by other "all files satisfy X" pins in this
// repo. The glob captures `.svelte` AND `.ts` so a writer can't sneak
// in a non-Svelte `addEventListener('wheel', ...)`.
const svelteFiles = import.meta.glob<string>(
  ['../../src/components/*.svelte', '../../src/routes/*.svelte'],
  { eager: true, query: '?raw', import: 'default' },
);
const tsFiles = import.meta.glob<string>(
  ['../../src/components/*.ts', '../../src/routes/*.ts', '../../src/lib/*.ts'],
  { eager: true, query: '?raw', import: 'default' },
);

describe('PR β — wheel-zoom-removal structural pin (Mode-A T5)', () => {
  it('case 1: MAP_WHEEL_ZOOM_FACTOR is gone from lib/constants.ts', () => {
    // The constant was deleted; `(constants as Record<string, unknown>).MAP_WHEEL_ZOOM_FACTOR`
    // resolves to undefined. A writer who re-adds it fails this case.
    const value = (constants as Record<string, unknown>).MAP_WHEEL_ZOOM_FACTOR;
    expect(value).toBeUndefined();
  });

  it('case 2: no .svelte file under src/components or src/routes contains "onwheel=" or "onWheel"', () => {
    const offenders: string[] = [];
    for (const [path, content] of Object.entries(svelteFiles)) {
      // Lower-cased test catches both `onwheel=` (Svelte 5 idiom) and
      // any `onWheel` / `OnWheel` mixed-case variant.
      const lower = String(content).toLowerCase();
      if (lower.includes('onwheel=') || lower.includes('onwheel ')) {
        offenders.push(path);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('case 3: no .svelte or .ts file under src/components/routes/lib registers a "wheel" listener', () => {
    const offenders: string[] = [];
    const all = { ...svelteFiles, ...tsFiles };
    for (const [path, content] of Object.entries(all)) {
      const text = String(content);
      // Catches `addEventListener('wheel'` / `addEventListener("wheel"` /
      // `addEventListener(\`wheel\``.
      if (
        text.includes("addEventListener('wheel'") ||
        text.includes('addEventListener("wheel"') ||
        text.includes('addEventListener(`wheel`')
      ) {
        offenders.push(path);
      }
    }
    expect(offenders).toEqual([]);
  });
});
