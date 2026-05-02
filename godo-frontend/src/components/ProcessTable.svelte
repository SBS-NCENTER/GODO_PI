<script lang="ts">
  /**
   * Track B-SYSTEM PR-B — Processes sub-tab table.
   *
   * Receives the `ProcessesSnapshot` from the page and renders:
   *   - text-search box (case-insensitive, name OR cmdline)
   *   - "GODO only" toggle
   *   - sortable table (default cpu_pct desc)
   *   - duplicate-alert banner (red) when any per-row duplicate=true
   *   - per-row left-border red marker for duplicate rows
   *
   * Filters are CLIENT-SIDE — the SSE wire never carries a filter
   * parameter (per Mode-A S1 fold pin).
   *
   * Polish TODO (deferred to Phase 4-5 follow-up per Final fold S5):
   * detect "duplicate detected within 2 s of operator clicking
   * Restart" and switch the banner sub-text to "Restart in progress —
   * duplicate is transient" instead of the generic alert. Operator
   * was clear that defense-in-depth visibility wins over
   * suppression for v1; see feedback_pipeline_short_circuit.md.
   */

  import type { MappingState, ProcessEntry, ProcessesSnapshot } from '$lib/protocol';
  import { MAPPING_STATE_RUNNING, MAPPING_STATE_STARTING, MAPPING_STATE_STOPPING } from '$lib/protocol';

  interface Props {
    snapshot: ProcessesSnapshot;
    // issue#16 HIL hot-fix — tells the table whether the mapping
    // pipeline is currently active. Docker-family rows render in
    // accent (blue) when running, success (green) otherwise. Pass
    // ``null`` to fall back to the idle palette (e.g. when the System
    // tab can't read the mapping state for some reason).
    mappingState?: MappingState | null;
  }

  const { snapshot, mappingState = null }: Props = $props();

  const dockerActive = $derived(
    mappingState === MAPPING_STATE_STARTING ||
    mappingState === MAPPING_STATE_RUNNING ||
    mappingState === MAPPING_STATE_STOPPING,
  );

  let search = $state('');
  let godoOnly = $state(false);
  let sortKey = $state<keyof ProcessEntry>('cpu_pct');
  let sortAsc = $state(false); // default cpu_pct desc

  function onSortClick(key: keyof ProcessEntry): void {
    if (sortKey === key) {
      sortAsc = !sortAsc;
    } else {
      sortKey = key;
      // Numeric columns default to desc; text columns to asc.
      sortAsc = !['cpu_pct', 'rss_mb', 'pid', 'etime_s'].includes(key as string);
    }
  }

  function rowMatches(p: ProcessEntry, q: string): boolean {
    if (!q) return true;
    const needle = q.toLowerCase();
    if (p.name.toLowerCase().includes(needle)) return true;
    return p.cmdline.join(' ').toLowerCase().includes(needle);
  }

  let visible = $derived.by(() => {
    let rows = snapshot.processes;
    if (godoOnly) rows = rows.filter((p) => p.category !== 'general');
    if (search) rows = rows.filter((p) => rowMatches(p, search));
    const k = sortKey;
    rows = [...rows].sort((a, b) => {
      const av = a[k];
      const bv = b[k];
      if (typeof av === 'number' && typeof bv === 'number') {
        return sortAsc ? av - bv : bv - av;
      }
      const sa = String(av ?? '');
      const sb = String(bv ?? '');
      return sortAsc ? sa.localeCompare(sb) : sb.localeCompare(sa);
    });
    return rows;
  });

  function fmtCpu(v: number): string {
    return v.toFixed(1) + ' %';
  }
  function fmtRss(v: number | null): string {
    if (v === null) return '—';
    if (v >= 1024) return (v / 1024).toFixed(2) + ' GiB';
    return v.toFixed(1) + ' MiB';
  }
  function fmtEtime(v: number): string {
    if (v < 60) return v + 's';
    const m = Math.floor(v / 60);
    const s = v % 60;
    if (m < 60) return `${m}m${s}s`;
    const h = Math.floor(m / 60);
    return `${h}h${m % 60}m`;
  }
  function fmtCmdline(parts: string[]): string {
    return parts.join(' ');
  }
</script>

