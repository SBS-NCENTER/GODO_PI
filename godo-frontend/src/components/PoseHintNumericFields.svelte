<script lang="ts">
  /**
   * issue#3 — pose hint numeric panel (Map Overview).
   *
   * Three text inputs (x_m, y_m, yaw_deg) two-way bound with the GUI
   * marker via the `hint` prop + `onhintchange` callback. Mirrors the
   * `<OriginPicker/>` numeric-input idiom from B-MAPEDIT-2:
   *   - `type="text" inputmode="decimal"` so locale-comma can be
   *     rejected explicitly (Windows browsers may otherwise paste
   *     European notation).
   *   - blur-on-Enter; field persists on blur.
   *
   * Range bounds match webctl Pydantic + C++ uds_server.cpp:
   *   x_m, y_m ∈ [-100, 100] m
   *   yaw_deg ∈ [0, 360)
   *
   * Out-of-range / unparseable inputs render an inline error and the
   * hint is NOT updated (operator-locked: never silently coerce).
   */
  import {
    POSE_HINT_DECIMAL_DISPLAY_MM,
    POSE_HINT_X_Y_ABS_MAX_M,
    POSE_HINT_YAW_DEG_LT,
  } from '$lib/constants';
  import type { HintPose } from './PoseHintLayer.svelte';

  interface Props {
    hint: HintPose | null;
    onhintchange: (next: HintPose | null) => void;
  }

  let { hint, onhintchange }: Props = $props();

  // Local edit buffers — synced from `hint` on prop changes; written
  // back to the parent only on a successful parse + range check.
  let xText = $state('');
  let yText = $state('');
  let yawText = $state('');
  let xError = $state<string | null>(null);
  let yError = $state<string | null>(null);
  let yawError = $state<string | null>(null);

  $effect(() => {
    if (hint) {
      xText = hint.x_m.toFixed(POSE_HINT_DECIMAL_DISPLAY_MM);
      yText = hint.y_m.toFixed(POSE_HINT_DECIMAL_DISPLAY_MM);
      yawText = hint.yaw_deg.toFixed(POSE_HINT_DECIMAL_DISPLAY_MM);
      xError = null;
      yError = null;
      yawError = null;
    }
  });

  function parseDecimal(text: string): { ok: true; value: number } | { ok: false; err: string } {
    const trimmed = text.trim();
    if (trimmed === '') return { ok: false, err: 'empty' };
    if (trimmed.includes(',')) return { ok: false, err: 'use a period (not a comma)' };
    const v = Number(trimmed);
    if (!Number.isFinite(v)) return { ok: false, err: 'not a number' };
    return { ok: true, value: v };
  }

  function commitField(field: 'x' | 'y' | 'yaw'): void {
    const text = field === 'x' ? xText : field === 'y' ? yText : yawText;
    const r = parseDecimal(text);
    if (!r.ok) {
      if (field === 'x') xError = r.err;
      else if (field === 'y') yError = r.err;
      else yawError = r.err;
      return;
    }
    let v = r.value;
    if (field === 'yaw') {
      if (v < 0 || v >= POSE_HINT_YAW_DEG_LT) {
        yawError = `yaw must be in [0, ${POSE_HINT_YAW_DEG_LT})`;
        return;
      }
      yawError = null;
    } else {
      if (v < -POSE_HINT_X_Y_ABS_MAX_M || v > POSE_HINT_X_Y_ABS_MAX_M) {
        const err = `must be in [-${POSE_HINT_X_Y_ABS_MAX_M}, ${POSE_HINT_X_Y_ABS_MAX_M}] m`;
        if (field === 'x') xError = err;
        else yError = err;
        return;
      }
      if (field === 'x') xError = null;
      else yError = null;
    }

    const base: HintPose = hint ?? { x_m: 0, y_m: 0, yaw_deg: 0 };
    const next: HintPose = {
      x_m: field === 'x' ? v : base.x_m,
      y_m: field === 'y' ? v : base.y_m,
      yaw_deg: field === 'yaw' ? v : base.yaw_deg,
    };
    onhintchange(next);
  }

  function onKeyDown(ev: KeyboardEvent, field: 'x' | 'y' | 'yaw'): void {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      (ev.target as HTMLInputElement).blur();
      commitField(field);
    }
  }

  function onClear(): void {
    xText = '';
    yText = '';
    yawText = '';
    xError = null;
    yError = null;
    yawError = null;
    onhintchange(null);
  }
</script>

<div class="pose-hint-numeric" data-testid="pose-hint-numeric">
  <div class="hstack">
    <label class="field">
      <span>x (m)</span>
      <input
        type="text"
        inputmode="decimal"
        bind:value={xText}
        onblur={() => commitField('x')}
        onkeydown={(e) => onKeyDown(e, 'x')}
        data-testid="pose-hint-x"
      />
      {#if xError}
        <span class="err" data-testid="pose-hint-x-err">{xError}</span>
      {/if}
    </label>
    <label class="field">
      <span>y (m)</span>
      <input
        type="text"
        inputmode="decimal"
        bind:value={yText}
        onblur={() => commitField('y')}
        onkeydown={(e) => onKeyDown(e, 'y')}
        data-testid="pose-hint-y"
      />
      {#if yError}
        <span class="err" data-testid="pose-hint-y-err">{yError}</span>
      {/if}
    </label>
    <label class="field">
      <span>yaw (deg)</span>
      <input
        type="text"
        inputmode="decimal"
        bind:value={yawText}
        onblur={() => commitField('yaw')}
        onkeydown={(e) => onKeyDown(e, 'yaw')}
        data-testid="pose-hint-yaw"
      />
      {#if yawError}
        <span class="err" data-testid="pose-hint-yaw-err">{yawError}</span>
      {/if}
    </label>
    <button
      type="button"
      class="clear-btn"
      disabled={hint === null}
      onclick={onClear}
      data-testid="pose-hint-clear">힌트 지우기</button
    >
  </div>
</div>

<style>
  .pose-hint-numeric {
    margin: 8px 0;
    padding: 8px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg-elev);
  }
  .hstack {
    display: flex;
    gap: 12px;
    align-items: flex-end;
    flex-wrap: wrap;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
  }
  .field input {
    width: 100px;
    padding: 4px 6px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: monospace;
  }
  .err {
    color: var(--color-status-err);
    font-size: 12px;
  }
  .clear-btn {
    padding: 4px 12px;
  }
</style>
