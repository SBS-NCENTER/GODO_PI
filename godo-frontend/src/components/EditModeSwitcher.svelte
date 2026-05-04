<script lang="ts">
  /**
   * issue#28 — segmented control for the MapEdit page.
   *
   * Sole owner of the per-edit-mode state in `<MapEdit>`. Mode switch
   * does NOT auto-discard the other mode's pending state — operator
   * can swap brush/origin tabs without losing work. Korean tooltip
   * pinned via `EDIT_MODE_SWITCH_TOOLTIP_KO`.
   */

  import {
    EDIT_MODE_COORD,
    EDIT_MODE_ERASE,
    EDIT_MODE_SWITCH_TOOLTIP_KO,
  } from '../lib/constants.js';

  type Mode = typeof EDIT_MODE_COORD | typeof EDIT_MODE_ERASE;

  interface Props {
    mode: Mode;
    onChange: (next: Mode) => void;
  }

  let { mode = $bindable(EDIT_MODE_COORD), onChange }: Props = $props();

  function pick(next: Mode): void {
    if (next === mode) return;
    mode = next;
    onChange(next);
  }
</script>

<div
  class="edit-mode-switcher"
  role="group"
  aria-label="Map edit mode"
  title={EDIT_MODE_SWITCH_TOOLTIP_KO}
>
  <button
    type="button"
    class="seg"
    class:active={mode === EDIT_MODE_COORD}
    aria-pressed={mode === EDIT_MODE_COORD}
    onclick={() => pick(EDIT_MODE_COORD)}
  >
    좌표 (Coordinate)
  </button>
  <button
    type="button"
    class="seg"
    class:active={mode === EDIT_MODE_ERASE}
    aria-pressed={mode === EDIT_MODE_ERASE}
    onclick={() => pick(EDIT_MODE_ERASE)}
  >
    지우기 (Erase)
  </button>
</div>

<style>
  .edit-mode-switcher {
    display: inline-flex;
    border: 1px solid var(--color-border, #cbd5e1);
    border-radius: 6px;
    overflow: hidden;
  }
  .seg {
    background: transparent;
    border: 0;
    padding: 6px 12px;
    cursor: pointer;
    font: inherit;
    color: var(--color-text, #1f2937);
  }
  .seg.active {
    background: var(--color-accent, #2563eb);
    color: var(--color-on-accent, #ffffff);
  }
  .seg + .seg {
    border-left: 1px solid var(--color-border, #cbd5e1);
  }
</style>
