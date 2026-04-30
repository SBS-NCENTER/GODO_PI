<script lang="ts">
  /**
   * Track B-CONFIG (PR-CONFIG-β) — Config editor page.
   * Track B-CONFIG PR-C — page-level Edit-mode safety gate.
   *
   * State machine (canonical, see
   * `.claude/memory/project_config_tab_edit_mode_ux.md`):
   *
   *   View  ──[admin clicks EDIT]──►  Edit
   *   Edit  ──[Cancel + pending=0]──►  View
   *   Edit  ──[Cancel + pending>0 + confirm]──►  View (pending discarded)
   *   Edit  ──[Apply, all ok]──►  View
   *   Edit  ──[Apply, any failure]──►  Edit (failed keys remain pending)
   *
   * Cancel NEVER fires a PATCH — it is client-side only. If somebody
   * adds reverse-PATCH "for symmetry," that is a regression.
   *
   * Apply uses best-effort sequential PATCH via
   * `stores/config.ts::applyBatch`; succeeded keys are removed from
   * pending, failed keys stay with their error text.
   *
   * The tracker-inactive banner is sourced from the existing
   * `systemServices` polling store (no new endpoint).
   *
   * RestartPendingBanner is rendered globally in App.svelte; do not
   * double-render here.
   */

  import ConfigEditor from '$components/ConfigEditor.svelte';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import { onDestroy, onMount, untrack } from 'svelte';
  import { auth } from '$stores/auth';
  import { ROLE_ADMIN, type ConfigSchemaRow, type ConfigValue } from '$lib/protocol';
  import {
    config as configStore,
    refresh,
    applyBatch,
    type ApplyBatchResult,
  } from '$stores/config';
  import { subscribeSystemServices } from '$stores/systemServices';
  import { CONFIG_APPLY_RESULT_MARKER_TTL_MS } from '$lib/constants';

  let isAdmin = $state(false);
  let unsubAuth: (() => void) | null = null;

  // Schema + current values mirrored from the store. The store is the
  // SSOT; this page only re-projects.
  let schema = $state<ConfigSchemaRow[]>([]);
  let current = $state<Record<string, ConfigValue>>({});
  let unsubConfig: (() => void) | null = null;

  // Page-local state — resets on /config route unmount per memory
  // §"How to apply". Hoisting any of these to a store would defeat
  // the safety gate (e.g. a forgotten Edit-mode in another tab).
  let mode = $state<'view' | 'edit'>('view');
  let pending = $state<Record<string, string>>({});
  let isApplying = $state(false);
  let applyResults = $state<Record<string, { ok: boolean; error?: string }>>({});
  let applyResultTimer: ReturnType<typeof setTimeout> | null = null;
  let applySummary = $state<{ ok: number; fail: number } | null>(null);

  // Tracker-active gate for the "현재값은 godo-tracker가 실행 중일 때만…"
  // banner. We DO NOT add a new endpoint — `systemServices` already polls
  // `/api/system/services` at 1 Hz (invariant (t)).
  let trackerActive = $state<boolean | null>(null);
  let unsubServices: (() => void) | null = null;

  // Cancel-with-pending confirm dialog state.
  let cancelDialogOpen = $state(false);

  // Derived — coerce raw input back into the schema's typed value.
  // Inline (not exported) so each Apply iteration walks the schema once
  // and avoids dragging the regex into a hot test path.
  function coerce(row: ConfigSchemaRow, raw: string): ConfigValue | null {
    const trimmed = raw.trim();
    if (row.type === 'int') {
      if (!/^-?\d+$/.test(trimmed)) return null;
      return parseInt(trimmed, 10);
    }
    if (row.type === 'double') {
      const n = Number(trimmed);
      if (Number.isNaN(n)) return null;
      return n;
    }
    return trimmed;
  }

  function setPending(key: string, raw: string): void {
    if (raw === '') {
      // Empty input → drop the key (matches Escape-to-clear UX).
      const { [key]: _drop, ...rest } = pending;
      void _drop;
      pending = rest;
      return;
    }
    pending = { ...pending, [key]: raw };
  }

  function pendingCount(): number {
    return Object.keys(pending).length;
  }

  function enterEdit(): void {
    if (!isAdmin || mode !== 'view') return;
    mode = 'edit';
    // Clear any stale apply markers from a previous Edit session.
    applyResults = {};
    applySummary = null;
  }

  function discardPending(): void {
    pending = {};
    mode = 'view';
    cancelDialogOpen = false;
    applyResults = {};
    applySummary = null;
  }

  function onCancelClick(): void {
    if (isApplying) return;
    if (pendingCount() === 0) {
      discardPending();
      return;
    }
    cancelDialogOpen = true;
  }

  function dismissCancelDialog(): void {
    cancelDialogOpen = false;
  }

  async function onApplyClick(): Promise<void> {
    if (isApplying || mode !== 'edit') return;
    if (pendingCount() === 0) return;

    // Coerce raw text → typed values; reject malformed inputs up-front
    // so we don't fire PATCHes that the tracker would reject anyway.
    const schemaByName: Record<string, ConfigSchemaRow> = {};
    for (const row of schema) schemaByName[row.name] = row;

    const typed: Record<string, ConfigValue> = {};
    const upfrontFailures: Record<string, { ok: boolean; error?: string }> = {};
    for (const [key, raw] of Object.entries(pending)) {
      const row = schemaByName[key];
      if (!row) continue;
      const coerced = coerce(row, raw);
      if (coerced === null) {
        upfrontFailures[key] = { ok: false, error: `bad ${row.type} literal` };
      } else {
        typed[key] = coerced;
      }
    }

    isApplying = true;

    let results: ApplyBatchResult[] = [];
    if (Object.keys(typed).length > 0) {
      results = await applyBatch(typed);
    }

    // Merge upfront-failures with PATCH results.
    const merged: Record<string, { ok: boolean; error?: string }> = { ...upfrontFailures };
    for (const r of results) {
      merged[r.key] = r.ok ? { ok: true } : { ok: false, error: r.error };
    }

    applyResults = merged;

    // Drop succeeded keys from pending; keep failures so the operator
    // can fix them inline. Memory: "Cancel semantics: don't undo
    // already-applied keys."
    const nextPending: Record<string, string> = {};
    let okCount = 0;
    let failCount = 0;
    for (const [key, raw] of Object.entries(pending)) {
      const r = merged[key];
      if (r?.ok) {
        okCount += 1;
      } else {
        failCount += 1;
        nextPending[key] = raw;
      }
    }
    pending = nextPending;
    applySummary = { ok: okCount, fail: failCount };

    isApplying = false;

    // All ok → return to View. Any failure → stay in Edit so the
    // operator can fix the failing inputs without re-clicking EDIT.
    if (failCount === 0) {
      mode = 'view';
    }

    // Auto-clear the per-row markers after the TTL.
    if (applyResultTimer !== null) clearTimeout(applyResultTimer);
    applyResultTimer = setTimeout(() => {
      applyResults = {};
      applySummary = null;
      applyResultTimer = null;
    }, CONFIG_APPLY_RESULT_MARKER_TTL_MS);
  }

  onMount(() => {
    unsubAuth = auth.subscribe((s) => {
      isAdmin = s !== null && s.role === ROLE_ADMIN;
      // Demoting from admin → viewer mid-session forces a clean View.
      if (!isAdmin && untrack(() => mode) === 'edit') {
        pending = {};
        mode = 'view';
        cancelDialogOpen = false;
      }
    });

    unsubConfig = configStore.subscribe((s) => {
      schema = s.schema;
      current = s.current;
    });
    void refresh();

    unsubServices = subscribeSystemServices((s) => {
      // Banner suppression (R5): only render once we have a fetched
      // services list. Empty list (initial load) → null → no banner.
      if (!s.services || s.services.length === 0) {
        trackerActive = null;
        return;
      }
      const t = s.services.find((x) => x.name === 'godo-tracker');
      if (!t) {
        trackerActive = null;
        return;
      }
      const wasActive = trackerActive;
      trackerActive = t.active_state === 'active';
      // On an inactive→active transition, refresh /api/config so the
      // operator sees fresh values immediately (the banner is about to
      // disappear).
      if (wasActive === false && trackerActive === true) {
        void refresh();
      }
    });
  });

  onDestroy(() => {
    unsubAuth?.();
    unsubConfig?.();
    unsubServices?.();
    if (applyResultTimer !== null) {
      clearTimeout(applyResultTimer);
      applyResultTimer = null;
    }
  });
