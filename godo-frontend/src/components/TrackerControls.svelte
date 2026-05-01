<script lang="ts">
  /**
   * Track B-MAPEDIT (β.5) — `<TrackerControls/>` component.
   *
   * Reusable Mode chip + Calibrate / Start-Stop Live / Backup map
   * buttons + role/error hints. Mirror of Dashboard's inline control
   * card, extracted so `/map` (Overview) and `/map-edit` (Edit) get the
   * same trigger UX without duplicating the action handlers.
   *
   * Action handlers (`doCalibrate`, `toggleLive`, `doBackup`) post to
   * the existing endpoints (`/api/calibrate`, `/api/live`,
   * `/api/map/backup`); error rendering follows the Dashboard idiom
   * (single `actionError` line under the buttons).
   *
   * Mode subscription drives the Live button's label ("Start Live" vs
   * "Stop Live"); pose-store interaction lives in the sibling
   * `<LastPoseCard/>` for separation of concerns.
   *
   * issue#3 — when `hint` is non-null, a "Calibrate from hint" button
   * is rendered alongside the existing "Calibrate" button. Both go to
   * the same /api/calibrate endpoint; the difference is only whether a
   * `CalibrateBody` is supplied. After a successful hint-calibrate
   * the parent `Map.svelte` clears the hint via `onClearHint` because
   * the cold writer has consumed it (consume-once invariant) and a
   * stale marker would mislead the operator about a future click.
   */
  import { onDestroy, onMount } from 'svelte';
  import ModeChip from '$components/ModeChip.svelte';
  import { ApiError, apiGet, apiPost, apiPostCalibrate } from '$lib/api';
  import { BACKUP_FLASH_DISMISS_MS, DASHBOARD_REFRESH_MS } from '$lib/constants';
  import {
    MODE_LIVE,
    type CalibrateBody,
    type Health,
    type LiveResponse,
    type Mode,
  } from '$lib/protocol';
  import type { HintPose } from './PoseHintLayer.svelte';
  import { auth } from '$stores/auth';
  import { setModeOptimistic, subscribeMode } from '$stores/mode';

  interface Props {
    hint?: HintPose | null;
    onClearHint?: () => void;
  }

  let { hint = null, onClearHint }: Props = $props();

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });
  let isAdmin = $derived(session?.role === 'admin');

  let mode = $state<Mode | null>(null);
  let health = $state<Health | null>(null);
  let actionError = $state<string | null>(null);
  // Backup flash banner — auto-dismisses after BACKUP_FLASH_DISMISS_MS so
  // operators get a visible "백업 완료" / "백업 실패" signal without the
  // banner persisting into unrelated navigation. Operator UX 2026-05-02 KST.
  let backupFlash = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);
  let backupFlashTimer: ReturnType<typeof setTimeout> | null = null;
  let busy = $state(false);

  let unsubMode: (() => void) | null = null;
  let healthTimer: ReturnType<typeof setInterval> | null = null;

  function showBackupFlash(kind: 'ok' | 'error', text: string): void {
    if (backupFlashTimer !== null) clearTimeout(backupFlashTimer);
    backupFlash = { kind, text };
    backupFlashTimer = setTimeout(() => {
      backupFlash = null;
      backupFlashTimer = null;
    }, BACKUP_FLASH_DISMISS_MS);
  }

  async function refreshHealth(): Promise<void> {
    try {
      health = await apiGet<Health>('/api/health');
    } catch {
      health = null;
    }
  }

  async function doCalibrate(): Promise<void> {
    if (!isAdmin || busy) return;
    busy = true;
    actionError = null;
    try {
      await apiPost('/api/calibrate');
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function doCalibrateFromHint(): Promise<void> {
    if (!isAdmin || busy || hint === null) return;
    busy = true;
    actionError = null;
    try {
      const body: CalibrateBody = {
        seed_x_m: hint.x_m,
        seed_y_m: hint.y_m,
        seed_yaw_deg: hint.yaw_deg,
      };
      await apiPostCalibrate(body);
      // Consume-once UX: after a successful calibrate-from-hint the
      // tracker has consumed the bundle; clear the SPA marker so a
      // stale arrow doesn't mislead the operator about a fresh click.
      onClearHint?.();
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function toggleLive(): Promise<void> {
    if (!isAdmin || busy) return;
    const enable = mode !== MODE_LIVE;
    busy = true;
    actionError = null;
    try {
      const resp = await apiPost<LiveResponse>('/api/live', { enable });
      setModeOptimistic(resp.mode);
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
    } finally {
      busy = false;
    }
  }

  async function doBackup(): Promise<void> {
    if (!isAdmin || busy) return;
    busy = true;
    actionError = null;
    try {
      const resp = await apiPost<{ ok: true; path: string }>('/api/map/backup');
      showBackupFlash('ok', `백업 완료: ${resp.path}`);
    } catch (e) {
      const msg = (e as ApiError).body?.err ?? (e as Error).message;
      actionError = msg;
      showBackupFlash('error', `백업 실패: ${msg}`);
    } finally {
      busy = false;
    }
  }

  onMount(() => {
    unsubMode = subscribeMode((m) => (mode = m));
    void refreshHealth();
    // Health is polled at a slow cadence — only the binary "tracker
    // up?" question matters for this card. Faster updates come from
    // the SSE-driven mode subscription.
    healthTimer = setInterval(() => void refreshHealth(), DASHBOARD_REFRESH_MS);
  });

  onDestroy(() => {
    unsubMode?.();
    if (healthTimer !== null) clearInterval(healthTimer);
    if (backupFlashTimer !== null) clearTimeout(backupFlashTimer);
  });
</script>

<div class="card vstack" data-testid="tracker-controls">
  <div class="hstack">
    <strong>Mode:</strong>
    <ModeChip {mode} />
    {#if health}
      <span class="muted" data-testid="tracker-health">tracker: {health.tracker}</span>
    {/if}
  </div>
  <div class="hstack">
    <button
      class="primary"
      disabled={!isAdmin || busy}
      onclick={doCalibrate}
      data-testid="calibrate-btn">Calibrate</button
    >
    <button
      class="primary"
      disabled={!isAdmin || busy || hint === null}
      onclick={doCalibrateFromHint}
      data-testid="calibrate-from-hint-btn"
      title="지도에 위치 힌트를 먼저 클릭/드래그한 뒤 누르세요"
      >Calibrate from hint</button
    >
    <button disabled={!isAdmin || busy} onclick={toggleLive} data-testid="live-btn">
      {mode === MODE_LIVE ? 'Stop Live' : 'Start Live'}
    </button>
    <button disabled={!isAdmin || busy} onclick={doBackup} data-testid="backup-btn"
      >Backup map</button
    >
  </div>
  {#if !session}
    <div class="muted" data-testid="anon-hint">제어 동작은 로그인이 필요합니다.</div>
  {:else if !isAdmin}
    <div class="muted">읽기 전용 사용자입니다 (admin 권한 필요).</div>
  {/if}
  {#if actionError}
    <div class="muted" style="color: var(--color-status-err);" data-testid="action-error">
      {actionError}
    </div>
  {/if}
  {#if backupFlash}
    <div
      class="backup-flash"
      class:ok={backupFlash.kind === 'ok'}
      class:err={backupFlash.kind === 'error'}
      data-testid="backup-flash"
      data-kind={backupFlash.kind}
    >
      {backupFlash.text}
    </div>
  {/if}
</div>

<style>
  .backup-flash {
    margin-top: var(--space-2);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm, 4px);
    font-size: 0.92em;
    word-break: break-all;
  }
  .backup-flash.ok {
    background: var(--color-status-ok-bg, rgba(46, 125, 50, 0.12));
    color: var(--color-status-ok, #2e7d32);
    border: 1px solid var(--color-status-ok, #2e7d32);
  }
  .backup-flash.err {
    background: var(--color-status-err-bg, rgba(198, 40, 40, 0.12));
    color: var(--color-status-err, #c62828);
    border: 1px solid var(--color-status-err, #c62828);
  }
</style>
