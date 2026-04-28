<script lang="ts">
  /**
   * PR-SYSTEM (Track B-SYSTEM) — `/system` page.
   *
   * Read-mostly diagnostics + power-control surface, reachable to anon
   * viewers (Track F). Four panels:
   *   (a) CPU temperature sparkline (window = DIAG_SPARKLINE_DEPTH ×
   *       SSE_TICK_MS — currently 12 s; see invariant (w)).
   *   (b) Resources — current memory + disk numbers from the same
   *       `DiagFrame.resources`.
   *   (c) Journal tail — reuses `<JournalTail/>` (allow-list mirror
   *       of `services.ALLOWED_SERVICES`).
   *   (d) Power — Reboot / Shutdown buttons. Admin-gated; mirrors the
   *       Local.svelte block verbatim (anon-hint string is identical).
   *
   * The page subscribes to the existing `diag` store via `subscribeDiag`
   * (invariant (p) — refcounted, so when both /diag and /system are
   *  mounted, only one SSE is open). It MUST capture and call the
   * unsubscribe closure in onDestroy to avoid leaking subscribers
   * (mirror of `Diagnostics.svelte:50-54`).
   */

  import { onDestroy, onMount } from 'svelte';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import DiagSparkline from '$components/DiagSparkline.svelte';
  import JournalTail from '$components/JournalTail.svelte';
  import { ApiError, apiPost } from '$lib/api';
  import {
    DIAG_FRESHNESS_MS,
    DIAG_SPARKLINE_DEPTH,
    RESOURCES_PANEL_COLOR,
    SSE_TICK_MS,
  } from '$lib/constants';
  import type { DiagFrame } from '$lib/protocol';
  import { auth } from '$stores/auth';
  import { diagSparklines, subscribeDiag, type DiagSparklineState } from '$stores/diag';

  let frame = $state<DiagFrame | null>(null);
  let sparklines = $state<DiagSparklineState>({
    jitter_p50_ns: [],
    jitter_p99_ns: [],
    amcl_rate_hz: [],
    cpu_temp_c: [],
    mem_used_pct: [],
  });
  let unsub: (() => void) | null = null;
  let unsubSparks: (() => void) | null = null;
  // Force a re-render every 1 s so the freshness gate ticks even when no
  // new frame arrives — same pattern as Diagnostics.svelte.
  let renderTick = $state(0);
  let tickTimer: ReturnType<typeof setInterval> | null = null;

  let session = $state($auth);
  $effect(() => {
    const u = auth.subscribe((v) => (session = v));
    return u;
  });
  let isAdmin = $derived(session?.role === 'admin');

  let confirmRebootOpen = $state(false);
  let confirmShutdownOpen = $state(false);
  let actionError = $state<string | null>(null);

  onMount(() => {
    unsub = subscribeDiag((f) => (frame = f));
    unsubSparks = diagSparklines.subscribe((s) => (sparklines = s));
    tickTimer = setInterval(() => (renderTick += 1), 1000);
  });

  onDestroy(() => {
    unsub?.();
    unsubSparks?.();
    if (tickTimer !== null) clearInterval(tickTimer);
  });

  function isStale(arrival_ms: number | undefined): boolean {
    void renderTick; // depend on tick so the gate re-evaluates each second
    if (!arrival_ms) return true;
    return Date.now() - arrival_ms > DIAG_FRESHNESS_MS;
  }

  function fmtTempC(v: number): string {
    return v.toFixed(1) + ' °C';
  }
  function fmtPct(v: number): string {
    return v.toFixed(1) + ' %';
  }
  function fmtBytes(v: number | null): string {
    if (v === null) return '—';
    const gb = v / (1 << 30);
    return gb.toFixed(2) + ' GiB';
  }

  // Sparkline window label is computed from the central constants (no
  // magic literal) so the test pinning the math survives a future
  // DIAG_SPARKLINE_DEPTH bump (invariant (w), T1 fold).
  const SPARKLINE_WINDOW_S = (DIAG_SPARKLINE_DEPTH * SSE_TICK_MS) / 1000;
  const cpuTempLabel = `CPU temp (${SPARKLINE_WINDOW_S} s)`;

  async function doReboot(): Promise<void> {
    confirmRebootOpen = false;
    actionError = null;
    try {
      await apiPost('/api/system/reboot');
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
    }
  }
  async function doShutdown(): Promise<void> {
    confirmShutdownOpen = false;
    actionError = null;
    try {
      await apiPost('/api/system/shutdown');
    } catch (e) {
      actionError = (e as ApiError).body?.err ?? (e as Error).message;
    }
  }

  let stale = $derived(isStale(frame?._arrival_ms));
  let resources = $derived(frame?.resources);
