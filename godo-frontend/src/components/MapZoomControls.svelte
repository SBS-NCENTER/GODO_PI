<svelte:options runes={true} />

<script lang="ts">
  /**
   * PR β — top-left absolute-positioned zoom controls.
   *
   * (+) and (−) buttons + a `<input type="text" inputmode="decimal">`
   * showing the current zoom percentage. Operators can:
   *   - Click (+) / (−) for `MAP_ZOOM_STEP` discrete steps.
   *   - Type a percentage and commit via blur OR Enter (Mode-A N3 —
   *     BOTH triggers call `setZoomFromPercent`).
   *
   * Validation reuses the OriginPicker idiom (PR #43):
   * `type="text" inputmode="decimal"`, locale-comma `1,234` rejected,
   * NaN/Inf rejected, out-of-range soft-clamps. Inline error indicator
   * (`.input-invalid` class — same idiom). Korean copy mirrors the
   * OriginPicker banner messages (Mode-A N1).
   *
   * **Mouse-wheel zoom is forbidden** (Rule 1 — operator-locked). This
   * component does NOT register a `wheel` listener anywhere; doing so
   * would re-introduce the UX `MAP_WHEEL_ZOOM_FACTOR` was deleted to
   * prevent. See `mapViewportNoWheelImports.test.ts` for the structural
   * pin.
   */
  import { formatZoomPercent, parsePercent, type MapViewport } from '$lib/mapViewport.svelte';

  interface Props {
    viewport: MapViewport;
  }

  const { viewport }: Props = $props();

  // Local input buffer + parse error. Re-derived from `viewport.zoom`
  // whenever the operator is NOT actively editing (i.e. the input has
  // no focus). Tracking focus avoids fighting the user's keystrokes.
  let editing = $state(false);
  let inputBuf = $state(formatZoomPercent(viewport.zoom));
  let parseErr = $state<'empty' | 'locale_comma' | 'not_finite' | null>(null);

  // Re-render the buffer whenever zoom changes externally (e.g. (+/−)
  // click) AND the operator isn't mid-edit AND there's no sticky parse
  // error to display. A sticky parse error means the operator's last
  // commit was rejected; the input keeps the invalid value visible
  // until they type something else.
  $effect(() => {
    if (!editing && parseErr === null) {
      inputBuf = formatZoomPercent(viewport.zoom);
    } else {
      // Touch viewport.zoom so the effect retracks; intentional re-read.
      void viewport.zoom;
    }
  });

  /**
   * Try to commit the current input buffer. Returns `true` on success
   * (caller can end the edit), `false` on validation error (caller
   * should leave editing-mode active so the operator sees the
   * highlighted invalid input).
   */
  function commitInput(): boolean {
    const parsed = parsePercent(inputBuf);
    if (parsed.error !== null) {
      parseErr = parsed.error;
      return false;
    }
    parseErr = null;
    if (parsed.value !== null) {
      // Convert ratio back to percent for the factory's clamp + assign.
      // (parsePercent returns a ratio; setZoomFromPercent takes percent.)
      viewport.setZoomFromPercent(parsed.value * 100);
      // Re-render the buffer to whatever the factory clamped to.
      inputBuf = formatZoomPercent(viewport.zoom);
    }
    return true;
  }

  function onInputFocus(): void {
    editing = true;
    // Clear any sticky parse error from a previous commit so the
    // first keystroke shows green again.
    parseErr = null;
  }

  function onInputBlur(): void {
    if (commitInput()) {
      editing = false;
    }
  }

  function onInputKeydown(e: KeyboardEvent): void {
    if (e.key === 'Enter') {
      if (commitInput()) {
        // Operator mental model: Enter ends the edit (matches blur).
        // Without this, subsequent external zoom changes (e.g. (+/−)
        // clicks while focus stays on the input) wouldn't update the
        // displayed value.
        editing = false;
      }
    }
  }

  function onZoomIn(): void {
    viewport.zoomIn();
  }

  function onZoomOut(): void {
    viewport.zoomOut();
  }

  function errorMessage(err: 'empty' | 'locale_comma' | 'not_finite' | null): string {
    if (err === 'locale_comma') return '쉼표(,) 대신 점(.)을 사용하세요. 예: 150';
    if (err === 'not_finite') return '유한하지 않은 값입니다.';
    if (err === 'empty') return '값을 입력하세요.';
    return '';
  }
</script>

<div class="map-zoom-controls" data-testid="map-zoom-controls">
  <button
    type="button"
    class="zoom-btn"
    onclick={onZoomOut}
    data-testid="map-zoom-out-btn"
    aria-label="Zoom out"
  >
    −
  </button>
  <input
    type="text"
    inputmode="decimal"
    class="zoom-input {parseErr ? 'input-invalid' : ''}"
    bind:value={inputBuf}
    onfocus={onInputFocus}
    onblur={onInputBlur}
    onkeydown={onInputKeydown}
    data-testid="map-zoom-input"
    aria-label="Zoom percentage"
  />
  <span class="percent-glyph">%</span>
  <button
    type="button"
    class="zoom-btn"
    onclick={onZoomIn}
    data-testid="map-zoom-in-btn"
    aria-label="Zoom in"
  >
    +
  </button>
  {#if parseErr}
    <span class="zoom-error" data-testid="map-zoom-error">
      {errorMessage(parseErr)}
    </span>
  {/if}
</div>

<style>
  .map-zoom-controls {
    position: absolute;
    top: 12px;
    left: 12px;
    z-index: 10;
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 4px 6px;
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
  }
  .zoom-btn {
    width: 26px;
    height: 26px;
    line-height: 1;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    cursor: pointer;
    font-size: 16px;
    padding: 0;
  }
  .zoom-btn:hover {
    border-color: var(--color-accent);
  }
  .zoom-input {
    width: 4em;
    padding: 2px 4px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    text-align: right;
    font-size: 14px;
  }
  .zoom-input:focus {
    outline: 1px solid var(--color-accent);
  }
  .input-invalid {
    border-color: var(--color-error, #c62828);
  }
  .percent-glyph {
    color: var(--color-text-muted, #666);
    font-size: 14px;
  }
  .zoom-error {
    margin-left: 8px;
    color: var(--color-error, #c62828);
    font-size: 12px;
  }
</style>
