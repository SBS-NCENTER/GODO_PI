<script lang="ts">
  /**
   * MapListPanel — Track E (PR-C).
   *
   * Lists every map under `cfg.maps_dir`, marks the active row, and
   * exposes admin-only "기본으로 지정" + "삭제" buttons.
   *
   * Activate dialog (per Mode-A M4 + N4): three buttons —
   *   cancel   (취소)
   *   secondary  (재시작하지 않음 — closes dialog after activating)
   *   primary    (godo-tracker 재시작 — calls /api/local/service/.../restart)
   *
   * On non-loopback hostnames (operator hits the SPA from a studio PC,
   * not the kiosk) the primary button is HIDDEN entirely with a
   * tooltip explaining that the restart action is loopback-only.
   *
   * Delete dialog: standard 2-button confirm. Disabled on the active
   * row (defence-in-depth — backend also returns 409 `map_is_active`).
   *
   * No periodic polling: refresh fires on (a) mount, (b) post-activate,
   * (c) post-delete (per Mode-A N6).
   */
  import { onDestroy, onMount } from 'svelte';
  import { get } from 'svelte/store';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import { apiPost } from '$lib/api';
  import { LOCAL_HOSTNAMES } from '$lib/constants';
  import { formatDateTime } from '$lib/format';
  import type { MapEntry } from '$lib/protocol';
  import { auth } from '$stores/auth';
  import { activate, maps, refresh, remove } from '$stores/maps';

  interface Props {
    onPreviewSelect?: (url: string) => void;
  }
  let { onPreviewSelect }: Props = $props();

  let entries = $state<MapEntry[]>([]);
  let unsubMaps: (() => void) | null = null;
  let role = $state<'admin' | 'viewer' | null>(null);
  let unsubAuth: (() => void) | null = null;

  let activateOpen = $state(false);
  let activateTarget = $state<string | null>(null);
  let deleteOpen = $state(false);
  let deleteTarget = $state<string | null>(null);
  let banner = $state<string | null>(null);
  let bannerKind = $state<'info' | 'error'>('info');

  function isLoopbackHost(): boolean {
    if (typeof window === 'undefined') return false;
    return LOCAL_HOSTNAMES.includes(window.location.hostname);
  }

  function setBanner(msg: string, kind: 'info' | 'error' = 'info'): void {
    banner = msg;
    bannerKind = kind;
  }

  onMount(() => {
    unsubMaps = maps.subscribe((v) => (entries = v));
    unsubAuth = auth.subscribe((s) => (role = s?.role ?? null));
    void refresh().catch((e: unknown) => {
      const err = (e as { body?: { err?: string } })?.body?.err;
      setBanner(
        err ? `맵 목록을 가져오지 못했습니다: ${err}` : '맵 목록을 가져오지 못했습니다.',
        'error',
      );
    });
  });

  onDestroy(() => {
    unsubMaps?.();
    unsubAuth?.();
  });

  function previewMap(name: string, isActive: boolean): void {
    if (!onPreviewSelect) return;
    onPreviewSelect(isActive ? '/api/map/image' : `/api/maps/${encodeURIComponent(name)}/image`);
  }

  function openActivate(name: string): void {
    activateTarget = name;
    activateOpen = true;
  }

  function openDelete(name: string): void {
    deleteTarget = name;
    deleteOpen = true;
  }

  async function activateThenRestart(): Promise<void> {
    const name = activateTarget;
    activateOpen = false;
    if (!name) return;
    try {
      await activate(name);
      // Restart is loopback-only — the button is hidden in the dialog
      // when the host is non-loopback, so reaching this branch implies
      // we ARE on loopback. The backend separately enforces the gate.
      await apiPost('/api/local/service/godo-tracker/restart', undefined);
      setBanner(`'${name}' 활성화 + godo-tracker 재시작 완료`, 'info');
    } catch (e: unknown) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      setBanner(err ? `재시작 실패: ${err}` : '재시작 실패', 'error');
    }
    activateTarget = null;
  }

  async function activateNoRestart(): Promise<void> {
    const name = activateTarget;
    activateOpen = false;
    if (!name) return;
    try {
      await activate(name);
      setBanner(`'${name}' 활성화 완료. godo-tracker 재시작 후 적용됩니다.`, 'info');
    } catch (e: unknown) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      setBanner(err ? `활성화 실패: ${err}` : '활성화 실패', 'error');
    }
    activateTarget = null;
  }

  function cancelActivate(): void {
    activateOpen = false;
    activateTarget = null;
  }

  async function confirmDelete(): Promise<void> {
    const name = deleteTarget;
    deleteOpen = false;
    if (!name) return;
    try {
      await remove(name);
      setBanner(`'${name}' 삭제 완료`, 'info');
    } catch (e: unknown) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      if (err === 'map_is_active') {
        setBanner('활성 맵은 삭제할 수 없습니다. 다른 맵을 먼저 활성화하세요.', 'error');
      } else {
        setBanner(err ? `삭제 실패: ${err}` : '삭제 실패', 'error');
      }
    }
    deleteTarget = null;
  }

  function cancelDelete(): void {
    deleteOpen = false;
    deleteTarget = null;
  }

  // Snapshot the auth role at module-call time for the disabled-state
  // attribute. The reactive subscription updates `role` at the
  // top-level `$state`, but we still want a stable reference for any
  // imperative path (e.g. the future "edit" follow-up) — `get(auth)`
  // is the canonical accessor.
  function isAdmin(): boolean {
    return get(auth)?.role === 'admin';
  }
  // Reference to silence the unused-helper lint while keeping the
  // accessor as a small documented utility.
  void isAdmin;
