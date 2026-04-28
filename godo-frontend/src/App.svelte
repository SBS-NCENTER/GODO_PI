<script lang="ts">
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

  // Health polling subscription: kept alive for the duration of an authed
  // session so the tracker-unreachable banner reflects current state on
  // every page (not just DASH). Tears down on logout.
  let trackerOnline = $state(true);
  $effect(() => {
    if (!session) {
      trackerOnline = true; // suppress banner on /login
      return;
    }
    const unsubMode = subscribeMode(() => {});
    const unsubOk = trackerOk.subscribe((v) => (trackerOnline = v));
    return () => {
      unsubOk();
      unsubMode();
    };
  });

  // Auth gate: anything other than /login requires a session. We do this
  // with a pure side-effect — render <Login/> if not authed, regardless
  // of the URL hash, except when the hash is /login itself.
  $effect(() => {
    if (!session && currentPath !== '/login') {
      navigate('/login');
    }
  });

  let Component = $derived(matchRoute(currentPath, routes) ?? notFoundComponent);
  let onLoginPage = $derived(currentPath === '/login');
</script>

{#if onLoginPage || !session}
  <main style="padding: 16px;">
    {#if !session}
      {@const Login = routes['/login']}
      <Login />
    {:else}
      <Component />
    {/if}
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
