<script lang="ts">
  import { apiPost, ApiError } from '$lib/api';
  import type { ServiceStatus } from '$lib/protocol';

  interface Props {
    service: ServiceStatus;
    isAdmin: boolean;
    journalLines: string[];
    onAction?: (action: 'start' | 'stop' | 'restart') => void;
  }
  let { service, isAdmin, journalLines, onAction }: Props = $props();

  let busy = $state(false);
  let lastError = $state<string | null>(null);

  const STATUS_TO_CHIP: Record<string, string> = {
    active: 'ok',
    activating: 'warn',
    inactive: 'idle',
    failed: 'err',
    timeout: 'err',
    unknown: 'idle',
  };

  function chipClass(s: string): string {
    return STATUS_TO_CHIP[s] ?? 'idle';
  }

  async function action(act: 'start' | 'stop' | 'restart'): Promise<void> {
    if (!isAdmin || busy) return;
    busy = true;
    lastError = null;
    try {
      await apiPost(`/api/local/service/${service.name}/${act}`);
      onAction?.(act);
    } catch (e) {
      const err = e as ApiError;
      lastError = err.body?.err ?? err.message;
    } finally {
      busy = false;
    }
  }
</script>

<div class="card" data-testid="service-card-{service.name}">
  <div class="hstack" style="justify-content: space-between;">
    <div class="hstack">
      <strong>{service.name}</strong>
      <span class="chip {chipClass(service.active)}" data-testid="service-status">
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
    <div class="muted" style="color: var(--color-status-err); margin-top: 8px;">
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
