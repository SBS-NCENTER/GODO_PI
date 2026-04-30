<script lang="ts">
  /**
   * Track B-MAPEDIT-2 — origin-pick controls.
   *
   * Sole owner of the dual-input origin form state per
   * `godo-frontend/CODEBASE.md` invariant (aa). The Edit sub-tab's
   * parent route (`MapEdit.svelte`) orchestrates layout + the
   * `'paint' | 'origin-pick'` click-mode toggle on `MapMaskCanvas`,
   * but does NOT mirror any of the form fields in a store.
   *
   * Two input modes:
   *   - Mode A (GUI pick): parent route's pointer-coord callback calls
   *     `setCandidate({x_m, y_m})` to pre-fill the absolute fields.
   *     This component flips its own mode toggle to `'absolute'`
   *     (a click is unambiguously an absolute world coord) before
   *     populating the inputs.
   *   - Mode B (numeric entry): operator types `x_m` / `y_m` directly
   *     and toggles `mode` between `absolute` and `delta`.
   *
   * Apply path emits via the `onapply` callback prop with a fully
   * validated `OriginPatchBody`. Parents handle the actual fetch +
   * success/error banner orchestration.
   *
   * Operator-locked rules (do NOT regress):
   *   - Both inputs MUST be visible side-by-side at all times. Single-
   *     input is a regression.
   *   - `mode === "delta"` uses ADD: `new_origin = current + (x_m, y_m)`.
   *     Korean copy MUST say "더해서" (NOT "빼서").
   *   - Locale-comma decimals (`1,234.5`) are rejected — `.` only.
   */

  import { ORIGIN_DECIMAL_DISPLAY_MM, ORIGIN_X_Y_ABS_MAX_M } from '$lib/constants';
  import type { OriginMode, OriginPatchBody } from '$lib/protocol';

  interface Props {
    currentOrigin: readonly [number, number, number] | null;
    role: 'admin' | 'viewer' | null;
    busy: boolean;
    bannerMsg: string | null;
    bannerKind: 'info' | 'success' | 'error' | null;
    onapply: (body: OriginPatchBody) => void;
  }

  const { currentOrigin, role, busy, bannerMsg, bannerKind, onapply }: Props = $props();

  // Form state — owned exclusively by this component.
  let mode = $state<OriginMode>('absolute');
  let xText = $state<string>('');
  let yText = $state<string>('');
  let inlineError = $state<string | null>(null);

  // Parsed values (null when the corresponding input is empty/invalid).
  // Kept derived rather than stored so the validation rule lives in
  // one place. `text` is the raw <input> string — using type="text"
  // (not type="number") preserves the original characters so we can
  // explicitly reject the locale-comma decimal at the SPA layer.
  function parseField(text: string): { value: number | null; error: string | null } {
    if (text === null || text === undefined) {
      return { value: null, error: 'empty' };
    }
    const trimmed = String(text).trim();
    if (trimmed === '') {
      return { value: null, error: 'empty' };
    }
    if (trimmed.includes(',')) {
      // Locale-comma rejected explicitly so a Windows browser pasting
      // `1,234.5` does NOT silently coerce to `1.234`.
      return { value: null, error: 'locale_comma' };
    }
    const v = Number(trimmed);
    if (!Number.isFinite(v)) {
      return { value: null, error: 'not_finite' };
    }
    if (Math.abs(v) > ORIGIN_X_Y_ABS_MAX_M) {
      return { value: null, error: 'out_of_bound' };
    }
    return { value: v, error: null };
  }

  let xParsed = $derived(parseField(xText));
  let yParsed = $derived(parseField(yText));

  let bothValid = $derived(xParsed.value !== null && yParsed.value !== null);

  let applyDisabled = $derived(busy || role !== 'admin' || !bothValid);

  function clearBanner(): void {
    inlineError = null;
  }

  function fmtDisplay(v: number): string {
    return v.toFixed(ORIGIN_DECIMAL_DISPLAY_MM);
  }

  // Imperative API — invoked by the parent's GUI-pick handler. Per
  // T1 fold: setCandidate also flips the mode to `'absolute'` (a click
  // on the canvas is unambiguously an absolute world coord).
  export function setCandidate(c: { x_m: number; y_m: number }): void {
    mode = 'absolute';
    xText = fmtDisplay(c.x_m);
    yText = fmtDisplay(c.y_m);
    inlineError = null;
  }

  function onApplyClick(): void {
    if (applyDisabled) return;
    if (xParsed.value === null || yParsed.value === null) {
      inlineError = 'inputs_invalid';
      return;
    }
    onapply({ x_m: xParsed.value, y_m: yParsed.value, mode });
  }

  function onDiscardClick(): void {
    if (busy) return;
    xText = '';
    yText = '';
    inlineError = null;
  }
</script>

