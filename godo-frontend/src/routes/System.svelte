<script lang="ts">
  /**
   * PR-SYSTEM (Track B-SYSTEM) — `/system` page.
   *
   * Read-mostly diagnostics + power-control surface, reachable to anon
   * viewers (Track F). Three sub-tabs (PR-B):
   *   - "Overview"  (default) — wraps the original PR-SYSTEM panels:
   *       CPU temperature sparkline / Resources / GODO services /
   *       Journal tail / Power.
   *   - "Processes" — live PID table (PR-B).
   *   - "Extended"  — per-core CPU + mem + disk bars (PR-B).
   *
   * Sub-tab key + filter state are component-local — they reset on
   * route change (e.g. operator clicks `/map` then comes back).
   * Persisting via URL hash is a follow-up if operators request it
   * (Risk R10 deferred per Final fold S3).
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
  import ProcessTable from '$components/ProcessTable.svelte';
  import ResourceBars from '$components/ResourceBars.svelte';
  import ServiceStatusCard from '$components/ServiceStatusCard.svelte';
  import { ApiError, apiPost } from '$lib/api';
  import {
    DIAG_FRESHNESS_MS,
    DIAG_SPARKLINE_DEPTH,
    RESOURCES_PANEL_COLOR,
    SSE_TICK_MS,
    SYSTEM_SERVICES_STALE_MS,
    SYSTEM_SUBTAB_EXTENDED,
    SYSTEM_SUBTAB_OVERVIEW,
    SYSTEM_SUBTAB_PROCESSES,
  } from '$lib/constants';
  import type { DiagFrame, ExtendedResources, ProcessesSnapshot } from '$lib/protocol';
  import { auth } from '$stores/auth';
  import { diagSparklines, subscribeDiag, type DiagSparklineState } from '$stores/diag';
  import { subscribeProcesses } from '$stores/processes';
  import { subscribeResourcesExtended } from '$stores/resourcesExtended';
  import { subscribeSystemServices, type SystemServicesState } from '$stores/systemServices';

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
  let unsubServices: (() => void) | null = null;
  let unsubProcesses: (() => void) | null = null;
  let unsubResExt: (() => void) | null = null;
  let svcState = $state<SystemServicesState>({ services: [], _arrival_ms: null, err: null });
  let processesSnapshot = $state<ProcessesSnapshot>({
    processes: [],
    duplicate_alert: false,
    published_mono_ns: 0,
  });
  let extendedSnapshot = $state<ExtendedResources>({
    cpu_per_core: [],
    cpu_aggregate_pct: 0,
    mem_total_mb: null,
    mem_used_mb: null,
    disk_pct: null,
    published_mono_ns: 0,
  });
  let activeSubtab = $state<string>(SYSTEM_SUBTAB_OVERVIEW);
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
    unsubServices = subscribeSystemServices((s) => (svcState = s));
    unsubProcesses = subscribeProcesses((s) => (processesSnapshot = s));
    unsubResExt = subscribeResourcesExtended((s) => (extendedSnapshot = s));
    tickTimer = setInterval(() => (renderTick += 1), 1000);
  });

  onDestroy(() => {
    unsub?.();
    unsubSparks?.();
    unsubServices?.();
    unsubProcesses?.();
    unsubResExt?.();
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

  // Track B-SYSTEM PR-2 — services panel staleness gate. Mirrors the
  // diag stale-banner pattern but with its own threshold
  // (`SYSTEM_SERVICES_STALE_MS`); also re-evaluates each second via
  // the existing `renderTick` so the gate flips without a new poll.
  function isServicesStale(arrival_ms: number | null): boolean {
    void renderTick;
    if (arrival_ms === null) return true;
    return Date.now() - arrival_ms > SYSTEM_SERVICES_STALE_MS;
  }
  let servicesStale = $derived(isServicesStale(svcState._arrival_ms));
  // `Date.now() / 1000` reflows once per renderTick so each card's
  // uptime label keeps moving even between polls.
  let nowUnix = $derived.by(() => {
    void renderTick;
    return Math.floor(Date.now() / 1000);
  });
</script>

<div data-testid="system-page">
  <div class="breadcrumb">GODO &gt; System</div>
  <h2>System</h2>

  <div class="subtabs" role="tablist" data-testid="system-subtabs">
    <button
      class="subtab"
      class:active={activeSubtab === SYSTEM_SUBTAB_OVERVIEW}
      role="tab"
      aria-selected={activeSubtab === SYSTEM_SUBTAB_OVERVIEW}
      onclick={() => (activeSubtab = SYSTEM_SUBTAB_OVERVIEW)}
      data-testid="subtab-overview">Overview</button
    >
    <button
      class="subtab"
      class:active={activeSubtab === SYSTEM_SUBTAB_PROCESSES}
      role="tab"
      aria-selected={activeSubtab === SYSTEM_SUBTAB_PROCESSES}
      onclick={() => (activeSubtab = SYSTEM_SUBTAB_PROCESSES)}
      data-testid="subtab-processes">Processes</button
    >
    <button
      class="subtab"
      class:active={activeSubtab === SYSTEM_SUBTAB_EXTENDED}
      role="tab"
      aria-selected={activeSubtab === SYSTEM_SUBTAB_EXTENDED}
      onclick={() => (activeSubtab = SYSTEM_SUBTAB_EXTENDED)}
      data-testid="subtab-extended">Extended resources</button
    >
  </div>

  {#if activeSubtab === SYSTEM_SUBTAB_OVERVIEW}
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

      <!-- Track B-SYSTEM PR-2 — GODO services panel -->
      <section class="panel panel-wide" data-testid="panel-services">
        <div class="hstack" style="justify-content: space-between;">
          <h3>GODO 서비스</h3>
          {#if servicesStale}
            <span class="muted services-stale" data-testid="services-stale-banner" role="status">
              데이터 갱신 지연
            </span>
          {/if}
        </div>
        {#if svcState.services.length === 0 && svcState._arrival_ms === null && svcState.err === null}
          <div class="muted" data-testid="services-loading">로드 중…</div>
        {:else if svcState.services.length === 0 && svcState.err}
          <div class="muted" style="color: var(--color-status-err);" data-testid="services-error">
            {svcState.err}
          </div>
        {:else}
          <div class="services-grid" data-testid="services-grid">
            {#each svcState.services as svc (svc.name)}
              <ServiceStatusCard
                service={svc}
                {isAdmin}
                {nowUnix}
                actionsDisabled={svc.name === 'godo-mapping@active'}
                actionsDisabledTooltip={svc.name === 'godo-mapping@active'
                  ? 'Map > Mapping 탭에서 제어'
                  : ''}
              />
            {/each}
          </div>
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
  {:else if activeSubtab === SYSTEM_SUBTAB_PROCESSES}
    <ProcessTable snapshot={processesSnapshot} />
  {:else if activeSubtab === SYSTEM_SUBTAB_EXTENDED}
    <ResourceBars snapshot={extendedSnapshot} />
  {/if}
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
  .services-grid {
    /* issue#14 Patch C2 (2026-05-02): 2x2 grid for the 4-service set
       (godo-irq-pin, godo-mapping@active, godo-tracker, godo-webctl).
       `auto-fit + minmax(360px, 1fr)` would have produced 4 columns
       on a wide viewport, which breaks the operator's mental model
       of "managed unit cards on one row, peripheral cards on another".
       The fixed 2-column grid keeps the layout consistent across
       viewport widths (drops to 1 column below 720 px). */
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
    margin-top: 8px;
  }
  @media (max-width: 720px) {
    .services-grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
  .services-stale {
    font-size: 13px;
    color: var(--color-warning-fg);
  }
  .subtabs {
    display: flex;
    gap: 0;
    margin: 12px 0;
    border-bottom: 1px solid var(--color-border);
  }
  .subtab {
    background: none;
    border: none;
    padding: 8px 16px;
    cursor: pointer;
    color: var(--color-text-muted);
    font-size: 14px;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .subtab:hover {
    color: var(--color-text);
  }
  .subtab.active {
    color: var(--color-text);
    border-bottom-color: var(--color-accent);
  }
</style>
