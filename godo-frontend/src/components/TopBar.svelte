<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { logout } from '$lib/auth';
  import { COUNTDOWN_TICK_MS } from '$lib/constants';
  import { formatRemaining } from '$lib/format';
  import { navigate } from '$lib/router';
  import { auth, clearSession } from '$stores/auth';
  import { theme, toggleTheme } from '$stores/theme';

  let now = $state(Math.floor(Date.now() / 1000));
  let timer: ReturnType<typeof setInterval> | null = null;

  onMount(() => {
    timer = setInterval(() => {
      now = Math.floor(Date.now() / 1000);
    }, COUNTDOWN_TICK_MS);
  });

  onDestroy(() => {
    if (timer !== null) clearInterval(timer);
  });

  let session = $state($auth);
  $effect(() => {
    const unsub = auth.subscribe((v) => (session = v));
    return unsub;
  });

  let themeValue = $state($theme);
  $effect(() => {
    const unsub = theme.subscribe((v) => (themeValue = v));
    return unsub;
  });

  let remainingLabel = $derived(session ? formatRemaining(session.exp - now) : '');

  async function onLogout(): Promise<void> {
    await logout();
    clearSession();
    navigate('/login');
  }
</script>

<header class="topbar app-topbar">
  <div class="brand">
    <span class="logo">:D</span>
    <span class="title">GODO</span>
  </div>
  <div class="hstack">
    {#if session}
      <span class="muted" data-testid="session-info">
        Logged in as <strong>{session.username}</strong> · {remainingLabel} 후 만료
      </span>
    {/if}
    <button onclick={toggleTheme} title="Toggle theme" data-testid="theme-toggle">
      {themeValue === 'light' ? '🌙' : '☀️'}
    </button>
    {#if session}
      <button onclick={onLogout} data-testid="logout-btn">Logout</button>
    {/if}
  </div>
</header>

<style>
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: var(--space-2) var(--space-4);
    background: var(--color-bg-elev);
    border-bottom: 1px solid var(--color-border);
    height: 48px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .logo {
    font-family: var(--font-mono);
    font-weight: 700;
    color: var(--color-accent);
    font-size: var(--font-size-xl);
  }
  .title {
    font-weight: 600;
    color: var(--color-text);
  }
</style>
