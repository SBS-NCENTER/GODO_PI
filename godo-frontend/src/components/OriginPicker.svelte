<script lang="ts">
  /**
   * Track B-MAPEDIT-2 + issue#28 — origin-pick controls.
   *
   * Sole owner of the dual-input origin form state per
   * `godo-frontend/CODEBASE.md` invariant (aa). The Edit sub-tab's
   * parent route (`MapEdit.svelte`) orchestrates layout + the
   * `'paint' | 'origin-pick'` click-mode toggle on `MapMaskCanvas`,
   * but does NOT mirror any of the form fields in a store.
   *
   * Two input modes for x_m / y_m:
   *   - Mode A (GUI pick): parent route's pointer-coord callback calls
   *     `setCandidate({x_m, y_m})` to pre-fill the absolute fields.
   *     This component flips its own mode toggle to `'absolute'`
   *     (a click is unambiguously an absolute world coord) before
   *     populating the inputs.
   *   - Mode B (numeric entry): operator types `x_m` / `y_m` / `theta_deg`
   *     directly and toggles `mode` between `absolute` and `delta`.
   *
   * issue#28 additions:
   *   - `THETA_EDIT_ENABLED` flipped to true (B-MAPEDIT-3 ships full
   *     PGM rotation on the backend, so theta is no longer a metadata-
   *     only no-op).
   *   - Dual-input parity for theta: numeric (with +/- step buttons)
   *     OR 2-click yaw pick (P1 → P2 vector defines the new +x axis).
   *     `setYawClick(world_x, world_y)` is the imperative API the
   *     parent calls when the canvas is in `'yaw-pick'` sub-mode.
   *   - Independent dirty flags per axis (`xyDirty`, `thetaDirty`); the
   *     parent's Apply button commits whichever is dirty via
   *     `getDirtyBody()`.
   *   - Inline Apply button + redirect-after-Apply pattern REMOVED;
   *     `<ApplyMemoModal>` (mounted by parent) owns the flow.
   *   - SUBTRACT semantic for theta: parent computes
   *     `new_yaml_yaw = wrap(prev_yaml_yaw - typed_yaw)` and shows it
   *     as a preview; backend re-computes the same delta server-side.
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
    YAW_PICK_MIN_PIXEL_DIST_PX,
  } from '$lib/constants';
  import {
    resolveDeltaFromPose,
    resolveYawDeltaFromPose,
    twoClickToYawDeg,
  } from '$lib/originMath';
  import type {
    ConfigGetResponse,
    LastPose,
    MapEditCoordBody,
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
    /**
     * Legacy callback (kept for the `/api/map/origin` back-compat path
     * + tests). Parent route is FREE to leave this as a no-op when the
     * issue#28 modal flow owns Apply.
     */
    onapply: (body: OriginPatchBody) => void;
    /**
     * issue#28 — per-axis pixel resolution required to evaluate the
     * 2-click yaw guard (`YAW_PICK_MIN_PIXEL_DIST_PX`). Optional so the
     * Track B-MAPEDIT-2 single-axis flow keeps working.
     */
    resolutionMPerPx?: number | null;
  }

  const {
    currentOrigin,
    role,
    busy,
    bannerMsg,
    bannerKind,
    onapply,
    resolutionMPerPx = null,
  }: Props = $props();

  // issue#28 — feature gate flipped on. Theta editing is now backed by
  // the `/api/map/edit/coord` pipeline (Lanczos-3 PGM rotation +
  // SUBTRACT YAML rewrite), so the visual ↔ coordinate inconsistency
  // that justified hiding the UI in issue#27 is gone.
  const THETA_EDIT_ENABLED = true;

  // Form state — owned exclusively by this component.
  let mode = $state<OriginMode>('absolute');
  let xText = $state<string>('');
  let yText = $state<string>('');
  let thetaText = $state<string>('');
  let inlineError = $state<string | null>(null);

  // issue#28 — 2-click yaw pick state. `yawP1` holds the first click in
  // world coords; the second click closes the gesture by calling
  // `twoClickToYawDeg`. Cleared on Discard, on numeric edit of theta,
  // and on `setCandidate` (an XY click overrides any pending yaw click).
  let yawP1 = $state<{ wx: number; wy: number } | null>(null);
  let inlineYawError = $state<string | null>(null);

  // issue#27 — step deltas for the +/- buttons.
  let stepX = $state<number>(ORIGIN_STEP_X_M_DEFAULT);
  let stepY = $state<number>(ORIGIN_STEP_Y_M_DEFAULT);
  let stepYaw = $state<number>(ORIGIN_STEP_YAW_DEG_DEFAULT);

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

  let xyBothValid = $derived(xParsed.value !== null && yParsed.value !== null);
  let thetaBlocking = $derived(thetaText.trim() !== '' && thetaParsed.value === null);

  // Independent dirty flags. xy is dirty when BOTH inputs parse and at
  // least one is non-empty. theta is dirty when the input parses to a
  // finite number (empty = clean).
  let xyDirty = $derived(xyBothValid && (xText.trim() !== '' || yText.trim() !== ''));
  let thetaDirty = $derived(thetaText.trim() !== '' && thetaParsed.value !== null);

  let applyDisabled = $derived(busy || role !== 'admin' || (!xyDirty && !thetaDirty) || thetaBlocking);

  function clearBanner(): void {
    inlineError = null;
  }

  function clearYawError(): void {
    inlineYawError = null;
  }

  function fmtDisplay(v: number): string {
    return v.toFixed(ORIGIN_DECIMAL_DISPLAY_MM);
  }

  function fmtTheta(v: number): string {
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
    // An XY click cancels any in-progress yaw gesture.
    yawP1 = null;
    inlineYawError = null;
  }

  // issue#28 — yaw-click feeder. Called by the parent in `'yaw-pick'`
  // sub-mode. First call records P1; second call resolves to a yaw
  // angle via `twoClickToYawDeg` and pre-fills `thetaText`. P1→P2 must
  // exceed `YAW_PICK_MIN_PIXEL_DIST_PX` (converted via
  // `resolutionMPerPx`); coincident clicks raise an inline error and
  // leave P1 in place so the operator can re-click P2 without resetting.
  export function setYawClick(c: { x_m: number; y_m: number }): void {
    if (!THETA_EDIT_ENABLED) return;
    if (yawP1 === null) {
      yawP1 = { wx: c.x_m, wy: c.y_m };
      inlineYawError = null;
      return;
    }
    const res = resolutionMPerPx;
    if (res === null || !(res > 0)) {
      // Without a resolution we cannot evaluate the pixel-distance
      // guard; reject the gesture explicitly so the operator gets a
      // fixable error rather than a silently-skipped click.
      inlineYawError = 'no_resolution';
      return;
    }
    const yaw = twoClickToYawDeg(
      yawP1.wx,
      yawP1.wy,
      c.x_m,
      c.y_m,
      YAW_PICK_MIN_PIXEL_DIST_PX,
      res,
    );
    if (yaw === null) {
      inlineYawError = 'yaw_pick_too_close';
      return;
    }
    thetaText = fmtTheta(yaw);
    yawP1 = null;
    inlineYawError = null;
  }

  /**
   * issue#28 — yaw-pick state observer. Used by tests + parent for the
   * "P1 placed, awaiting P2" UI affordance.
   */
  export function isYawP1Pending(): boolean {
    return yawP1 !== null;
  }

  /**
   * issue#28 — Apply gateway. Returns the JSON body for
   * `POST /api/map/edit/coord` based on the dirty flags. Returns null
   * when nothing is dirty (Apply must remain disabled), when only
   * theta is supplied (the backend pipeline requires x/y to anchor
   * the SUBTRACT), or when delta-mode lacks a pose. The parent's
   * Apply button is `disabled = !canApply()` mirroring this.
   *
   * `memo` is supplied by `<ApplyMemoModal>` and appended at the call
   * site, so this method intentionally returns the body MINUS memo.
   */
  export function getDirtyBody(): Omit<MapEditCoordBody, 'memo'> | null {
    if (!xyDirty && !thetaDirty) return null;
    if (thetaBlocking) return null;

    // x/y must always be present for the backend pipeline. If only
    // theta is dirty, fill x/y from the current YAML origin so the
    // SUBTRACT becomes a no-op on those axes.
    let resolvedX: number;
    let resolvedY: number;
    if (xyDirty && xParsed.value !== null && yParsed.value !== null) {
      resolvedX = xParsed.value;
      resolvedY = yParsed.value;
      if (mode === 'delta') {
        if (lastPose === null || !lastPose.valid) {
          inlineError = 'no_pose_for_delta';
          return null;
        }
        const abs = resolveDeltaFromPose(
          { x_m: lastPose.x_m, y_m: lastPose.y_m },
          xParsed.value,
          yParsed.value,
        );
        resolvedX = abs.x_m;
        resolvedY = abs.y_m;
      }
    } else if (currentOrigin !== null) {
      resolvedX = currentOrigin[0];
      resolvedY = currentOrigin[1];
    } else {
      inlineError = 'no_xy_baseline';
      return null;
    }

    const body: Omit<MapEditCoordBody, 'memo'> = { x_m: resolvedX, y_m: resolvedY };
    if (thetaDirty && thetaParsed.value !== null) {
      body.theta_deg = thetaParsed.value;
    }
    return body;
  }

  /**
   * issue#28 — clear all dirty state. Parent calls on Discard.
   */
  export function clearAll(): void {
    xText = '';
    yText = '';
    thetaText = '';
    inlineError = null;
    inlineYawError = null;
    yawP1 = null;
  }

  // Legacy back-compat path: the inline Apply button still exists for
  // the existing /api/map/origin tests + non-modal callers. The
  // issue#28 parent route never clicks it (the parent's per-mode Apply
  // button drives the modal flow instead).
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
    clearYawError();
  }

  function onApplyClick(): void {
    if (applyDisabled) return;
    if (!xyDirty || xParsed.value === null || yParsed.value === null) {
      inlineError = 'inputs_invalid';
      return;
    }
    let resolvedX = xParsed.value;
    let resolvedY = yParsed.value;
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
    if (thetaDirty && thetaParsed.value !== null) {
      body.theta_deg = thetaParsed.value;
    }
    onapply(body);
  }

  function onDiscardClick(): void {
    if (busy) return;
    clearAll();
  }

  // SUBTRACT preview for theta — mirrors backend `wrap(prev - typed)`.
  let thetaPreview = $derived.by((): { prev: number; next: number } | null => {
    if (!thetaDirty || thetaParsed.value === null || currentOrigin === null) return null;
    const prevDeg = currentOrigin[2] * (180 / Math.PI);
    const nextDeg = resolveYawDeltaFromPose(prevDeg, thetaParsed.value);
    return { prev: prevDeg, next: nextDeg };
  });
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
    {#if THETA_EDIT_ENABLED}
      <label class="num-label">
        theta:
        <input
          type="text"
          inputmode="decimal"
          bind:value={thetaText}
          oninput={() => {
            clearBanner();
            clearYawError();
            // Numeric edit cancels any in-progress yaw gesture.
            yawP1 = null;
          }}
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
    {/if}
  </div>

  {#if currentOrigin !== null}
    <p class="muted current-origin" data-testid="origin-current">
      현재 origin: ({fmtDisplay(currentOrigin[0])}, {fmtDisplay(currentOrigin[1])},
      {(currentOrigin[2] * (180 / Math.PI)).toFixed(1)}°)
    </p>
  {/if}

  {#if THETA_EDIT_ENABLED && thetaPreview}
    <p class="muted preview" data-testid="origin-theta-preview">
      θ 미리보기: {thetaPreview.prev.toFixed(1)}° → {thetaPreview.next.toFixed(1)}°
    </p>
  {/if}

  {#if THETA_EDIT_ENABLED && yawP1 !== null}
    <p class="muted hint" data-testid="origin-yaw-pending">
      P1 표시 완료 — +x 축 방향의 두 번째 점을 클릭하세요.
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
              : inlineError === 'no_xy_baseline'
                ? 'Theta 단독 적용을 위해서는 현재 origin 메타데이터가 필요합니다.'
                : '입력 값이 잘못되었습니다.'}
    </p>
  {:else if inlineYawError}
    <p class="banner banner-error" data-testid="origin-yaw-banner">
      {inlineYawError === 'yaw_pick_too_close'
        ? '두 점이 너무 가깝습니다. 더 멀리 떨어진 곳을 클릭하세요.'
        : inlineYawError === 'no_resolution'
          ? '맵 해상도를 불러오지 못해 yaw 픽 가드를 평가할 수 없습니다.'
          : '두 점 입력에 문제가 있습니다.'}
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
  .preview {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 0.9em;
    margin: 4px 0;
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
