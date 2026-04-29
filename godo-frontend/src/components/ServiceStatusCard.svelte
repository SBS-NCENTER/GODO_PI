<script lang="ts">
  /**
   * Track B-SYSTEM PR-2 — read-only-or-admin twin of `ServiceCard.svelte`.
   *
   * Read surface:
   *   - service.name (header)
   *   - ActiveState chip (chip-class via `$lib/serviceStatus`)
   *   - SubState in parens
   *   - Korean uptime (`formatUptimeKo`) + PID + memory (`formatBytesBinaryShort`)
   *   - Collapsible env-vars (redacted KEYS render with `(secret)` tag)
   *
   * Admin surface (gated by `$isAdmin`):
   *   - Start / Stop / Restart buttons → POST /api/system/service/<name>/<action>
   *   - 409 service_starting/stopping toast renders body.detail (Korean)
   *     with auto-dismiss after `SERVICE_TRANSITION_TOAST_TTL_MS`.
   *
   * `ServiceCard.svelte` (loopback-admin, kiosk path) stays the place
   * to act on /local. This component is the /system twin — admin-non-
   * loopback (any LAN/Tailscale operator with admin role).
   */

  import { onDestroy } from 'svelte';
  import EnvVarsList from '$components/EnvVarsList.svelte';
  import { ApiError, apiPost } from '$lib/api';
  import { SERVICE_TRANSITION_TOAST_TTL_MS } from '$lib/constants';
  import { formatBytesBinaryShort, formatUptimeKo } from '$lib/format';
  import {
    ERR_SERVICE_STARTING,
    ERR_SERVICE_STOPPING,
    apiSystemServiceAction,
    type SystemServiceEntry,
  } from '$lib/protocol';
  import { statusChipClass } from '$lib/serviceStatus';

  interface Props {
    service: SystemServiceEntry;
    isAdmin: boolean;
    nowUnix: number; // Date.now()/1000 from the parent; exposed as a prop
    // so unit tests can freeze "now" without monkeypatching Date.
    onAction?: (action: 'start' | 'stop' | 'restart') => void;
  }
  let { service, isAdmin, nowUnix, onAction }: Props = $props();

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
      await apiPost(apiSystemServiceAction(service.name, act));
      onAction?.(act);
    } catch (e) {
      const err = e as ApiError;
      const errCode = err.body?.err;
      if (errCode === ERR_SERVICE_STARTING || errCode === ERR_SERVICE_STOPPING) {
        // 409 transition gate — render the Korean detail with auto-dismiss.
        setErrorWithAutoDismiss(err.body?.detail ?? errCode);
      } else {
        // All other errors auto-dismiss too. Cases like:
        //   - `subprocess_failed` from a webctl self-restart (webctl
        //     terminates mid-response so the systemctl call returns
        //     non-zero before the new process can answer)
        //   - `request_aborted` / network errors when the operator
        //     restarts a service whose initialization (mlock + map
        //     load + AMCL kernel rebuild for the tracker) outlasts
        //     the SPA fetch timeout
        // The next /api/system/services poll already shows the new
        // active state, so a sticky red banner is misleading. Auto-
        // dismiss matches the 409 path's UX.
        setErrorWithAutoDismiss(err.body?.err ?? err.message);
      }
    } finally {
      busy = false;
    }
  }

  // Belt-and-suspenders: when the next polling tick reports the
  // service active AND the SPA is no longer mid-action, clear any
  // residual error banner. This handles the edge case where the
  // user navigates back to the page after the auto-dismiss timer
  // already fired in another tab — Svelte 5 timers are per-component.
  $effect(() => {
    if (!busy && lastError !== null && service.active_state === 'active') {
      lastError = null;
      clearDismissTimer();
    }
  });
</script>

<div class="card svc-card" data-testid={`service-status-card-${service.name}`}>
  <div class="hstack" style="justify-content: space-between;">
    <div class="hstack">
      <strong>{service.name}</strong>
      <span
        class="chip {statusChipClass(service.active_state)}"
        data-testid={`svc-status-${service.name}`}
      >
        {service.active_state}
      </span>
      {#if service.sub_state}
        <span class="muted sub-state">({service.sub_state})</span>
      {/if}
    </div>
    {#if isAdmin}
      <div class="hstack">
        <button
          disabled={busy}
          onclick={() => action('start')}
          data-testid={`svc-action-start-${service.name}`}>Start</button
        >
        <button
          disabled={busy}
          onclick={() => action('stop')}
          data-testid={`svc-action-stop-${service.name}`}>Stop</button
        >
        <button
          disabled={busy}
          onclick={() => action('restart')}
          data-testid={`svc-action-restart-${service.name}`}>Restart</button
        >
      </div>
    {/if}
  </div>

  <div class="kv-grid" style="margin-top: 8px;">
    <span>uptime</span>
    <span data-testid={`svc-uptime-${service.name}`}
      >{formatUptimeKo(service.active_since_unix, nowUnix)}</span
    >
    <span>pid</span>
    <span data-testid={`svc-pid-${service.name}`}>{service.main_pid ?? '—'}</span>
    <span>memory</span>
    <span data-testid={`svc-memory-${service.name}`}
      >{formatBytesBinaryShort(service.memory_bytes)}</span
    >
  </div>

  {#if lastError}
    <div
      class="muted"
      style="color: var(--color-status-err); margin-top: 8px;"
      data-testid={`svc-error-${service.name}`}
      role="status"
    >
      {lastError}
    </div>
  {/if}

  <EnvVarsList env={service.env_redacted} stale={service.env_stale} />
</div>

<style>
  .svc-card {
    padding: 12px;
  }
  .sub-state {
    font-size: var(--font-size-sm);
  }
  .kv-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
</style>
