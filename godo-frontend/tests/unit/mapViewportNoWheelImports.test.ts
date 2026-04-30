/**
 * PR β — Mode-A T5 mechanical wheel-zoom-removal pin
 *   + issue#2.2 pinch-zoom carve-out.
 *
 * Operator-locked Rule 1: **scroll-wheel zoom is forbidden**. Trackpad
 * pinch (synthetic `wheel` event with `ctrlKey === true`) is allowed —
 * scroll = page scroll, pinch = zoom. The `ctrlKey` gate is the
 * structural witness that distinguishes the two.
 *
 * Pins:
 *   1. `MAP_WHEEL_ZOOM_FACTOR` is undefined in `lib/constants.ts`
 *      (no scroll-wheel zoom factor; pinch uses the same `MAP_ZOOM_STEP`
 *      as the (+/−) buttons).
 *   2. The ONLY `.svelte` file under `src/components`/`src/routes`
 *      that contains `onwheel=` is `MapUnderlay.svelte`, AND its handler
 *      checks `e.ctrlKey` before reacting (pinch-only). Any other file
 *      with `onwheel=` is a regression.
 *   3. No `.svelte` or `.ts` file under those folders registers a
 *      `'wheel'` listener via `addEventListener` (the imperative path
 *      bypasses the source-grep ctrlKey check; force the Svelte-attr
 *      idiom).
 */

import { describe, expect, it } from 'vitest';
import * as constants from '../../src/lib/constants';

const svelteFiles = import.meta.glob<string>(
  ['../../src/components/*.svelte', '../../src/routes/*.svelte'],
  { eager: true, query: '?raw', import: 'default' },
);
const tsFiles = import.meta.glob<string>(
  ['../../src/components/*.ts', '../../src/routes/*.ts', '../../src/lib/*.ts'],
  { eager: true, query: '?raw', import: 'default' },
);

const PINCH_ALLOWED_FILE = '../../src/components/MapUnderlay.svelte';

describe('PR β + issue#2.2 — wheel-zoom-removal structural pin (pinch carve-out)', () => {
  it('case 1: MAP_WHEEL_ZOOM_FACTOR is gone from lib/constants.ts', () => {
    const value = (constants as Record<string, unknown>).MAP_WHEEL_ZOOM_FACTOR;
    expect(value).toBeUndefined();
  });

  it('case 2: only MapUnderlay.svelte has onwheel=, and its handler is ctrlKey-gated', () => {
    const offenders: string[] = [];
    for (const [path, content] of Object.entries(svelteFiles)) {
      const lower = String(content).toLowerCase();
      const hasOnWheel = lower.includes('onwheel=') || lower.includes('onwheel ');
      if (!hasOnWheel) continue;

      if (path !== PINCH_ALLOWED_FILE) {
        offenders.push(`${path} (only MapUnderlay may register wheel handlers)`);
        continue;
      }

      // The MapUnderlay handler MUST check ctrlKey before zooming —
      // operator-locked: scroll without ctrl = page scroll, NOT zoom.
      const text = String(content);
      if (!text.includes('e.ctrlKey') && !text.includes('event.ctrlKey')) {
        offenders.push(`${path} (onwheel handler missing ctrlKey check)`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('case 3: no .svelte or .ts file registers a "wheel" listener via addEventListener', () => {
    const offenders: string[] = [];
    const all = { ...svelteFiles, ...tsFiles };
    for (const [path, content] of Object.entries(all)) {
      const text = String(content);
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
