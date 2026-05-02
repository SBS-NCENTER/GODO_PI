<script lang="ts">
  /**
   * issue#14 — Map > Mapping sub-tab body.
   *
   * Hosts: name input + validation, Start/Stop buttons, live preview
   * canvas, monitor strip, journal tail panel on Failed.
   */

  import { onDestroy, onMount } from 'svelte';
  import MappingHostStrip from '$components/MappingHostStrip.svelte';
  import MappingMonitorStrip from '$components/MappingMonitorStrip.svelte';
  import MappingPreviewCanvas from '$components/MappingPreviewCanvas.svelte';
  import { apiGet, apiPost, ApiError } from '$lib/api';
  import {
    MAPPING_NAME_MAX_LEN,
    MAPPING_NAME_REGEX_SOURCE,
    MAPPING_OPERATION_TIMEOUT_MS,
    MAPPING_RESERVED_NAMES,
  } from '$lib/constants';
  import {
    MAPPING_STATE_FAILED,
    MAPPING_STATE_IDLE,
    MAPPING_STATE_RUNNING,
    MAPPING_STATE_STARTING,
    MAPPING_STATE_STOPPING,
    type MappingStatus,
    type PrecheckCheck,
    type PrecheckResult,
  } from '$lib/protocol';
  import { refreshMappingStatus, subscribeMappingStatus } from '$stores/mappingStatus';
  import { precheckStore, start as startPrecheck, stop as stopPrecheck } from '$stores/precheckStore';

  const NAME_RE = new RegExp(MAPPING_NAME_REGEX_SOURCE);

  // issue#16 — Korean labels for the precheck rows. Order does NOT
  // matter here (we render in the order returned by the backend); the
  // dictionary lookup just maps the canonical name to a human label.
  const PRECHECK_LABEL_KO: Record<string, string> = {
    lidar_readable: 'LiDAR 장치 읽기 가능',
    tracker_stopped: 'godo-tracker 정지됨',
    image_present: 'Docker 이미지 존재',
    disk_space_mb: '디스크 공간 (≥ 500 MB)',
    name_available: '맵 이름 사용 가능',
    state_clean: '이전 매핑 상태 정리됨',
    mapping_unit_clean: '매핑 unit/컨테이너 잔여 없음',
  };

  // issue#16 v7 — Korean tooltip for known mapping_unit_clean failure
  // detail strings. Falls back to the raw `detail` for unknown shapes.
  const PRECHECK_DETAIL_KO: Record<string, string> = {
    systemd_unit_failed_run_reset_failed:
      '이전 실행이 비정상 종료되어 systemd unit이 failed로 남아 있습니다. 터미널에서 `sudo systemctl reset-failed godo-mapping@active.service` 실행 후 다시 시도해 주세요.',
    container_lingering_exited: 'godo-mapping 컨테이너가 종료된 채 남아 있습니다. 다음 Start 시 자동 정리됩니다.',
    container_lingering_running: 'godo-mapping 컨테이너가 여전히 실행 중입니다.',
    container_lingering_created: 'godo-mapping 컨테이너가 생성됐으나 아직 실행 전입니다.',
    container_lingering_paused: 'godo-mapping 컨테이너가 paused 상태입니다.',
    container_lingering_dead: 'godo-mapping 컨테이너가 dead 상태입니다.',
  };

  let status = $state<MappingStatus | null>(null);
  let unsub: (() => void) | null = null;
  let unsubPrecheck: (() => void) | null = null;
  let precheck = $state<PrecheckResult>({ ready: false, checks: [] });
  let name = $state('');
  let starting = $state(false);
  let stopping = $state(false);
  let recovering = $state(false);
  let lastError = $state<string | null>(null);
  let journalLines = $state<string[]>([]);
  let journalLoading = $state(false);

  onMount(() => {
    unsub = subscribeMappingStatus((s) => (status = s));
    // issue#16 — start precheck polling. The closure reads `name` on
    // each tick so a fresh keystroke surfaces in the next URL.
    unsubPrecheck = precheckStore.subscribe((p) => (precheck = p));
    startPrecheck(() => name);
  });

  // issue#16 v7 — clear stale lastError when mapping transitions to a
  // resting state (Idle). Without this, after the operator clicks 확인
  // on a Failed view, the underlying error string from a prior 409
  // (mapping_already_active) or other onStart failure stays painted
  // beneath the all-green precheck rows even though state.json is now
  // Idle. Operator HIL 2026-05-02 evening surfaced this UX paper-cut.
  $effect(() => {
    if (status?.state === MAPPING_STATE_IDLE) {
      lastError = null;
    }
  });
  onDestroy(() => {
    unsub?.();
    unsubPrecheck?.();
    stopPrecheck();
  });

  function validateName(s: string): string | null {
    if (!s) return '이름을 입력해 주세요.';
    if (s.length > MAPPING_NAME_MAX_LEN) return `${MAPPING_NAME_MAX_LEN}자 이내로 입력해 주세요.`;
    if (MAPPING_RESERVED_NAMES.has(s)) return '예약된 이름은 사용할 수 없습니다.';
    if (!NAME_RE.test(s)) return '허용되지 않는 문자가 포함되어 있습니다 (영문/숫자/._-(),).';
    return null;
  }

  let nameError = $derived(name === '' ? null : validateName(name));
  // issue#16 — Start gate now also requires precheck.ready=true. The
  // precheck endpoint includes a name-availability row, so once the
  // operator types a valid+free name, the row flips to ok=true and the
  // backend's `ready=true` aggregate matches our local nameError===null.
  let canStart = $derived(
    status?.state === MAPPING_STATE_IDLE &&
      nameError === null &&
      name !== '' &&
      precheck.ready &&
      !starting,
  );
  let canStop = $derived(
    status?.state === MAPPING_STATE_RUNNING ||
      status?.state === MAPPING_STATE_STARTING,
  );

  // issue#16 — derived helpers for the precheck panel.
  let lidarRow = $derived(
    precheck.checks.find((c) => c.name === 'lidar_readable') ?? null,
  );
  let canRecoverLidar = $derived(
    !recovering && lidarRow !== null && lidarRow.ok === false,
  );

  function rowGlyph(row: PrecheckCheck): string {
    if (row.ok === true) return '✓';
    if (row.ok === false) return '✗';
    return '⋯'; // pending
  }

  function rowClass(row: PrecheckCheck): string {
    if (row.ok === true) return 'precheck-row-ok';
    if (row.ok === false) return 'precheck-row-fail';
    return 'precheck-row-pending';
  }

  async function onRecoverLidar(): Promise<void> {
    recovering = true;
    lastError = null;
    try {
      await apiPost('/api/mapping/recover-lidar', {});
      // The 1 Hz precheck tick will reflect the new state shortly.
    } catch (e) {
      lastError = e instanceof ApiError && e.body?.detail
        ? `${e.body.err}: ${e.body.detail}`
        : e instanceof Error
          ? e.message
          : String(e);
    } finally {
      recovering = false;
    }
  }

  // Operator UX 2026-05-02 KST: always-visible state badge so operators
  // see the current mapping coordinator state (idle / starting / running
  // / stopping / failed) at a glance without having to read which body
  // block rendered. Pre-fix the only state cue was indirect (the form
  // body shape) — operator could not tell "is this thing alive? is the
  // status fetch still in flight?" without checking DevTools.
  function stateBadge(s: string | undefined): { text: string; cls: string } {
    if (s === undefined) return { text: '연결 중…', cls: 'badge-loading' };
    if (s === MAPPING_STATE_IDLE)     return { text: '대기 (Idle)',          cls: 'badge-idle' };
    if (s === MAPPING_STATE_STARTING) return { text: '시작 중 (Starting)',    cls: 'badge-active' };
    if (s === MAPPING_STATE_RUNNING)  return { text: '매핑 중 (Running)',     cls: 'badge-active' };
    if (s === MAPPING_STATE_STOPPING) return { text: '저장 중 (Stopping)',    cls: 'badge-active' };
    if (s === MAPPING_STATE_FAILED)   return { text: '실패 (Failed)',         cls: 'badge-failed' };
    return { text: s, cls: 'badge-loading' };
  }
  let badge = $derived(stateBadge(status?.state));

  async function onStart(): Promise<void> {
    if (!canStart) return;
    starting = true;
    lastError = null;
    try {
      // Long timeout — start blocks ~25 s for tracker stop + container
      // start polling. Default 3 s aborts long before backend completes
      // (operator sees request_aborted while backend keeps going).
      await apiPost('/api/mapping/start', { name }, { timeoutMs: MAPPING_OPERATION_TIMEOUT_MS });
      void refreshMappingStatus();
    } catch (e) {
      lastError = e instanceof ApiError && e.body?.detail
        ? `${e.body.err}: ${e.body.detail}`
        : e instanceof Error
          ? e.message
          : String(e);
    } finally {
      starting = false;
    }
  }

  async function onStop(): Promise<void> {
    stopping = true;
    lastError = null;
    try {
      // Long timeout — stop blocks up to MAPPING_CONTAINER_STOP_TIMEOUT_S
      // (35 s — Maj-1 ladder protects map_saver atomic-rename window).
      // Default 3 s would abort while map is still being saved on the
      // backend (operator's "맵은 저장됐는데 request_aborted 떠" symptom).
      await apiPost('/api/mapping/stop', {}, { timeoutMs: MAPPING_OPERATION_TIMEOUT_MS });
      void refreshMappingStatus();
    } catch (e) {
      lastError = e instanceof ApiError && e.body?.err
        ? e.body.err
        : e instanceof Error
          ? e.message
          : String(e);
    } finally {
      stopping = false;
    }
  }

  async function loadJournal(): Promise<void> {
    journalLoading = true;
    try {
      const r = await apiGet<{ lines: string[] }>('/api/mapping/journal?n=50');
      journalLines = r.lines;
    } catch {
      journalLines = [];
    } finally {
      journalLoading = false;
    }
  }