</script>

<section class="config-page" data-testid="config-page">
  <header>
    <div class="header-row">
      <h1>Configuration</h1>
      <div class="header-actions" data-testid="config-actions">
        {#if mode === 'view'}
          <button
            type="button"
            class="primary"
            disabled={!isAdmin}
            onclick={enterEdit}
            data-testid="config-edit"
            title={isAdmin ? '편집 모드 진입' : '관리자만 편집할 수 있습니다'}
          >
            EDIT
          </button>
        {:else}
          <button
            type="button"
            disabled={isApplying}
            onclick={onCancelClick}
            data-testid="config-cancel"
          >
            Cancel
          </button>
          <button
            type="button"
            class="primary"
            disabled={isApplying || pendingCount() === 0}
            onclick={onApplyClick}
            data-testid="config-apply"
          >
            {#if isApplying}
              적용 중…
            {:else}
              Apply
            {/if}
          </button>
        {/if}
      </div>
    </div>
    <p class="hint">
      Tier-2 키 (~37). 즉시 반영(✓), 재시작 필요(!), 재시작+재캘리브레이션 필요(!!) 가 각 행에
      표시됩니다.
    </p>
    {#if trackerActive === false}
      <div class="banner banner-warn" data-testid="config-tracker-banner">
        현재값은 godo-tracker가 실행 중일 때만 표시됩니다 — System 탭에서 Start
      </div>
    {/if}
    {#if applySummary && applySummary.fail === 0 && applySummary.ok > 0}
      <div class="banner banner-info" data-testid="config-apply-summary">
        {applySummary.ok}개 키가 적용되었습니다.
      </div>
    {:else if applySummary && applySummary.fail > 0}
      <div class="banner banner-error" data-testid="config-apply-summary">
        {applySummary.ok}개 적용, {applySummary.fail}개 실패. 실패한 행에 사유가 표시됩니다.
      </div>
    {/if}
  </header>

  <ConfigEditor
    admin={isAdmin}
    {mode}
    {isApplying}
    {schema}
    {current}
    {pending}
    {applyResults}
    {setPending}
  />

  <ConfirmDialog
    open={cancelDialogOpen}
    title="편집 취소"
    message={`${pendingCount()}개 변경사항이 폐기됩니다. 계속하시겠습니까?`}
    confirmLabel="확인"
    cancelLabel="취소"
    onConfirm={discardPending}
    onCancel={dismissCancelDialog}
  />
</section>

<style>
  .config-page {
    padding: var(--space-3);
    max-width: 1100px;
    margin: 0 auto;
  }
  header h1 {
    margin: 0 0 var(--space-2) 0;
  }
  .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .header-actions {
    display: flex;
    gap: var(--space-2);
  }
  .hint {
    margin: 0 0 var(--space-3) 0;
    color: var(--color-text-muted);
  }
  .banner {
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-sm, 4px);
    margin-bottom: var(--space-3);
    font-size: 0.92em;
  }
  .banner-warn {
    background: rgba(255, 152, 0, 0.12);
    border: 1px solid rgba(255, 152, 0, 0.35);
    color: var(--color-text);
  }
  .banner-info {
    background: rgba(21, 101, 192, 0.1);
    color: var(--color-accent);
  }
  .banner-error {
    background: rgba(198, 40, 40, 0.1);
    color: var(--color-error, #c62828);
  }
</style>
