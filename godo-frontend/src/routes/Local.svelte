<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import ServiceCard from '$components/ServiceCard.svelte';
  import { ApiError, apiGet, apiPost } from '$lib/api';
  import {
    JOURNAL_TAIL_DEFAULT_N,
    LOCAL_HOSTNAMES,
    LOCAL_SERVICES_POLL_MS,
    SVC_NAMES,
  } from '$lib/constants';
  import type { ServiceStatus, ServicesStreamFrame } from '$lib/protocol';
  import { SSEClient } from '$lib/sse';
  import { auth, getToken } from '$stores/auth';

  const isLoopback =
    typeof window !== 'undefined' && LOCAL_HOSTNAMES.includes(window.location.hostname);

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });
  let isAdmin = $derived(session?.role === 'admin');

  let services = $state<ServiceStatus[]>([]);
  let journalMap = $state<Record<string, string[]>>({});
  let sseClient: SSEClient | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let confirmRebootOpen = $state(false);
  let confirmShutdownOpen = $state(false);
  let actionError = $state<string | null>(null);

  async function fetchJournals(): Promise<void> {
    const next: Record<string, string[]> = {};
    await Promise.all(
      SVC_NAMES.map(async (svc) => {
        try {
          const lines = await apiGet<string[]>(
            `/api/local/journal/${svc}?n=${JOURNAL_TAIL_DEFAULT_N}`,
          );
          next[svc] = lines;
        } catch {
          next[svc] = [];
        }
      }),
    );
    journalMap = next;
  }

  async function pollServices(): Promise<void> {
    try {
      services = await apiGet<ServiceStatus[]>('/api/local/services');
    } catch {
      // Keep last value.
    }
  }

  function stopPolling(): void {
    if (pollTimer !== null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function startSSE(): void {
    if (sseClient !== null) return;
    sseClient = new SSEClient({
      path: '/api/local/services/stream',
      getToken,
      onMessage: (payload: unknown) => {
        // Per Mode-B M1: a successful frame disarms the polling fallback
        // so we do not double-fetch after a transient backend bounce.
        stopPolling();
        const frame = payload as ServicesStreamFrame;
        if (frame && Array.isArray(frame.services)) services = frame.services;
      },
      onError: () => {
        if (pollTimer === null)
          pollTimer = setInterval(() => void pollServices(), LOCAL_SERVICES_POLL_MS);
      },
    });
    const opened = sseClient.open();
    if (!opened) {
      sseClient = null;
      pollTimer = setInterval(() => void pollServices(), LOCAL_SERVICES_POLL_MS);
    }
  }

  function onCardAction(): void {
    void fetchJournals();
    void pollServices();
  }

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

  onMount(() => {
    if (!isLoopback) return;
    void pollServices();
    void fetchJournals();
    startSSE();
  });

  onDestroy(() => {
    sseClient?.close();
    stopPolling();
  });
</script>

{#if !isLoopback}
  <div class="card" data-testid="local-not-allowed">
    <h2>Local 패널</h2>
    <p>이 페이지는 RPi 5 본체에서만 표시됩니다.</p>
    <p class="muted">
      현재 호스트: {typeof window !== 'undefined' ? window.location.hostname : '-'}
    </p>
  </div>
{:else}
  <div data-testid="local-page">
    <div class="breadcrumb">GODO &gt; Local</div>
    <h2>Local services</h2>

    <div class="vstack">
      {#each services as svc (svc.name)}
        <ServiceCard
          service={svc}
          {isAdmin}
          journalLines={journalMap[svc.name] ?? []}
          onAction={onCardAction}
        />
      {/each}
    </div>

    <div class="card" style="margin-top: 24px;">
      <h3>System</h3>
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
      {#if !isAdmin}
        <div class="muted" style="margin-top: 8px;">admin 권한이 필요합니다.</div>
      {/if}
      {#if actionError}
        <div class="muted" style="color: var(--color-status-err); margin-top: 8px;">
          {actionError}
        </div>
      {/if}
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
{/if}

<style>
  h2,
  h3 {
    margin-top: 0;
  }
</style>
