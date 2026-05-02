<script lang="ts">
  import MappingBanner from '$components/MappingBanner.svelte';
  import RestartPendingBanner from '$components/RestartPendingBanner.svelte';
  import Sidebar from '$components/Sidebar.svelte';
  import TopBar from '$components/TopBar.svelte';
  import { matchRoute, navigate, route } from '$lib/router';
  import { auth } from '$stores/auth';
  import { subscribeMode, trackerOk } from '$stores/mode';
  // Side-effect import: theme store wires the document attribute on init.
  import '$stores/theme';
  import { notFoundComponent, routes } from './routes';

  let currentPath = $state('/');
  $effect(() => {
    const unsub = route.subscribe((p) => (currentPath = p));
    return unsub;
  });

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });

  // Health polling subscription: always-on (Track F) so anonymous viewers
  // also see the tracker-unreachable banner on every page. Backend health
  // endpoint is anon-readable; nothing requires a session here.
  let trackerOnline = $state(true);
  $effect(() => {
    const unsubMode = subscribeMode(() => {});
    const unsubOk = trackerOk.subscribe((v) => (trackerOnline = v));
    return () => {
      unsubOk();
      unsubMode();
    };
  });

  // Track F: no auth gate on routing. Anonymous viewers can browse every
  // page (read endpoints are anon-readable, mutations 401 cleanly and the
  // SPA disables their buttons). The only navigation rule is: a logged-in
  // user landing on /login gets bounced to / so they don't see the form.
  $effect(() => {
    if (session && currentPath === '/login') {
      navigate('/');
    }
  });

  let Component = $derived(matchRoute(currentPath, routes) ?? notFoundComponent);
  let onLoginPage = $derived(currentPath === '/login');
</script>

{#if onLoginPage}
  <main style="padding: 16px;">
    <Component />
  </main>
{:else}
  <div class="app-shell">
    <TopBar />
    <Sidebar />
    <main class="app-main">
      {#if !trackerOnline}
        <div class="tracker-banner" data-testid="tracker-banner" role="status">
          godo-tracker가 응답하지 않습니다. <code>systemctl status godo-tracker</code>를
          확인해주세요.
        </div>
      {/if}
      <MappingBanner />
      <RestartPendingBanner />
      <Component />
    </main>
  </div>
{/if}

<style>
  .tracker-banner {
    margin: 0 0 16px;
    padding: 8px 12px;
    border-radius: var(--radius-sm);
    background: var(--color-warning-bg);
    color: var(--color-warning-fg);
    border: 1px solid var(--color-warning-border);
    font-size: 14px;
  }
  .tracker-banner code {
    background: rgba(0, 0, 0, 0.08);
    padding: 0 4px;
    border-radius: 2px;
  }
</style>