</script>

<section class="map-list-panel" data-testid="map-list-panel">
  <header>
    <h3>맵 목록</h3>
    {#if !isLoopbackHost()}
      <span
        class="loopback-hint"
        data-testid="loopback-hint"
        title="로컬 kiosk에서만 가능 (스튜디오 PC에서는 SSH로 재시작)"
      >
        (스튜디오 PC: 활성화 후 SSH로 재시작 필요)
      </span>
    {/if}
  </header>

  {#if banner}
    <div class="banner banner-{bannerKind}" data-testid="map-list-banner">{banner}</div>
  {/if}

  {#if entries.length === 0}
    <p class="muted" data-testid="map-list-empty">맵이 없습니다 — 매핑 컨테이너를 실행하세요.</p>
  {:else}
    <table data-testid="map-list-table">
      <thead>
        <tr>
          <th>이름</th>
          <th>크기 (B)</th>
          <th>최종 수정</th>
          <th>상태</th>
          <th>작업</th>
        </tr>
      </thead>
      <tbody>
        {#each entries as entry (entry.name)}
          <tr class={entry.is_active ? 'active' : ''} data-testid={`map-row-${entry.name}`}>
            <td>
              <button
                type="button"
                class="link"
                onclick={() => previewMap(entry.name, entry.is_active)}
                data-testid={`map-preview-${entry.name}`}
              >
                {entry.name}
              </button>
            </td>
            <td>{entry.size_bytes}</td>
            <td>{formatDateTime(entry.mtime_unix)}</td>
            <td>
              {#if entry.is_active}
                <span class="badge active-badge" data-testid={`map-active-${entry.name}`}>활성</span
                >
              {/if}
            </td>
            <td>
              <button
                type="button"
                disabled={role !== 'admin' || entry.is_active}
                onclick={() => openActivate(entry.name)}
                data-testid={`map-activate-${entry.name}`}
              >
                기본으로 지정
              </button>
              <button
                type="button"
                class="danger"
                disabled={role !== 'admin' || entry.is_active}
                title={entry.is_active ? '활성 맵은 삭제할 수 없습니다' : ''}
                onclick={() => openDelete(entry.name)}
                data-testid={`map-delete-${entry.name}`}
              >
                삭제
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <ConfirmDialog
    open={activateOpen}
    title="활성 맵 변경"
    message={activateTarget
      ? `'${activateTarget}'을(를) 활성 맵으로 지정하시겠습니까?\ngodo-tracker는 재시작 후 새 맵을 로드합니다.`
      : ''}
    confirmLabel="godo-tracker 재시작"
    cancelLabel="취소"
    onConfirm={activateThenRestart}
    onCancel={cancelActivate}
    showPrimary={isLoopbackHost()}
    primaryHiddenTooltip="로컬 kiosk에서만 가능 (스튜디오 PC에서는 SSH로 재시작)"
    secondaryAction={{ label: '재시작하지 않음', handler: activateNoRestart }}
  />

  <ConfirmDialog
    open={deleteOpen}
    title="맵 삭제"
    message={deleteTarget
      ? `'${deleteTarget}' 맵 페어를 삭제하시겠습니까? 되돌릴 수 없습니다.`
      : ''}
    confirmLabel="삭제"
    cancelLabel="취소"
    danger={true}
    onConfirm={confirmDelete}
    onCancel={cancelDelete}
  />
</section>

<style>
  .map-list-panel {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    margin-bottom: var(--space-4);
    background: var(--color-bg-elev);
  }
  header {
    display: flex;
    align-items: baseline;
    gap: var(--space-3);
    margin-bottom: var(--space-3);
  }
  h3 {
    margin: 0;
    font-size: var(--font-size-md);
  }
  .loopback-hint {
    font-size: 0.85em;
    color: var(--color-text-muted, #666);
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
  tr.active {
    background: var(--color-bg-elev-strong, rgba(21, 101, 192, 0.07));
  }
  .badge.active-badge {
    background: var(--color-status-ok, #2e7d32);
    color: white;
    border-radius: 3px;
    padding: 2px 6px;
    font-size: 0.85em;
  }
  button.link {
    background: none;
    border: none;
    color: var(--color-accent);
    cursor: pointer;
    padding: 0;
    text-decoration: underline;
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
</style>
