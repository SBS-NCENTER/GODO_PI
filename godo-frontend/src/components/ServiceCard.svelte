<script lang="ts">
  import { onDestroy } from 'svelte';
  import { apiPost, ApiError } from '$lib/api';
  import { SERVICE_TRANSITION_TOAST_TTL_MS } from '$lib/constants';
  import { ERR_SERVICE_STARTING, ERR_SERVICE_STOPPING, type ServiceStatus } from '$lib/protocol';
  import { statusChipClass } from '$lib/serviceStatus';
  import { refresh as refreshRestartPending } from '$stores/restartPending';

  interface Props {
    service: ServiceStatus;
    isAdmin: boolean;
    journalLines: string[];
    onAction?: (action: 'start' | 'stop' | 'restart') => void;
  }
  let { service, isAdmin, journalLines, onAction }: Props = $props();

  let busy = $state(false);
  let lastError = $state<string | null>(null);
  let dismissTimer: ReturnType<typeof setTimeout> | null = null;

  function clearDismissTimer(): void {
    if (dismissTimer !== null) {
      clearTimeout(dismissTimer);
      dismissTimer = null;
    }
  }

  function setErrorWithAutoDismiss(msg: string): void {
    lastError = msg;
    clearDismissTimer();
    dismissTimer = setTimeout(() => {
      lastError = null;
      dismissTimer = null;
    }, SERVICE_TRANSITION_TOAST_TTL_MS);
  }

  onDestroy(() => {
    clearDismissTimer();
  });

  async function action(act: 'start' | 'stop' | 'restart'): Promise<void> {
    if (!isAdmin || busy) return;
    busy = true;
    lastError = null;
    clearDismissTimer();
    try {
      await apiPost(`/api/local/service/${service.name}/${act}`);
      // godo-tracker boots clear the restart-pending sentinel; refresh
      // the SPA store so the banner clears without a page reload.
      // No-op for non-tracker services.
      void refreshRestartPending();
      onAction?.(act);
    } catch (e) {
      const err = e as ApiError;
      const errCode = err.body?.err;
      if (errCode === ERR_SERVICE_STARTING || errCode === ERR_SERVICE_STOPPING) {
        // Track B-SYSTEM PR-2 — 409 transition gate. Render the
        // Korean detail with auto-dismiss so the operator sees the
        // warning and the toast clears itself before the next click.
        setErrorWithAutoDismiss(err.body?.detail ?? errCode);
      } else {
        lastError = err.body?.err ?? err.message;
      }
    } finally {
      busy = false;
    }
  }
</script>

<div class="card" data-testid="service-card-{service.name}">
  <div class="hstack" style="justify-content: space-between;">
    <div class="hstack">
      <strong>{service.name}</strong>
      <span class="chip {statusChipClass(service.active)}" data-testid="service-status">
        {service.active}
      </span>
    </div>
    <div class="hstack">
      <button disabled={!isAdmin || busy} onclick={() => action('start')} data-testid="svc-start"
        >Start</button
      >
      <button disabled={!isAdmin || busy} onclick={() => action('stop')} data-testid="svc-stop"
        >Stop</button
      >
      <button
        disabled={!isAdmin || busy}
        onclick={() => action('restart')}
        data-testid="svc-restart">Restart</button
      >
    </div>
  </div>
  {#if lastError}
    <div class="muted" style="color: var(--color-status-err); margin-top: 8px;" role="status">
      {lastError}
    </div>
  {/if}
  {#if journalLines.length > 0}
    <details style="margin-top: 12px;">
      <summary class="muted">journalctl tail ({journalLines.length} lines)</summary>
      <pre class="journal">{journalLines.join('\n')}</pre>
    </details>
  {/if}
</div>

<style>
  .journal {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    background: var(--color-bg);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    overflow-x: auto;
    max-height: 220px;
    overflow-y: auto;
    white-space: pre;
    margin-top: var(--space-2);
  }
</style>
