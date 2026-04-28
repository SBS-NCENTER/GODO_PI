<script lang="ts">
  import { LOCAL_HOSTNAMES } from '$lib/constants';
  import { navigate, route } from '$lib/router';

  let currentPath = $state('/');
  $effect(() => {
    const unsub = route.subscribe((p) => (currentPath = p));
    return unsub;
  });

  const isLocalHost =
    typeof window !== 'undefined' && LOCAL_HOSTNAMES.includes(window.location.hostname);

  type NavItem = { path: string; label: string };
  const items: NavItem[] = [
    { path: '/', label: 'Dashboard' },
    { path: '/map', label: 'Map' },
    { path: '/diag', label: 'Diagnostics' },
  ];

  function go(p: string): void {
    navigate(p);
  }
</script>

<nav class="sidebar app-sidebar" data-testid="sidebar">
  <ul>
    {#each items as it (it.path)}
      <li>
        <button
          class="nav-link"
          class:active={currentPath === it.path}
          onclick={() => go(it.path)}
          data-testid="nav-{it.label.toLowerCase()}"
        >
          {it.label}
        </button>
      </li>
    {/each}
    {#if isLocalHost}
      <li>
        <button
          class="nav-link"
          class:active={currentPath === '/local'}
          onclick={() => go('/local')}
          data-testid="nav-local"
        >
          Local
        </button>
      </li>
    {/if}
  </ul>
</nav>

<style>
  .sidebar {
    width: 200px;
    background: var(--color-bg-elev);
    border-right: 1px solid var(--color-border);
    padding: var(--space-3) 0;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  li {
    padding: 0;
  }
  .nav-link {
    display: block;
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: var(--space-2) var(--space-4);
    color: var(--color-text);
    cursor: pointer;
  }
  .nav-link:hover {
    background: var(--color-bg-hover);
  }
  .nav-link.active {
    background: color-mix(in srgb, var(--color-accent) 15%, transparent);
    color: var(--color-accent);
    font-weight: 500;
    border-left: 3px solid var(--color-accent);
    padding-left: calc(var(--space-4) - 3px);
  }
</style>
