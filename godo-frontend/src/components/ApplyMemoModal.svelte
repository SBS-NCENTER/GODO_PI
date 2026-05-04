<script lang="ts">
  /**
   * issue#28 — postfix memo modal + SSE progress consumer.
   *
   * Sole owner of the Apply UX. Validates the memo against
   * `MEMO_REGEX_SOURCE`; on confirm emits `onApply(memo)` and shows the
   * SSE progress bar driven by `/api/map/edit/progress`. Tracker
   * control buttons are NOT directly disabled here — the parent
   * MapEdit.svelte signals via the `disableTrackerControls` event so
   * the System tab listener can grey itself.
   */

  import {
    MEMO_MAX_LEN_CHARS,
    MEMO_REGEX_SOURCE,
    SSE_PROGRESS_PATH,
  } from '../lib/constants.js';

  interface Props {
    open: boolean;
    onApply: (memo: string) => void;
    onCancel: () => void;
    /**
     * issue#28 (Mode-B CR3) — request_id captured from the POST
     * /api/map/edit/{coord,erase} response body. When non-null,
     * incoming SSE frames whose `request_id` does NOT match are
     * dropped on the client. Null means "do not filter" — applies
     * before the POST returns OR when the parent has not yet wired
     * the filter (back-compat with older callers).
     */
    sessionRequestId?: string | null;
  }

  let { open, onApply, onCancel, sessionRequestId = null }: Props = $props();

  let memo = $state('');
  let progress = $state(0);
  let phase = $state<'idle' | 'starting' | 'yaml_rewrite' | 'rotate' | 'restart_pending' | 'done' | 'rejected'>('idle');
  let rejectionReason = $state<string | null>(null);
  let memoRegex = new RegExp(MEMO_REGEX_SOURCE);

  function isMemoValid(value: string): boolean {
    return value.length > 0 && value.length <= MEMO_MAX_LEN_CHARS && memoRegex.test(value);
  }

  let valid = $derived(isMemoValid(memo));

  function confirm(): void {
    if (!valid) return;
    onApply(memo);
    // Phase transitions arrive via SSE — the parent owns connection
    // lifecycle and pipes frames here.
  }

  // SSE subscription: connect when open, disconnect when closed.
  let eventSource: EventSource | null = null;
  $effect(() => {
    if (!open) {
      eventSource?.close();
      eventSource = null;
      progress = 0;
      phase = 'idle';
      rejectionReason = null;
      return;
    }
    if (typeof EventSource === 'undefined') return;
    const es = new EventSource(SSE_PROGRESS_PATH);
    eventSource = es;
    es.onmessage = (ev: MessageEvent) => {
      try {
        const frame = JSON.parse(ev.data) as {
          phase: typeof phase;
          progress: number;
          reason?: string;
          request_id?: string;
        };
        // issue#28 (Mode-B CR3) — drop frames belonging to a different
        // Apply session. The server tags every frame with `request_id`
        // (verified in app.py::_apply_map_edit_pipeline); a stale
        // tab's leftover frames or a near-simultaneous Apply on
        // another browser would otherwise mix into this modal's
        // progress bar.
        if (
          sessionRequestId !== null &&
          typeof frame.request_id === 'string' &&
          frame.request_id !== sessionRequestId
        ) {
          // Visible-in-DevTools breadcrumb without warn-spam; the
          // rejected frame still drops cleanly.
          // eslint-disable-next-line no-console
          console.debug(
            '[ApplyMemoModal] dropping stale SSE frame',
            frame.request_id,
            'expected',
            sessionRequestId,
          );
          return;
        }
        progress = frame.progress;
        phase = frame.phase;
        if (frame.phase === 'rejected') {
          rejectionReason = frame.reason ?? 'unknown';
        }
      } catch {
        // ignore malformed frame
      }
    };
    return () => {
      es.close();
      eventSource = null;
    };
  });
</script>

{#if open}
  <div class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="apply-memo-modal-title">
    <div class="modal">
      <h2 id="apply-memo-modal-title">메모 입력</h2>
      <p class="hint">파생 맵 이름의 후위 식별자입니다 (영문/숫자/_/-, 최대 {MEMO_MAX_LEN_CHARS}자).</p>
      <input
        type="text"
        bind:value={memo}
        maxlength={MEMO_MAX_LEN_CHARS}
        placeholder="예: wallcal01"
        aria-label="memo"
      />
      {#if memo.length > 0 && !valid}
        <p class="error">유효하지 않은 메모입니다.</p>
      {/if}
      {#if phase !== 'idle'}
        <div class="progress" aria-label="진행">
          <div class="bar" style:width="{Math.round(progress * 100)}%"></div>
          <p class="phase">{phase} ({Math.round(progress * 100)}%)</p>
          {#if phase === 'rejected'}
            <p class="error">실패: {rejectionReason}</p>
          {/if}
        </div>
      {/if}
      <div class="actions">
        <button type="button" onclick={() => onCancel()}>취소</button>
        <button type="button" disabled={!valid || (phase !== 'idle' && phase !== 'rejected' && phase !== 'done')} onclick={confirm}>
          적용
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }
  .modal {
    background: var(--color-bg, #ffffff);
    color: var(--color-text, #1f2937);
    border-radius: 8px;
    padding: 16px 20px;
    min-width: 360px;
    max-width: 90vw;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  }
  h2 { margin: 0 0 8px; font-size: 18px; }
  .hint { font-size: 12px; color: var(--color-muted, #6b7280); margin: 0 0 8px; }
  input[type="text"] { width: 100%; padding: 6px 8px; font: inherit; }
  .error { color: #dc2626; font-size: 12px; margin: 4px 0 0; }
  .progress { margin-top: 12px; }
  .progress .bar { height: 6px; background: var(--color-accent, #2563eb); border-radius: 3px; transition: width 200ms; }
  .progress .phase { font-size: 12px; margin: 4px 0 0; color: var(--color-muted, #6b7280); }
  .actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
  .actions button { padding: 6px 14px; font: inherit; cursor: pointer; }
  .actions button:disabled { cursor: not-allowed; opacity: 0.5; }
</style>