<div class="proc-table" data-testid="process-table">
  <details class="info-popover">
    <summary data-testid="proc-info-toggle">i 도움말</summary>
    <ul class="info-list" data-testid="proc-info-content">
      <li data-testid="info-irq-pin">
        godo-irq-pin은 <code>Type=oneshot</code> 서비스입니다. 시작 후 즉시 종료되므로 살아있는 프로세스가
        없는 것이 정상입니다.
      </li>
      <li data-testid="info-managed">
        Managed services (3개) — <code>godo_tracker_rt</code>, <code>godo-webctl</code>,
        <code>godo-irq-pin</code> — 는 이름이 굵고 색상이 있는 글씨로 표시됩니다.
      </li>
      <li data-testid="info-duplicate">
        같은 GODO 프로세스가 두 개 이상 검출되면 빨간 배너가 표시됩니다 (single-instance
        defense-in-depth).
      </li>
    </ul>
  </details>

  <div class="filter-bar">
    <input
      type="search"
      placeholder="이름 또는 cmdline 검색"
      bind:value={search}
      data-testid="proc-search"
    />
    <label class="checkbox">
      <input type="checkbox" bind:checked={godoOnly} data-testid="proc-godo-only" />
      <span>GODO only</span>
    </label>
    <span class="muted" data-testid="proc-count">
      {visible.length} / {snapshot.processes.length} processes
    </span>
  </div>

  {#if snapshot.duplicate_alert}
    <div class="dup-banner" data-testid="proc-duplicate-banner" role="alert">
      ⚠ 중복 GODO 프로세스가 검출되었습니다. 이름 컬럼이 빨간 줄로 표시된 행을 확인하세요.
    </div>
  {/if}

  <table>
    <thead>
      <tr>
        <th class="sortable" onclick={() => onSortClick('name')}>name</th>
        <th class="sortable num" onclick={() => onSortClick('pid')}>pid</th>
        <th class="sortable" onclick={() => onSortClick('user')}>user</th>
        <th class="sortable" onclick={() => onSortClick('state')}>state</th>
        <th class="sortable num" onclick={() => onSortClick('cpu_pct')}>cpu%</th>
        <th class="sortable num" onclick={() => onSortClick('rss_mb')}>rss</th>
        <th class="sortable num" onclick={() => onSortClick('etime_s')}>uptime</th>
        <th>cmdline</th>
      </tr>
    </thead>
    <tbody>
      {#each visible as p (p.pid)}
        <tr class:dup={p.duplicate} data-testid={`proc-row-${p.pid}`}>
          <td
            class={`name-cell name-${p.category}`}
            class:docker-active={p.category === 'docker' && dockerActive}
            data-category={p.category}
          >{p.name}</td>
          <td class="num">{p.pid}</td>
          <td>{p.user}</td>
          <td>{p.state}</td>
          <td class="num">{fmtCpu(p.cpu_pct)}</td>
          <td class="num">{fmtRss(p.rss_mb)}</td>
          <td class="num">{fmtEtime(p.etime_s)}</td>
          <td class="cmdline">{fmtCmdline(p.cmdline)}</td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#if visible.length === 0}
    <div class="muted empty" data-testid="proc-empty">검색 결과가 없습니다.</div>
  {/if}
</div>

<style>
  .proc-table {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .info-popover {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: var(--space-2);
    font-size: var(--font-size-sm);
  }
  .info-popover summary {
    cursor: pointer;
    color: var(--color-text-muted);
  }
  .info-list {
    margin: var(--space-2) 0 0 0;
    padding-left: 1.4em;
  }
  .info-list li {
    margin-bottom: var(--space-1);
  }
  .filter-bar {
    display: flex;
    gap: var(--space-3);
    align-items: center;
  }
  .filter-bar input[type='search'] {
    flex: 1;
    min-width: 200px;
    padding: var(--space-1) var(--space-2);
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
  }
  .checkbox {
    display: flex;
    gap: var(--space-1);
    align-items: center;
    user-select: none;
  }
  .muted {
    color: var(--color-text-muted);
    font-size: var(--font-size-sm);
  }
  .dup-banner {
    padding: var(--space-2) var(--space-3);
    background: var(--color-warning-bg);
    color: var(--color-status-err);
    border: 1px solid var(--color-status-err);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-md);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-size-sm);
    font-variant-numeric: tabular-nums;
  }
  th {
    text-align: left;
    background: var(--color-bg);
    color: var(--color-text-muted);
    padding: var(--space-1) var(--space-2);
    border-bottom: 1px solid var(--color-border);
    font-weight: normal;
  }
  th.num,
  td.num {
    text-align: right;
  }
  th.sortable {
    cursor: pointer;
    user-select: none;
  }
  th.sortable:hover {
    color: var(--color-text);
  }
  td {
    padding: var(--space-1) var(--space-2);
    border-bottom: 1px solid var(--color-border);
  }
  tr.dup td.name-cell {
    border-left: var(--border-width-emphasis) solid var(--color-status-err);
    padding-left: calc(var(--space-2) - var(--border-width-emphasis));
  }
  /* Mode-A M5 + Final fold O1: typography over background shading.
     `name-managed` uses the existing `--color-status-warn` token in
     both light + dark modes; no raw hex literals.
     issue#14 Patch C1 (2026-05-02): the `godo` category (any process
     in GODO_PROCESS_NAMES that isn't a managed unit, e.g. `godo_smoke`,
     `godo_jitter`, `godo_freed_passthrough`) now gets a distinguishing
     accent color in addition to the bold weight, so both halves of the
     godo-family (`godo` + `managed`) are visually grouped against the
     general-process noise. Operator stake: System tab triage at a
     glance. */
  .name-cell {
    font-family: var(--font-mono);
  }
  .name-godo {
    font-weight: bold;
    color: var(--color-accent);
  }
  .name-managed {
    font-weight: bold;
    color: var(--color-status-warn);
  }
  /* issue#16 HIL hot-fix — docker-family rows render bold + colour
     swap based on mapping state. Idle (default) → green so the
     daemons read as "alive but not active"; mapping running → accent
     blue (matches the godo-family palette) to signal "actively
     driving the container". */
  .name-docker {
    font-weight: bold;
    color: var(--color-status-ok);
  }
  .name-docker.docker-active {
    color: var(--color-accent);
  }
  .cmdline {
    font-family: var(--font-mono);
    color: var(--color-text-muted);
    word-break: break-all;
  }
  .empty {
    padding: var(--space-2) 0;
    font-style: italic;
  }
</style>