<section class="origin-picker" data-testid="origin-picker">
  <h3 class="picker-title">Origin pick</h3>

  <div class="mode-row" role="radiogroup" aria-label="origin mode">
    <label class="radio-label">
      <input
        type="radio"
        name="origin-mode"
        value="absolute"
        checked={mode === 'absolute'}
        onchange={() => {
          mode = 'absolute';
          clearBanner();
        }}
        disabled={busy || role !== 'admin'}
        data-testid="origin-mode-absolute"
      />
      Absolute
    </label>
    <label class="radio-label">
      <input
        type="radio"
        name="origin-mode"
        value="delta"
        checked={mode === 'delta'}
        onchange={() => {
          mode = 'delta';
          clearBanner();
        }}
        disabled={busy || role !== 'admin'}
        data-testid="origin-mode-delta"
      />
      Delta
    </label>
  </div>

  <div class="number-row">
    <label class="num-label">
      x_m:
      <input
        type="text"
        inputmode="decimal"
        bind:value={xText}
        oninput={clearBanner}
        disabled={busy || role !== 'admin'}
        data-testid="origin-x-input"
        class={xParsed.error && xText !== '' ? 'input-invalid' : ''}
      />
      m
    </label>
    <label class="num-label">
      y_m:
      <input
        type="text"
        inputmode="decimal"
        bind:value={yText}
        oninput={clearBanner}
        disabled={busy || role !== 'admin'}
        data-testid="origin-y-input"
        class={yParsed.error && yText !== '' ? 'input-invalid' : ''}
      />
      m
    </label>
  </div>

  {#if currentOrigin !== null}
    <p class="muted current-origin" data-testid="origin-current">
      현재 origin: ({fmtDisplay(currentOrigin[0])}, {fmtDisplay(currentOrigin[1])},
      {(currentOrigin[2] * (180 / Math.PI)).toFixed(1)}°)
    </p>
  {/if}

  {#if mode === 'delta'}
    <p class="muted hint" data-testid="origin-delta-hint">
      Delta: 입력한 값을 현재 origin에 <strong>더해서</strong> 새 origin이 됩니다.
    </p>
  {/if}

  <div class="actions">
    <button
      type="button"
      class="btn-secondary"
      onclick={onDiscardClick}
      disabled={busy}
      data-testid="origin-discard-btn"
    >
      Discard
    </button>
    <button
      type="button"
      class="btn-primary"
      onclick={onApplyClick}
      disabled={applyDisabled}
      data-testid="origin-apply-btn"
      title={role !== 'admin' ? '제어 동작은 로그인 필요' : ''}
    >
      Apply origin
    </button>
  </div>

  {#if inlineError}
    <p class="banner banner-error" data-testid="origin-banner">
      {inlineError === 'locale_comma'
        ? '쉼표(,) 대신 점(.)을 사용하세요. 예: 1.5'
        : inlineError === 'not_finite'
          ? '유한하지 않은 값입니다.'
          : inlineError === 'out_of_bound'
            ? `값의 절댓값이 ${ORIGIN_X_Y_ABS_MAX_M} m를 넘습니다.`
            : '입력 값이 잘못되었습니다.'}
    </p>
  {:else if bannerMsg}
    <p class="banner banner-{bannerKind ?? 'info'}" data-testid="origin-banner">{bannerMsg}</p>
  {/if}

  <p class="hint">적용 후 godo-tracker를 재시작해야 효과가 반영됩니다.</p>
</section>

<style>
  .origin-picker {
    margin-top: 16px;
    padding: 12px;
    border: 1px solid var(--color-border);
    border-radius: 4px;
  }
  .picker-title {
    margin: 0 0 8px;
    font-size: 1em;
  }
  .mode-row {
    display: flex;
    gap: 16px;
    margin: 4px 0;
  }
  .radio-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .number-row {
    display: flex;
    gap: 16px;
    margin: 8px 0;
    flex-wrap: wrap;
  }
  .num-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
  }
  .num-label input {
    width: 8em;
  }
  .input-invalid {
    border-color: var(--color-error, #c62828);
  }
  .current-origin {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 0.9em;
  }
  .muted {
    color: var(--color-text-muted, #666);
  }
  .actions {
    display: flex;
    gap: 8px;
    margin-top: 8px;
  }
  .banner {
    padding: 6px 10px;
    border-left: 3px solid var(--color-accent);
    margin-top: 8px;
    font-size: 0.9em;
  }
  .banner-success {
    border-left-color: #2e7d32;
    background: color-mix(in srgb, #2e7d32 10%, var(--color-bg));
  }
  .banner-error {
    border-left-color: var(--color-error, #c62828);
    background: color-mix(in srgb, var(--color-error, #c62828) 10%, var(--color-bg));
  }
  .hint {
    margin-top: 8px;
    font-size: 0.85em;
    color: var(--color-text-muted, #666);
  }
</style>