</script>

<div data-testid="system-page">
  <div class="breadcrumb">GODO &gt; System</div>
  <h2>System</h2>

  {#if stale}
    <div class="stale-banner" data-testid="system-stale-banner" role="status">
      마지막 진단 프레임이 {DIAG_FRESHNESS_MS / 1000}초 이상 갱신되지 않았습니다.
    </div>
  {/if}

  <div class="panels">
    <!-- (a) CPU temperature sparkline -->
    <section class="panel" data-testid="panel-cpu-temp" class:stale>
      <h3>CPU temperature</h3>
      <DiagSparkline
        values={sparklines.cpu_temp_c}
        color={RESOURCES_PANEL_COLOR}
        label={cpuTempLabel}
        formatValue={fmtTempC}
      />
    </section>

    <!-- (b) Resources (mem + disk) -->
    <section class="panel" data-testid="panel-resources" class:stale>
      <h3>Resources</h3>
      {#if resources}
        <div class="kv-grid">
          <span>cpu temp</span>
          <span data-testid="resources-cpu-temp">
            {resources.cpu_temp_c !== null ? fmtTempC(resources.cpu_temp_c) : '—'}
          </span>
          <span>mem</span>
          <span data-testid="resources-mem">
            {resources.mem_used_pct !== null ? fmtPct(resources.mem_used_pct) : '—'} of
            {fmtBytes(resources.mem_total_bytes)}
          </span>
          <span>disk</span>
          <span data-testid="resources-disk">
            {resources.disk_used_pct !== null ? fmtPct(resources.disk_used_pct) : '—'} of
            {fmtBytes(resources.disk_total_bytes)}
          </span>
        </div>
      {:else}
        <div class="panel-empty" data-testid="panel-resources-empty">Resources unavailable.</div>
      {/if}
    </section>

    <!-- (c) Journal tail -->
    <section class="panel panel-wide" data-testid="panel-journal">
      <h3>Journal tail</h3>
      <JournalTail />
    </section>

    <!-- (d) Power — admin-gated reboot / shutdown -->
    <section class="panel panel-wide" data-testid="panel-power">
      <h3>Power</h3>
      <div class="hstack">
        <button
          class="danger"
          disabled={!isAdmin}
          onclick={() => (confirmRebootOpen = true)}
          data-testid="reboot-btn">Reboot Pi</button
        >
        <button
          class="danger"
          disabled={!isAdmin}
          onclick={() => (confirmShutdownOpen = true)}
          data-testid="shutdown-btn">Shutdown Pi</button
        >
      </div>
      {#if !session}
        <div class="muted" style="margin-top: 8px;" data-testid="anon-hint">
          제어 동작은 로그인이 필요합니다.
        </div>
      {:else if !isAdmin}
        <div class="muted" style="margin-top: 8px;">admin 권한이 필요합니다.</div>
      {/if}
      {#if actionError}
        <div class="muted" style="color: var(--color-status-err); margin-top: 8px;">
          {actionError}
        </div>
      {/if}
    </section>
  </div>

  <ConfirmDialog
    open={confirmRebootOpen}
    title="재부팅 확인"
    message="RPi 5를 지금 재부팅할까요? 진행 중인 작업이 중단될 수 있습니다."
    confirmLabel="재부팅"
    danger={true}
    onConfirm={doReboot}
    onCancel={() => (confirmRebootOpen = false)}
  />
  <ConfirmDialog
    open={confirmShutdownOpen}
    title="종료 확인"
    message="RPi 5를 지금 종료할까요? 다시 켜려면 직접 전원을 인가해야 합니다."
    confirmLabel="종료"
    danger={true}
    onConfirm={doShutdown}
    onCancel={() => (confirmShutdownOpen = false)}
  />
</div>

<style>
  h2,
  h3 {
    margin-top: 0;
  }
  .panels {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
    gap: 12px;
    margin-top: 12px;
  }
  .panel {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 12px;
  }
  .panel-wide {
    grid-column: 1 / -1;
  }
  .panel.stale {
    opacity: 0.6;
  }
  .panel h3 {
    margin: 0 0 8px;
    font-size: 16px;
  }
  .kv-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
  .panel-empty {
    color: var(--color-text-muted);
    font-style: italic;
    padding: 8px 0;
  }
  .stale-banner {
    margin: 0 0 12px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
    border: 1px solid var(--color-warning-border);
    font-size: 14px;
  }
</style>
