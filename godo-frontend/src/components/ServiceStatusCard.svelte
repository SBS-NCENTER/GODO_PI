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
  import { refreshMode } from '$stores/mode';
  import { refresh as refreshRestartPending } from '$stores/restartPending';

  interface Props {
    service: SystemServiceEntry;
    isAdmin: boolean;
    nowUnix: number; // Date.now()/1000 from the parent; exposed as a prop
    // so unit tests can freeze "now" without monkeypatching Date.
    onAction?: (action: 'start' | 'stop' | 'restart') => void;
    /**
     * Optional UI-layer override that disables the action buttons even
     * when the operator is admin. Used by the System tab for
     * `godo-mapping@active`: the polkit rule grants the verb (so
     * `curl POST /api/system/service/godo-mapping@active/stop` still
     * works), but the System tab UI hides the buttons behind a tooltip
     * so the operator goes through the Map > Mapping tab instead.
     * issue#14 Patch C2.
     */
    actionsDisabled?: boolean;
    actionsDisabledTooltip?: string;
  }
  let {
    service,
    isAdmin,
    nowUnix,
    onAction,
    actionsDisabled = false,
    actionsDisabledTooltip = '',
  }: Props = $props();

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
      // godo-tracker boots clear the restart-pending sentinel; refresh
      // the SPA store so the banner clears without a page reload.
      // No-op for non-tracker services.
      void refreshRestartPending();
      // issue#9 — also refresh mode.ts so the App.svelte tracker-down
      // banner reflects the new state within HTTP RTT instead of
      // waiting up to 1 s for the next polling tick.
      void refreshMode();
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
      <div class="hstack" title={actionsDisabled ? actionsDisabledTooltip : ''}>
        <button
          disabled={busy || actionsDisabled}
          onclick={() => action('start')}
          data-testid={`svc-action-start-${service.name}`}>Start</button
        >
        <button
          disabled={busy || actionsDisabled}
          onclick={() => action('stop')}
          data-testid={`svc-action-stop-${service.name}`}>Stop</button
        >
        <button
          disabled={busy || actionsDisabled}
          onclick={() => action('restart')}
          data-testid={`svc-action-restart-${service.name}`}>Restart</button
        >
      </div>
    {/if}
  </div>
  {#if actionsDisabled && actionsDisabledTooltip && isAdmin}
    <div
      class="muted actions-disabled-hint"
      data-testid={`svc-actions-disabled-hint-${service.name}`}
    >
      {actionsDisabledTooltip}
    </div>
  {/if}

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
  /* issue#14 Patch C2 — explanatory hint shown next to disabled action
     row (e.g. godo-mapping@active card directs operator to Map > Mapping). */
  .actions-disabled-hint {
    font-size: var(--font-size-sm);
    margin-top: var(--space-2);
  }
  .kv-grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
  }
</style>
