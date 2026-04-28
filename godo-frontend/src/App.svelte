<script lang="ts">
  import Sidebar from '$components/Sidebar.svelte';
  import TopBar from '$components/TopBar.svelte';
  import { matchRoute, navigate, route } from '$lib/router';
  import { auth } from '$stores/auth';
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
      <Component />
    </main>
  </div>
{/if}
