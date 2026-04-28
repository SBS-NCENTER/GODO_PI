import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vitest/config';
import { svelte, vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/**
 * Dedicated vitest config.
 *
 * The production vite config (`vite.config.ts`) wires the svelte plugin
 * with the project default `svelte.config.js`, which uses
 * `vitePreprocess()` (CSS + script). Under vitest's transform pipeline
 * the CSS preprocess stage creates a `PartialEnvironment` proxy that
 * `preprocessCSS` cannot consume, so component-mount tests like
 * `tests/unit/map_list_panel.test.ts` fail with "Cannot create proxy
 * with a non-object as target or handler".
 *
 * Workaround: vitest gets its own svelte plugin instance with
 * `configFile: false` (skip auto-loading `svelte.config.js`) and an
 * inline preprocess config that processes only the script block. None
 * of our `<style>` blocks use a non-CSS lang, so dropping style
 * preprocessing has no functional effect for tests.
 */
export default defineConfig({
  plugins: [
    svelte({
      configFile: false,
      compilerOptions: { runes: true },
      preprocess: vitePreprocess({ style: false }),
    }),
  ],
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL('./src/lib', import.meta.url)),
      $stores: fileURLToPath(new URL('./src/stores', import.meta.url)),
      $components: fileURLToPath(new URL('./src/components', import.meta.url)),
    },
    // Force the browser entry of svelte under jsdom so `mount(...)` is
    // available. Without `browser` in the resolve conditions, svelte's
    // exports map falls through to the server build which throws
    // `lifecycle_function_unavailable` on `mount`.
    conditions: ['browser'],
  },
  test: {
    environment: 'jsdom',
    globals: false,
    include: ['tests/unit/**/*.test.ts'],
  },
});
