<script lang="ts">
  /**
   * Track B-CONFIG (PR-CONFIG-β) — Config editor page.
   *
   * Anonymous viewers see the table with disabled inputs (Track F).
   * Admin operators see enabled inputs that PATCH on blur / Enter.
   * The page is wired into Sidebar (admin-only nav row).
   */

  // RestartPendingBanner is rendered globally in App.svelte; do not
  // double-render here (Mode-A S5 banner is already at app root).
  import ConfigEditor from '$components/ConfigEditor.svelte';
  import { onDestroy, onMount } from 'svelte';
  import { auth } from '$stores/auth';
  import { ROLE_ADMIN } from '$lib/protocol';

  let isAdmin = $state(false);
  let unsub: (() => void) | null = null;

  onMount(() => {
    unsub = auth.subscribe((s) => {
      isAdmin = s !== null && s.role === ROLE_ADMIN;
    });
  });

  onDestroy(() => {
    unsub?.();
  });
</script>

<section class="config-page" data-testid="config-page">
  <header>
    <h1>Configuration</h1>
    <p class="hint">
      Tier-2 키 (~37). 즉시 반영(✓), 재시작 필요(!), 재시작+재캘리브레이션 필요(!!) 가 각 행에
      표시됩니다.
    </p>
  </header>

  <ConfigEditor admin={isAdmin} />
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
  .hint {
    margin: 0 0 var(--space-3) 0;
    color: var(--color-text-muted);
  }
</style>
