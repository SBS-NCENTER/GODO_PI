<script lang="ts">
  import { onMount } from 'svelte';
  import { ApiError } from '$lib/api';
  import { login } from '$lib/auth';
  import { navigate } from '$lib/router';
  import { auth, setSession } from '$stores/auth';

  let username = $state('');
  let password = $state('');
  let error = $state<string | null>(null);
  let busy = $state(false);

  // If already logged in, bounce to /.
  onMount(() => {
    const unsub = auth.subscribe((s) => {
      if (s) navigate('/');
    });
    unsub();
  });

  async function onSubmit(e: SubmitEvent): Promise<void> {
    e.preventDefault();
    if (busy) return;
    busy = true;
    error = null;
    try {
      const resp = await login(username, password);
      setSession(resp.token, resp.username, resp.role, resp.exp);
      navigate('/');
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 401) error = '아이디 또는 비밀번호가 올바르지 않습니다.';
      else if (err.status === 503)
        error = '인증 서비스를 사용할 수 없습니다. 관리자에게 문의하세요.';
      else error = err.body?.err ?? `로그인 실패 (${err.status})`;
    } finally {
      busy = false;
    }
  }
</script>

<div class="login-page" data-testid="login-page">
  <form class="card login-card" onsubmit={onSubmit}>
    <h2>GODO 로그인</h2>
    <div class="vstack">
      <label>
        <span class="muted">사용자명</span>
        <input
          type="text"
          bind:value={username}
          required
          autocomplete="username"
          data-testid="login-username"
        />
      </label>
      <label>
        <span class="muted">비밀번호</span>
        <input
          type="password"
          bind:value={password}
          required
          autocomplete="current-password"
          data-testid="login-password"
        />
      </label>
      {#if error}
        <div class="error" data-testid="login-error">{error}</div>
      {/if}
      <button type="submit" class="primary" disabled={busy} data-testid="login-submit">
        {busy ? '로그인 중...' : '로그인'}
      </button>
    </div>
  </form>
</div>

<style>
  .login-page {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 80vh;
  }
  .login-card {
    min-width: 320px;
    max-width: 400px;
    width: 100%;
  }
  h2 {
    margin: 0 0 var(--space-4) 0;
    text-align: center;
  }
  label {
    display: block;
  }
  label span {
    display: block;
    margin-bottom: var(--space-1);
  }
  .error {
    color: var(--color-status-err);
    background: color-mix(in srgb, var(--color-status-err) 10%, transparent);
    padding: var(--space-2);
    border-radius: var(--radius-sm);
    border: 1px solid var(--color-status-err);
    font-size: var(--font-size-sm);
  }
</style>
