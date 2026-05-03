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
   *   - Mode B (numeric entry): operator types `x_m` / `y_m` / `theta_deg`
   *     directly and toggles `mode` between `absolute` and `delta`.
   *
   * issue#27 additions:
   *   - `theta_deg` input row (sub-degree precision, ±180° bound).
   *     Backend converts deg → rad before writing to YAML.
   *   - +/- step buttons next to each numeric input. Step deltas come
   *     from the live /api/config response (`origin_step.x_m`,
   *     `.y_m`, `.yaw_deg`); fallback to the constants defaults
   *     when the config fetch is in flight.
   *   - SUBTRACT sign convention (operator-locked 2026-05-04 KST,
   *     supersedes 2026-04-30 ADD): typed (x_m, y_m) names the world
   *     coord that should become the new (0, 0). Korean copy says
   *     "이 좌표를 새 (0, 0)으로 만듭니다" instead of the previous
   *     "더해서" wording.
   *
   * Apply path emits via the `onapply` callback prop with a fully
   * validated `OriginPatchBody`. Parents handle the actual fetch +
   * success/error banner orchestration.
   */

  import { onDestroy, onMount } from 'svelte';
  import { apiGet } from '$lib/api';
  import {
    ORIGIN_DECIMAL_DISPLAY_MM,
    ORIGIN_STEP_X_M_DEFAULT,
    ORIGIN_STEP_Y_M_DEFAULT,
    ORIGIN_STEP_YAW_DEG_DEFAULT,
    ORIGIN_THETA_DEG_ABS_MAX,
    ORIGIN_X_Y_ABS_MAX_M,
  } from '$lib/constants';
  import { resolveDeltaFromPose } from '$lib/originMath';
  import type {
    ConfigGetResponse,
    LastPose,
    OriginMode,
    OriginPatchBody,
  } from '$lib/protocol';
  import { subscribeLastPose } from '$stores/lastPose';

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
  let thetaText = $state<string>('');
  let inlineError = $state<string | null>(null);

  // issue#27 — step deltas for the +/- buttons. Fetched from
  // /api/config on mount; fallback to constants defaults during the
  // fetch (or if it fails — UI stays usable). No reactive subscription:
  // schema rows are Restart class, so the value at mount time is the
  // operator's current spec for the session.
  let stepX = $state<number>(ORIGIN_STEP_X_M_DEFAULT);
  let stepY = $state<number>(ORIGIN_STEP_Y_M_DEFAULT);
  let stepYaw = $state<number>(ORIGIN_STEP_YAW_DEG_DEFAULT);

  // issue#27 Mode-B Maj-1 fix — delta mode resolves on the SPA side.
  // Frontend reads lastPose, computes `abs = current_pose + delta`,
  // sends absolute to backend so the backend stays dumb (single
  // SUBTRACT formula). Without this subscription the delta branch would
  // silently behave identically to absolute (the backend treats both
  // identically as SUBTRACT-of-typed; only the *meaning* differs).
  let lastPose = $state<LastPose | null>(null);
  let unsubLastPose: (() => void) | null = null;

  onMount(() => {
    void apiGet<ConfigGetResponse>('/api/config')
      .then((cfg) => {
        const sx = cfg['origin_step.x_m'];
        const sy = cfg['origin_step.y_m'];
        const syaw = cfg['origin_step.yaw_deg'];
        if (typeof sx === 'number') stepX = sx;
        if (typeof sy === 'number') stepY = sy;
        if (typeof syaw === 'number') stepYaw = syaw;
      })
      .catch(() => {
        // Silent — fall back to constants defaults already in state.
      });
    unsubLastPose = subscribeLastPose((p) => (lastPose = p));
  });

  onDestroy(() => {
    unsubLastPose?.();
  });

  function parseField(
    text: string,
    bound: number,
  ): { value: number | null; error: string | null } {
    if (text === null || text === undefined) {
      return { value: null, error: 'empty' };
    }
    const trimmed = String(text).trim();
    if (trimmed === '') {
      return { value: null, error: 'empty' };
    }
    if (trimmed.includes(',')) {
      return { value: null, error: 'locale_comma' };
    }
    const v = Number(trimmed);
    if (!Number.isFinite(v)) {
      return { value: null, error: 'not_finite' };
    }
    if (Math.abs(v) > bound) {
      return { value: null, error: 'out_of_bound' };
    }
    return { value: v, error: null };
  }

  let xParsed = $derived(parseField(xText, ORIGIN_X_Y_ABS_MAX_M));
  let yParsed = $derived(parseField(yText, ORIGIN_X_Y_ABS_MAX_M));
  let thetaParsed = $derived(parseField(thetaText, ORIGIN_THETA_DEG_ABS_MAX));

  // Theta is OPTIONAL — empty input is allowed (preserves YAML byte-for-
  // byte). Apply is gated on x AND y being valid; theta blocks Apply
  // only when typed AND invalid.
  let bothValid = $derived(xParsed.value !== null && yParsed.value !== null);
  let thetaBlocking = $derived(thetaText.trim() !== '' && thetaParsed.value === null);

  let applyDisabled = $derived(busy || role !== 'admin' || !bothValid || thetaBlocking);

  function clearBanner(): void {
    inlineError = null;
  }

  function fmtDisplay(v: number): string {
    return v.toFixed(ORIGIN_DECIMAL_DISPLAY_MM);
  }

  function fmtTheta(v: number): string {
    // 1 decimal place matches the operator's typical "fine-tune by tenths
    // of a degree" workflow without losing the operator's typed precision
    // when it overshoots — the parsed value is full f64 round-tripped.
    return v.toFixed(1);
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

  function nudgeX(delta: number): void {
    const cur = xParsed.value ?? 0;
    xText = fmtDisplay(cur + delta);
    clearBanner();
  }
  function nudgeY(delta: number): void {
    const cur = yParsed.value ?? 0;
    yText = fmtDisplay(cur + delta);
    clearBanner();
  }
  function nudgeTheta(delta: number): void {
    const cur = thetaParsed.value ?? 0;
    thetaText = fmtTheta(cur + delta);
    clearBanner();
  }

  function onApplyClick(): void {
    if (applyDisabled) return;
    if (xParsed.value === null || yParsed.value === null) {
      inlineError = 'inputs_invalid';
      return;
    }
    let resolvedX = xParsed.value;
    let resolvedY = yParsed.value;
    // Maj-1 fix — resolve delta on the SPA side so the backend stays dumb.
    // Operator's delta-mode mental model: typed (dx, dy) is the offset
    // from the current LiDAR pose to the point that should become the
    // new (0, 0). Backend always receives absolute world coords.
    if (mode === 'delta') {
      if (lastPose === null || !lastPose.valid) {
        inlineError = 'no_pose_for_delta';
        return;
      }
      const abs = resolveDeltaFromPose(
        { x_m: lastPose.x_m, y_m: lastPose.y_m },
        xParsed.value,
        yParsed.value,
      );
      resolvedX = abs.x_m;
      resolvedY = abs.y_m;
    }
    const body: OriginPatchBody = {
      x_m: resolvedX,
      y_m: resolvedY,
      mode: 'absolute',
    };
    if (thetaText.trim() !== '' && thetaParsed.value !== null) {
      body.theta_deg = thetaParsed.value;
    }
    onapply(body);
  }

  function onDiscardClick(): void {
    if (busy) return;
    xText = '';
    yText = '';
    thetaText = '';
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
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeX(-stepX)}
        disabled={busy || role !== 'admin'}
        title={`-${stepX} m`}
        data-testid="origin-x-minus"
      >−</button>
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeX(+stepX)}
        disabled={busy || role !== 'admin'}
        title={`+${stepX} m`}
        data-testid="origin-x-plus"
      >+</button>
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
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeY(-stepY)}
        disabled={busy || role !== 'admin'}
        title={`-${stepY} m`}
        data-testid="origin-y-minus"
      >−</button>
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeY(+stepY)}
        disabled={busy || role !== 'admin'}
        title={`+${stepY} m`}
        data-testid="origin-y-plus"
      >+</button>
    </label>
    <label class="num-label">
      theta:
      <input
        type="text"
        inputmode="decimal"
        bind:value={thetaText}
        oninput={clearBanner}
        disabled={busy || role !== 'admin'}
        data-testid="origin-theta-input"
        placeholder="optional"
        class={thetaParsed.error && thetaText !== '' ? 'input-invalid' : ''}
      />
      °
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeTheta(-stepYaw)}
        disabled={busy || role !== 'admin'}
        title={`-${stepYaw}°`}
        data-testid="origin-theta-minus"
      >−</button>
      <button
        type="button"
        class="step-btn"
        onclick={() => nudgeTheta(+stepYaw)}
        disabled={busy || role !== 'admin'}
        title={`+${stepYaw}°`}
        data-testid="origin-theta-plus"
      >+</button>
    </label>
  </div>

  {#if currentOrigin !== null}
    <p class="muted current-origin" data-testid="origin-current">
      현재 origin: ({fmtDisplay(currentOrigin[0])}, {fmtDisplay(currentOrigin[1])},
      {(currentOrigin[2] * (180 / Math.PI)).toFixed(1)}°)
    </p>
  {/if}

  {#if mode === 'absolute'}
    <p class="muted hint" data-testid="origin-absolute-hint">
      Absolute: 입력한 좌표가 새 origin(0, 0)이 되도록 YAML이 다시 쓰여집니다.
    </p>
  {:else}
    <p class="muted hint" data-testid="origin-delta-hint">
      Delta: 현재 pose에서 입력한 만큼 떨어진 점이 새 origin(0, 0)이 됩니다.
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
            : inlineError === 'no_pose_for_delta'
              ? 'Delta 모드는 현재 LiDAR pose가 필요합니다. AMCL이 수렴할 때까지 기다리거나 Absolute 모드를 사용하세요.'
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
  .step-btn {
    width: 1.8em;
    height: 1.8em;
    padding: 0;
    line-height: 1;
    font-weight: 600;
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
