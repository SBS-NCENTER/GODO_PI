<script lang="ts">
  /**
   * issue#14 — Map > Mapping sub-tab body.
   *
   * Hosts: name input + validation, Start/Stop buttons, live preview
   * canvas, monitor strip, journal tail panel on Failed.
   */

  import { onDestroy, onMount } from 'svelte';
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
  } from '$lib/protocol';
  import { refreshMappingStatus, subscribeMappingStatus } from '$stores/mappingStatus';

  const NAME_RE = new RegExp(MAPPING_NAME_REGEX_SOURCE);

  let status = $state<MappingStatus | null>(null);
  let unsub: (() => void) | null = null;
  let name = $state('');
  let starting = $state(false);
  let stopping = $state(false);
  let lastError = $state<string | null>(null);
  let journalLines = $state<string[]>([]);
  let journalLoading = $state(false);

  onMount(() => {
    unsub = subscribeMappingStatus((s) => (status = s));
  });
  onDestroy(() => unsub?.());

  function validateName(s: string): string | null {
    if (!s) return '이름을 입력해 주세요.';
    if (s.length > MAPPING_NAME_MAX_LEN) return `${MAPPING_NAME_MAX_LEN}자 이내로 입력해 주세요.`;
    if (MAPPING_RESERVED_NAMES.has(s)) return '예약된 이름은 사용할 수 없습니다.';
    if (!NAME_RE.test(s)) return '허용되지 않는 문자가 포함되어 있습니다 (영문/숫자/._-(),).';
    return null;
  }

  let nameError = $derived(name === '' ? null : validateName(name));
  let canStart = $derived(
    status?.state === MAPPING_STATE_IDLE && nameError === null && name !== '' && !starting,
  );
  let canStop = $derived(
    status?.state === MAPPING_STATE_RUNNING ||
      status?.state === MAPPING_STATE_STARTING,
  );

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
    Mapping (issue#14)
    <span class="state-badge {badge.cls}" data-testid="mapping-state-badge">
      {badge.text}
    </span>
  </h3>

  {#if status?.state === MAPPING_STATE_IDLE}
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
    <MappingPreviewCanvas mapName={status.map_name} />
    <MappingMonitorStrip />
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
        Acknowledge
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
</style>