</script>

<section data-testid="map-mapping-section">
  <h3>
    Mapping
    <span class="state-badge {badge.cls}" data-testid="mapping-state-badge">
      {badge.text}
    </span>
  </h3>

  {#if status?.state === MAPPING_STATE_IDLE}
    <!-- issue#16 — Pre-check panel. 6 fixed-order rows polled at 1 Hz. -->
    <div class="precheck-panel" data-testid="mapping-precheck-panel">
      <h4>준비 상태 (Pre-check)</h4>
      {#if precheck.checks.length === 0}
        <p class="hint">상태 확인 중…</p>
      {:else}
        <ul class="precheck-list">
          {#each precheck.checks as row (row.name)}
            <li class={rowClass(row)} data-testid={`precheck-row-${row.name}`}>
              <span class="precheck-glyph" data-testid={`precheck-glyph-${row.name}`}>
                {rowGlyph(row)}
              </span>
              <span class="precheck-label">
                {PRECHECK_LABEL_KO[row.name] ?? row.name}
              </span>
              {#if row.detail}
                <span class="precheck-detail">
                  — {PRECHECK_DETAIL_KO[row.detail] ?? row.detail}
                </span>
              {/if}
              {#if row.name === 'lidar_readable' && row.ok === false}
                <button
                  type="button"
                  class="recover-btn"
                  onclick={onRecoverLidar}
                  disabled={!canRecoverLidar}
                  data-testid="mapping-recover-lidar-button">
                  🔧 LiDAR USB 복구
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </div>

    <div class="form">
      <label>
        이름:
        <input
          type="text"
          bind:value={name}
          maxlength={MAPPING_NAME_MAX_LEN}
          placeholder="control_room_v1"
          data-testid="mapping-name-input"
        />
      </label>
      {#if nameError}
        <p class="err">{nameError}</p>
      {:else if name === ''}
        <p class="hint">이름을 입력하면 Start 버튼이 활성화됩니다.</p>
      {:else if !precheck.ready}
        <p class="hint">준비 상태가 모두 통과해야 Start 버튼이 활성화됩니다.</p>
      {/if}
      <button
        type="button"
        onclick={onStart}
        disabled={!canStart}
        data-testid="mapping-start-button">
        Start
      </button>
      <p class="hint">
        Start를 누르면 godo-tracker가 정지되고 godo-mapping 컨테이너가 시작됩니다.
        매핑이 끝난 후에는 시스템 탭에서 godo-tracker를 직접 다시 시작해 주세요.
      </p>
    </div>
  {:else if status?.state === MAPPING_STATE_STARTING}
    <p>컨테이너 시작 중… ({status.map_name})</p>
  {:else if status?.state === MAPPING_STATE_RUNNING && status.map_name}
    <p>매핑 진행 중: <strong>{status.map_name}</strong></p>
    <button
      type="button"
      onclick={onStop}
      disabled={stopping}
      data-testid="mapping-stop-button">
      Stop & Save
    </button>
    <!-- issue#16 HIL hot-fix v2 (2026-05-02 KST) — monitor grid moved
         ABOVE the preview canvas so the operator can keep an eye on
         resource pressure while the slow-updating preview fills in
         below. RPi5 host strip uses numeric-only formatting (no bars,
         no animation) so its vertical height aligns with the Docker
         container strip — both panels read at a glance. -->
    <div class="monitor-grid" data-testid="mapping-monitor-grid">
      <MappingMonitorStrip />
      <MappingHostStrip />
    </div>
    <MappingPreviewCanvas mapName={status.map_name} />
  {:else if status?.state === MAPPING_STATE_STOPPING}
    <p>저장 중… ({status.map_name})</p>
  {:else if status?.state === MAPPING_STATE_FAILED}
    <div class="failed" data-testid="mapping-failed">
      <p class="err">실패: {status.error_detail ?? '(상세 정보 없음)'}</p>
      {#if status.journal_tail_available}
        <details>
          <summary>journal tail (지난 50줄)</summary>
          {#if journalLines.length === 0 && !journalLoading}
            <button type="button" onclick={loadJournal}>journal tail 가져오기</button>
          {:else if journalLoading}
            <p class="muted">로딩 중…</p>
          {:else}
            <pre>{journalLines.join('\n')}</pre>
          {/if}
        </details>
      {/if}
      <button type="button" onclick={onStop} data-testid="mapping-acknowledge-button">
        확인
      </button>
    </div>
  {/if}

  {#if lastError}
    <p class="err">{lastError}</p>
  {/if}
</section>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-width: 360px;
  }
  .err {
    color: var(--color-error, #c62828);
  }
  .hint {
    font-size: 0.85em;
    color: var(--color-text-muted);
  }
  .failed {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  .muted {
    color: var(--color-text-muted);
  }
  pre {
    max-height: 240px;
    overflow: auto;
    background: var(--color-surface);
    padding: var(--space-2);
    font-size: 0.8em;
  }
  .state-badge {
    display: inline-block;
    margin-left: var(--space-2);
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.7em;
    font-weight: 600;
    vertical-align: middle;
  }
  .badge-loading {
    background: var(--color-bg-elev);
    color: var(--color-text-muted);
    border: 1px solid var(--color-border);
  }
  .badge-idle {
    background: var(--color-status-ok-bg, rgba(46, 125, 50, 0.12));
    color: var(--color-status-ok, #2e7d32);
    border: 1px solid var(--color-status-ok, #2e7d32);
  }
  .badge-active {
    background: color-mix(in srgb, var(--color-warning, #f59e0b) 14%, var(--color-bg));
    color: var(--color-warning, #f59e0b);
    border: 1px solid var(--color-warning, #f59e0b);
  }
  .badge-failed {
    background: var(--color-status-err-bg, rgba(198, 40, 40, 0.12));
    color: var(--color-status-err, #c62828);
    border: 1px solid var(--color-status-err, #c62828);
  }
  /* issue#16 — Pre-check panel styles. */
  .precheck-panel {
    margin-bottom: var(--space-3);
    padding: var(--space-2);
    border: 1px solid var(--color-border);
    border-radius: 4px;
    background: var(--color-surface);
  }
  .precheck-panel h4 {
    margin: 0 0 var(--space-2) 0;
    font-size: 0.95em;
  }
  .precheck-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .precheck-list li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: 0.9em;
  }
  .precheck-glyph {
    display: inline-block;
    width: 1.2em;
    text-align: center;
    font-weight: bold;
  }
  .precheck-row-ok .precheck-glyph {
    color: var(--color-status-ok, #2e7d32);
  }
  .precheck-row-fail .precheck-glyph {
    color: var(--color-status-err, #c62828);
  }
  .precheck-row-pending .precheck-glyph {
    color: var(--color-text-muted);
  }
  .precheck-detail {
    color: var(--color-text-muted);
    font-size: 0.85em;
  }
  .recover-btn {
    margin-left: auto;
    padding: 2px 8px;
    font-size: 0.85em;
  }

  /* issue#16 HIL hot-fix v2 — 2-column monitor grid for the running
     view, positioned ABOVE the preview canvas. Docker container SSE
     on the left, RPi5 host resources on the right. Each cell hosts a
     self-contained strip component (MappingMonitorStrip /
     MappingHostStrip) that owns its own header + border, so the grid
     here is layout-only.  Single-column collapse below 900 px so the
     mobile preview path still reads cleanly. */
  .monitor-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3);
    margin-top: var(--space-2);
    margin-bottom: var(--space-3);
  }
  @media (max-width: 900px) {
    .monitor-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
