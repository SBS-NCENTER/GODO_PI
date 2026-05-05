<script lang="ts">
  /**
   * issue#30 — origin-pick controls (delta-on-top of picked-at-origin).
   *
   * Sole owner of the dual-input origin form state per
   * `godo-frontend/CODEBASE.md` invariant (aa). The Edit sub-tab's
   * parent route (`MapEdit.svelte`) orchestrates layout + the
   * `'paint' | 'origin-pick'` click-mode toggle on `MapMaskCanvas`,
   * but does NOT mirror any of the form fields in a store.
   *
   * Operator-locked semantic per `.claude/memory/project_pick_anchored
   * _yaml_normalization_locked.md`:
   *
   *   - The XY click on the canvas captures `picked_world_x_m` /
   *     `picked_world_y_m` — that point becomes the new world (0, 0)
   *     by definition. Click does NOT pre-fill the input boxes.
   *   - The input boxes hold an OPTIONAL DELTA on top of the picked
   *     origin. Empty / `0` placeholder = "no further nudge".
   *   - 2-click yaw pick still resolves to a yaw delta in degrees and
   *     pre-fills `thetaText`.
   *
   * Pre-issue#30 absolute / delta mode toggle is removed — the pick-
   * anchored delta-on-top semantic is unconditional. The
   * `resolveDeltaFromPose` helper is preserved as a deprecated symbol
   * (back-compat for `originMath.test.ts`) but no longer wired.
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
  import { twoClickToYawDeg } from '$lib/originMath';
  import type {
    ConfigGetResponse,
    LastPose,
    MapEditCoordBody,
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
    /**
     * issue#28 (HIL fix) — when false, hide the inline "Apply origin"
     * button. The parent route (`MapEdit.svelte`) owns Apply via the
     * outer toolbar + modal flow; the inline button caused operator
     * confusion (clicked it → hit legacy `/api/map/origin` path with
     * no modal). Default true keeps back-compat tests + non-modal
     * callers working.
     */
    inlineApplyEnabled?: boolean;
  }

  const {
    currentOrigin,
    role,
    busy,
    bannerMsg,
    bannerKind,
    onapply,
    resolutionMPerPx = null,
    inlineApplyEnabled = true,
  }: Props = $props();

  const THETA_EDIT_ENABLED = true;

  // Form state — owned exclusively by this component.
  // Per Q2 lock: input boxes hold the typed DELTA (optional). Empty /
  // 0 placeholder = "no further nudge".
  let xText = $state<string>('');
  let yText = $state<string>('');
  let thetaText = $state<string>('');
  let inlineError = $state<string | null>(null);

  // issue#30 — picked-point state (canvas-clicked world coord). Held
  // INTERNALLY here, NOT mirrored into xText/yText. The XY click
  // captures the pick; the typed DELTA on top is applied separately.
  let pickedWorld = $state<{ x_m: number; y_m: number } | null>(null);

  // 2-click yaw pick state.
  let yawP1 = $state<{ wx: number; wy: number } | null>(null);
  let inlineYawError = $state<string | null>(null);

  // Step deltas for the +/- buttons.
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
    allowEmpty: boolean = true,
  ): { value: number | null; error: string | null } {
    if (text === null || text === undefined) {
      return allowEmpty ? { value: 0, error: null } : { value: null, error: 'empty' };
    }
    const trimmed = String(text).trim();
    if (trimmed === '') {
      // issue#30: empty input = 0 (no further nudge), not an error.
      return allowEmpty ? { value: 0, error: null } : { value: null, error: 'empty' };
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

  // Inputs are valid when the parser returns a finite number (incl. 0).
  let xValid = $derived(xParsed.value !== null);
  let yValid = $derived(yParsed.value !== null);
  let thetaBlocking = $derived(thetaText.trim() !== '' && thetaParsed.value === null);

  // issue#30 — Apply is allowed when picked OR any non-empty typed
  // delta exists (so operator can re-Apply with a new memo even if
  // they only typed θ). At minimum, a picked point is required if
  // none of x/y/θ is dirty (otherwise nothing distinguishes from the
  // pristine baseline). The parent applies its own gate — we just
  // gate the helper.
  let xyDirty = $derived(xText.trim() !== '' || yText.trim() !== '');
  let thetaDirty = $derived(thetaText.trim() !== '' && thetaParsed.value !== null);
  let pickedDirty = $derived(pickedWorld !== null);

  let canApply = $derived(
    !busy
    && role === 'admin'
    && (pickedDirty || xyDirty || thetaDirty)
    && xValid
    && yValid
    && !thetaBlocking,
  );
  let applyDisabled = $derived(!canApply);

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

  /**
   * issue#30 — Q2 lock: XY click on canvas captures the picked world
   * coord into INTERNAL state but does NOT pre-fill the input boxes.
   * The picked point is the new world (0, 0) baseline; the input
   * boxes hold an OPTIONAL DELTA on top.
   */
  export function setCandidate(c: { x_m: number; y_m: number }): void {
    pickedWorld = { x_m: c.x_m, y_m: c.y_m };
    inlineError = null;
    // An XY click cancels any in-progress yaw gesture.
    yawP1 = null;
    inlineYawError = null;
  }

  /**
   * issue#28 — yaw-click feeder. Called by the parent in `'yaw-pick'`
   * sub-mode. First call records P1; second call resolves to a yaw
   * angle via `twoClickToYawDeg` and pre-fills `thetaText`. P1→P2 must
   * exceed `YAW_PICK_MIN_PIXEL_DIST_PX` (converted via
   * `resolutionMPerPx`); coincident clicks raise an inline error and
   * leave P1 in place so the operator can re-click P2 without resetting.
   */
  export function setYawClick(c: { x_m: number; y_m: number }): void {
    if (!THETA_EDIT_ENABLED) return;
    if (yawP1 === null) {
      yawP1 = { wx: c.x_m, wy: c.y_m };
      inlineYawError = null;
      return;
    }
    const res = resolutionMPerPx;
    if (res === null || !(res > 0)) {
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

  export function isYawP1Pending(): boolean {
    return yawP1 !== null;
  }

  /**
   * issue#30 — picked-point observer. Used by the parent route to
   * render the orange pick-preview on the canvas underlay AND verify
   * tests, since a test cannot read internal $state directly.
   */
  export function getPickedWorld(): { x_m: number; y_m: number } | null {
    return pickedWorld;
  }

  /**
   * issue#30 — Apply gateway. Returns the JSON body for
   * `POST /api/map/edit/coord` based on the dirty flags. Returns null
   * when nothing is dirty.
   *
   * Wire shape per issue#30:
   *   - `x_m`, `y_m`, `theta_deg`: operator's typed DELTA (0 if empty).
   *   - `picked_world_x_m`, `picked_world_y_m`: the picked world coord
   *     captured from the canvas click. Falls back to (0, 0) if the
   *     operator typed only a delta without picking — in that case
   *     the backend treats the typed delta as a nudge from the
   *     active map's current origin (PICK#1 = pristine origin).
   */
  export function getDirtyBody(): Omit<MapEditCoordBody, 'memo'> | null {
    if (!canApply) return null;
    if (!pickedDirty && !xyDirty && !thetaDirty) return null;

    // Empty input = 0 (no further nudge); already enforced by parseField.
    const tx = xParsed.value ?? 0;
    const ty = yParsed.value ?? 0;

    const body: Omit<MapEditCoordBody, 'memo'> = { x_m: tx, y_m: ty };
    if (thetaDirty && thetaParsed.value !== null) {
      body.theta_deg = thetaParsed.value;
    }
    if (pickedWorld !== null) {
      body.picked_world_x_m = pickedWorld.x_m;
      body.picked_world_y_m = pickedWorld.y_m;
    }
    // Stale-pose-from-LastPose path retired — issue#30 picked-anchored
    // semantic supersedes the SUBTRACT delta-from-pose form.
    void lastPose;
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
    pickedWorld = null;
  }

  // Legacy back-compat path — preserved for /api/map/origin smoke tests.
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
    // Legacy back-compat path — emit OriginPatchBody with `mode='absolute'`.
    if (xParsed.value === null || yParsed.value === null) {
      inlineError = 'inputs_invalid';
      return;
    }
    const body: OriginPatchBody = {
      x_m: xParsed.value,
      y_m: yParsed.value,
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
</script>

<section class="origin-picker" data-testid="origin-picker">
  <h3 class="picker-title">Origin pick (issue#30 — pick + delta)</h3>

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
        placeholder="0"
        class={xParsed.error ? 'input-invalid' : ''}
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
      <span class="hint-inline" data-testid="origin-x-hint">(이동 없음)</span>
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
        placeholder="0"
        class={yParsed.error ? 'input-invalid' : ''}
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
      <span class="hint-inline" data-testid="origin-y-hint">(이동 없음)</span>
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
            yawP1 = null;
          }}
          disabled={busy || role !== 'admin'}
          data-testid="origin-theta-input"
          placeholder="0"
          class={thetaParsed.error ? 'input-invalid' : ''}
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
        <span class="hint-inline" data-testid="origin-theta-hint">(회전 없음)</span>
      </label>
    {/if}
  </div>

  {#if currentOrigin !== null}
    <p class="muted current-origin" data-testid="origin-current">
      현재 origin: ({fmtDisplay(currentOrigin[0])}, {fmtDisplay(currentOrigin[1])},
      {(currentOrigin[2] * (180 / Math.PI)).toFixed(1)}°)
    </p>
  {/if}

  {#if pickedWorld !== null}
    <p class="muted picked-info" data-testid="origin-picked-info">
      picked: ({fmtDisplay(pickedWorld.x_m)}, {fmtDisplay(pickedWorld.y_m)}) m
      — 이 점이 새 world (0, 0)이 됩니다.
    </p>
  {/if}

  {#if THETA_EDIT_ENABLED && yawP1 !== null}
    <p class="muted hint" data-testid="origin-yaw-pending">
      P1 표시 완료 — +x 축 방향의 두 번째 점을 클릭하세요.
    </p>
  {/if}

  <p class="muted hint" data-testid="origin-delta-hint">
    캔버스에서 클릭한 점이 새 origin (0, 0)이 됩니다. 입력값은 그 위에
    추가로 적용되는 이동/회전 입니다. 0 또는 빈 칸 = 추가 변경 없음.
  </p>

  {#if inlineApplyEnabled}
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
  {/if}

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
  .picked-info {
    font-family: var(--font-mono, ui-monospace, monospace);
    font-size: 0.9em;
    margin: 4px 0;
  }
  .muted {
    color: var(--color-text-muted, #666);
  }
  .hint-inline {
    font-size: 0.8em;
    color: var(--color-text-muted, #666);
    margin-left: 4px;
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
