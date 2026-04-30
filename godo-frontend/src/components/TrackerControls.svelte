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
   * Dashboard.svelte still keeps its inline copy — incremental rollout;
   * a follow-up PR can swap Dashboard to `<TrackerControls/>` once we
   * see this component holds up under HIL.
   */
  import { onDestroy, onMount } from 'svelte';
  import ModeChip from '$components/ModeChip.svelte';
  import { ApiError, apiGet, apiPost } from '$lib/api';
  import { DASHBOARD_REFRESH_MS } from '$lib/constants';
  import { MODE_LIVE, type Health, type LiveResponse, type Mode } from '$lib/protocol';
  import { auth } from '$stores/auth';
  import { setModeOptimistic, subscribeMode } from '$stores/mode';

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });
  let isAdmin = $derived(session?.role === 'admin');

  let mode = $state<Mode | null>(null);
  let health = $state<Health | null>(null);
  let actionError = $state<string | null>(null);
  let busy = $state(false);

  let unsubMode: (() => void) | null = null;
  let healthTimer: ReturnType<typeof setInterval> | null = null;

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
      await apiPost('/api/map/backup');
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
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
</div>
