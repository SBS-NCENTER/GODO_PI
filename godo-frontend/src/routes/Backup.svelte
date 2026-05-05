<script lang="ts">
  /**
   * Backup — Track B-BACKUP page (P2 Step 2).
   *
   * Lists every map backup snapshot under `cfg.backup_dir`
   * (`/var/lib/godo/map-backups/`); admin-only "복원" button per row.
   * Restore re-creates the named pair inside `cfg.maps_dir` (Option A
   * semantics) — operator activates separately via `/map` + restarts
   * `godo-tracker`. The success toast wording mirrors Track E
   * (`MapListPanel.svelte:116`) so the restart-flow language is
   * consistent across both pages.
   *
   * Layout mirrors `MapListPanel.svelte`: anon-readable table + admin-
   * gated action button + `<ConfirmDialog/>` two-line body. Refresh
   * fires on (a) mount, (b) post-restore — no periodic polling.
   */

  import { onMount } from 'svelte';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import { ApiError, apiGet, apiPost } from '$lib/api';
  import { BACKUP_RESTORE_OVERWRITE_WARNING, BACKUP_RESTORE_SUCCESS_TOAST } from '$lib/constants';
  import { backupTsToUnix, formatDateTime } from '$lib/format';
  import type { BackupEntry, BackupListResponse, RestoreResponse } from '$lib/protocol';
  import { auth } from '$stores/auth';

  let entries = $state<BackupEntry[]>([]);
  let role = $state<'admin' | 'viewer' | null>(null);
  let unsubAuth: (() => void) | null = null;
  let restoreOpen = $state(false);
  let restoreTarget = $state<string | null>(null);
  let banner = $state<string | null>(null);
  let bannerKind = $state<'info' | 'error'>('info');

  function setBanner(msg: string, kind: 'info' | 'error' = 'info'): void {
    banner = msg;
    bannerKind = kind;
  }

  // `<ts>` arrives in one of two forms (issue#32):
  //  - Legacy UTC: `20260101T010101Z` (pre-PR #83).
  //  - KST (post-PR #83): `20260505T112600` (no suffix).
  // `backupTsToUnix` in `lib/format.ts` parses both correctly so the
  // human-readable "YYYY-MM-DD HH:MM" displayed via `formatDateTime`
  // matches the operator's wall clock regardless of which form a
  // given backup carries.

  async function refresh(): Promise<void> {
    try {
      const resp = await apiGet<BackupListResponse>('/api/map/backup/list');
      entries = resp.items;
    } catch (e: unknown) {
      const err = e as ApiError | { body?: { err?: string } } | null;
      const msg = (err && 'body' in err && err.body?.err) || '백업 목록을 가져오지 못했습니다.';
      setBanner(typeof msg === 'string' ? msg : '백업 목록을 가져오지 못했습니다.', 'error');
    }
  }

  onMount(() => {
    unsubAuth = auth.subscribe((s) => (role = s?.role ?? null));
    void refresh();
    return () => {
      unsubAuth?.();
    };
  });

  function openRestore(ts: string): void {
    restoreTarget = ts;
    restoreOpen = true;
  }

  async function confirmRestore(): Promise<void> {
    const ts = restoreTarget;
    restoreOpen = false;
    if (!ts) return;
    try {
      await apiPost<RestoreResponse>(`/api/map/backup/${encodeURIComponent(ts)}/restore`);
      setBanner(BACKUP_RESTORE_SUCCESS_TOAST, 'info');
      await refresh();
    } catch (e: unknown) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      setBanner(err ? `복원 실패: ${err}` : '복원 실패', 'error');
    }
    restoreTarget = null;
  }

  function cancelRestore(): void {
    restoreOpen = false;
    restoreTarget = null;
  }
</script>

<div data-testid="backup-page">
  <div class="breadcrumb">GODO &gt; Backup</div>
  <h2>Backup</h2>
  <section class="backup-panel" data-testid="backup-panel">
    {#if banner}
      <div class="banner banner-{bannerKind}" data-testid="backup-banner">{banner}</div>
    {/if}

    {#if entries.length === 0}
      <p class="muted" data-testid="backup-empty">백업이 없습니다.</p>
    {:else}
      <table data-testid="backup-table">
        <thead>
          <tr>
            <th>시점 (raw)</th>
            <th>로컬 시각</th>
            <th>파일 수</th>
            <th>총 크기 (B)</th>
            <th>작업</th>
          </tr>
        </thead>
        <tbody>
          {#each entries as entry (entry.ts)}
            <tr data-testid={`backup-row-${entry.ts}`}>
              <td><code>{entry.ts}</code></td>
              <td>{formatDateTime(backupTsToUnix(entry.ts))}</td>
              <td>{entry.files.length}</td>
              <td>{entry.size_bytes}</td>
              <td>
                <button
                  type="button"
                  disabled={role !== 'admin'}
                  onclick={() => openRestore(entry.ts)}
                  data-testid={`backup-restore-${entry.ts}`}
                >
                  복원
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}

    <ConfirmDialog
      open={restoreOpen}
      title="맵 백업 복원"
      message={restoreTarget
        ? `'${restoreTarget}' 시점의 맵을 복원합니다.\n${BACKUP_RESTORE_OVERWRITE_WARNING}`
        : ''}
      confirmLabel="복원"
      cancelLabel="취소"
      danger={true}
      onConfirm={confirmRestore}
      onCancel={cancelRestore}
    />
  </section>
</div>

<style>
  h2 {
    margin-top: 0;
  }
  .backup-panel {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    background: var(--color-bg-elev);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.92em;
  }
  th,
  td {
    border-bottom: 1px solid var(--color-border);
    padding: 4px 8px;
    text-align: left;
  }
  code {
    font-family: ui-monospace, monospace;
    font-size: 0.92em;
  }
  button[disabled] {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .banner {
    padding: 6px 10px;
    border-radius: var(--radius-sm);
    margin-bottom: var(--space-3);
  }
  .banner-info {
    background: rgba(21, 101, 192, 0.1);
    color: var(--color-accent);
  }
  .banner-error {
    background: rgba(198, 40, 40, 0.1);
    color: var(--color-status-err, #c62828);
  }
  .muted {
    color: var(--color-text-muted, #666);
  }
</style>
