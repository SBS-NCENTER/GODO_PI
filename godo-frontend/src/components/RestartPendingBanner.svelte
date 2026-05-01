<script lang="ts">
  /**
   * Track B-CONFIG (PR-CONFIG-β) — "godo-tracker restart needed" banner.
   *
   * Mode-A S5 fold: differentiates two states by joining
   * `restart_pending` ∧ `health.tracker`:
   *   - tracker ok + flag set → "godo-tracker 재시작 필요"
   *   - tracker unreachable + flag set → "godo-tracker 시작 실패 — journalctl 확인"
   *   - flag not set → render nothing (component returns no DOM).
   *
   * The banner is non-dismissable; only a tracker boot via B-LOCAL
   * "Restart godo-tracker" clears the underlying file flag.
   */

  import { onDestroy, onMount } from 'svelte';
  import { subscribeRestartPending } from '$stores/restartPending';

  let pending = $state(false);
  let trackerOk = $state(true);
  let unsub: (() => void) | null = null;

  // issue#8 — subscribe via subscribeRestartPending so the first mount
  // also starts the 1 Hz polling backstop. Without polling, the banner
  // sticks after a service-restart action because the post-action
  // refresh fires before tracker boot clears the sentinel.
  onMount(() => {
    unsub = subscribeRestartPending((s) => {
      pending = s.pending;
      trackerOk = s.trackerOk;
    });
  });

  onDestroy(() => {
    unsub?.();
  });
</script>

{#if pending}
  <div class="banner" data-testid="restart-pending-banner">
    {#if trackerOk}
      <span class="icon" aria-hidden="true">!</span>
      <span class="text"
        >godo-tracker 재시작 필요 — B-LOCAL에서 "Restart godo-tracker" 버튼 클릭</span
      >
    {:else}
      <span class="icon" aria-hidden="true">!</span>
      <span class="text">godo-tracker 시작 실패 — journalctl 확인</span>
    {/if}
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: color-mix(in srgb, var(--color-error, #c62828) 12%, var(--color-bg));
    border-left: 3px solid var(--color-error, #c62828);
    color: var(--color-text);
    font-size: 0.95em;
  }
  .icon {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.25em;
    height: 1.25em;
    border-radius: 999px;
    background: var(--color-error, #c62828);
    color: white;
    font-weight: 700;
    font-size: 0.8em;
    padding: 0 0.45em;
  }
  .text {
    flex: 1;
  }
</style>
