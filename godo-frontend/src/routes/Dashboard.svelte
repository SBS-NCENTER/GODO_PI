<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import ModeChip from '$components/ModeChip.svelte';
  import { ApiError, apiGet, apiPost } from '$lib/api';
  import {
    ACTIVITY_TAIL_DEFAULT_N,
    BACKUP_FLASH_DISMISS_MS,
    DASHBOARD_REFRESH_MS,
  } from '$lib/constants';
  import { formatDegrees, formatMeters, formatTimeOfDay } from '$lib/format';
  import {
    MODE_IDLE,
    MODE_LIVE,
    type ActivityEntry,
    type Health,
    type LastPose,
    type LiveResponse,
    type Mode,
  } from '$lib/protocol';
  import { auth } from '$stores/auth';
  import { subscribeLastPose } from '$stores/lastPose';
  import { setModeOptimistic, subscribeMode } from '$stores/mode';

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });
  let isAdmin = $derived(session?.role === 'admin');

  let mode = $state<Mode | null>(null);
  let pose = $state<LastPose | null>(null);
  let activity = $state<ActivityEntry[]>([]);
  let health = $state<Health | null>(null);
  let actionError = $state<string | null>(null);
  // Backup flash banner — auto-dismisses after BACKUP_FLASH_DISMISS_MS so
  // operators get a visible "백업 완료" / "백업 실패" signal without the
  // banner persisting into unrelated navigation. Operator UX 2026-05-02 KST.
  let backupFlash = $state<{ kind: 'ok' | 'error'; text: string } | null>(null);
  let backupFlashTimer: ReturnType<typeof setTimeout> | null = null;
  let busy = $state(false);

  let unsubMode: (() => void) | null = null;
  let unsubPose: (() => void) | null = null;
  let activityTimer: ReturnType<typeof setInterval> | null = null;

  function showBackupFlash(kind: 'ok' | 'error', text: string): void {
    if (backupFlashTimer !== null) clearTimeout(backupFlashTimer);
    backupFlash = { kind, text };
    backupFlashTimer = setTimeout(() => {
      backupFlash = null;
      backupFlashTimer = null;
    }, BACKUP_FLASH_DISMISS_MS);
  }

  async function refreshActivity(): Promise<void> {
    try {
      activity = await apiGet<ActivityEntry[]>(`/api/activity?n=${ACTIVITY_TAIL_DEFAULT_N}`);
    } catch {
      // Tolerate transient failure.
    }
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
      await refreshActivity();
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
      await refreshActivity();
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
      await refreshActivity();
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
    unsubPose = subscribeLastPose((p) => (pose = p));
    void refreshActivity();
    void refreshHealth();
    activityTimer = setInterval(() => {
      void refreshActivity();
      void refreshHealth();
    }, DASHBOARD_REFRESH_MS);
  });

  onDestroy(() => {
    unsubMode?.();
    unsubPose?.();
    if (activityTimer !== null) clearInterval(activityTimer);
    if (backupFlashTimer !== null) clearTimeout(backupFlashTimer);
  });
</script>

<div data-testid="dashboard">
  <div class="breadcrumb">GODO &gt; Dashboard</div>
  <h2>Dashboard</h2>

  <div class="card vstack">
    <div class="hstack">
      <strong>Mode:</strong>
      <ModeChip {mode} />
      {#if health}
        <span class="muted">tracker: {health.tracker}</span>
      {/if}
    </div>
    <div class="hstack">
      <button
        class="primary"
        disabled={!isAdmin || busy}
        onclick={doCalibrate}
        data-testid="calibrate-btn">Calibrate</button
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

  <div class="card" style="margin-top: 16px;">
    <h3>Last pose</h3>
    {#if pose && pose.valid}
      <div class="hstack">
        <span>x: {formatMeters(pose.x_m)}</span>
        <span>y: {formatMeters(pose.y_m)}</span>
        <span>yaw: {formatDegrees(pose.yaw_deg)}</span>
        <span class="muted">σ_xy: {formatMeters(pose.xy_std_m)}</span>
        {#if pose.converged}
          <span class="chip ok">converged</span>
        {/if}
      </div>
    {:else}
      <div class="muted">no valid pose yet</div>
    {/if}
  </div>

  <div class="card" style="margin-top: 16px;">
    <h3>Recent activity</h3>
    {#if activity.length === 0}
      <div class="muted">no activity yet</div>
    {:else}
      <ul class="activity-list">
        {#each activity as a (a.ts)}
          <li>
            <span class="muted">{formatTimeOfDay(a.ts)}</span>
            <strong>{a.type}</strong>
            <span class="muted">{a.detail}</span>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  <div class="muted" style="margin-top: 24px;">
    Mode legend: <span class="chip idle">{MODE_IDLE}</span>
    <span class="chip warn">OneShot</span>
    <span class="chip ok">{MODE_LIVE}</span>
  </div>
</div>

<style>
  h2,
  h3 {
    margin-top: 0;
  }
  .activity-list {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .activity-list li {
    display: flex;
    gap: var(--space-3);
    padding: var(--space-1) 0;
    border-bottom: 1px solid var(--color-border);
  }
  .activity-list li:last-child {
    border-bottom: none;
  }
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
