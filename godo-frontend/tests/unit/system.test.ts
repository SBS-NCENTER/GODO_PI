/**
 * Component-level tests for `routes/System.svelte` (PR-SYSTEM, Track B-SYSTEM).
 *
 * Six cases pin the page contract:
 *   1. Renders four panels and registers exactly one diag subscriber on
 *      mount; subscriber count drops back to 0 on unmount (N3 fold —
 *      catches a regression that leaks the SSE refcount).
 *   2. Sparkline label is derived from `DIAG_SPARKLINE_DEPTH × SSE_TICK_MS`
 *      (T1 fold) — pins the math, not the prose, so a future depth bump
 *      doesn't silently break this test.
 *   3. Anon viewer sees disabled reboot/shutdown buttons + the verbatim
 *      anon-hint string from `routes/Local.svelte:169` (M2 fold —
 *      eliminates copy drift).
 *   4. Admin viewer sees enabled buttons (anti-tautology partner of (3)).
 *   5. Reboot click opens ConfirmDialog; cancel does NOT call apiPost.
 *   6. Reboot confirm-confirm calls `apiPost('/api/system/reboot')`
 *      exactly once and not `/shutdown` (M3 fold — anti-typo pin).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import System from '../../src/routes/System.svelte';
import { DIAG_SPARKLINE_DEPTH, SSE_TICK_MS } from '../../src/lib/constants';
import * as api from '../../src/lib/api';
import { auth } from '../../src/stores/auth';
import { _getSubscriberCountForTests, _resetDiagForTests } from '../../src/stores/diag';
import { _resetJournalTailForTests } from '../../src/stores/journalTail';
import { _resetSystemServicesForTests, systemServices } from '../../src/stores/systemServices';

let target: HTMLDivElement;

beforeEach(() => {
  // Provide an EventSource stub so subscribeDiag → startSSE doesn't throw.
  class MockEventSource {
    url: string;
    readyState = 0;
    onmessage: ((ev: MessageEvent<string>) => void) | null = null;
    onerror: ((ev: Event) => void) | null = null;
    closed = false;
    constructor(url: string) {
      this.url = url;
    }
    close(): void {
      this.closed = true;
      this.readyState = 2;
    }
  }
  // @ts-expect-error — global override for tests
  globalThis.EventSource = MockEventSource;

  // Wire the api layer to a known token so the SSE token gate passes.
  api.configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });

  // Stub fetch so the systemServices store's poll resolves quickly with
  // a known payload — keeps these tests focused on the System.svelte
  // wiring (subscriber refcount, button states, anon hint, etc.).
  globalThis.fetch = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        services: [
          {
            name: 'godo-tracker',
            active_state: 'active',
            sub_state: 'running',
            main_pid: 1234,
            active_since_unix: 0,
            memory_bytes: 0,
            env_redacted: { GODO_LOG_DIR: '/var/log/godo', JWT_SECRET: '<redacted>' },
            env_stale: false,
          },
        ],
      }),
      { status: 200, headers: { 'Content-Type': 'application/json' } },
    ),
  ) as unknown as typeof globalThis.fetch;

  target = document.createElement('div');
  document.body.appendChild(target);
  _resetDiagForTests();
  _resetJournalTailForTests();
  _resetSystemServicesForTests();
  auth.set(null);
});

afterEach(() => {
  document.body.removeChild(target);
  _resetDiagForTests();
  _resetJournalTailForTests();
  _resetSystemServicesForTests();
  auth.set(null);
  vi.restoreAllMocks();
});

function setAdminSession(): void {
  auth.set({
    token: 'tok',
    username: 'ncenter',
    role: 'admin',
    exp: Math.floor(Date.now() / 1000) + 3600,
  });
}

function seedServicesStore(): void {
  // Bypass the polling fetch and inject a known payload directly into
  // the store; the System.svelte component subscribes via
  // `subscribeSystemServices` which subscribes to `systemServices.set(...)`
  // directly, so this is sufficient for component-render assertions.
  systemServices.set({
    services: [
      {
        name: 'godo-tracker',
        active_state: 'active',
        sub_state: 'running',
        main_pid: 1234,
        active_since_unix: 0,
        memory_bytes: 0,
        env_redacted: { GODO_LOG_DIR: '/var/log/godo', JWT_SECRET: '<redacted>' },
            env_stale: false,
      },
    ],
    _arrival_ms: Date.now(),
    err: null,
  });
}

describe('System page', () => {
  it('renders five panels (PR-2: +services), registers one diag subscriber on mount, and unsubs on unmount', () => {
    expect(_getSubscriberCountForTests()).toBe(0);

    const cmp = mount(System, { target, props: {} });
    flushSync();

    expect(target.querySelector('[data-testid="panel-cpu-temp"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="panel-resources"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="panel-services"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="panel-journal"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="panel-power"]')).not.toBeNull();
    expect(_getSubscriberCountForTests()).toBe(1);

    unmount(cmp);
    flushSync();
    // N3 fold: unmount must drop the subscriber back to 0 — pins the
    // unsubscribe closure call in onDestroy.
    expect(_getSubscriberCountForTests()).toBe(0);
  });

  it('sparkline label is derived from DIAG_SPARKLINE_DEPTH × SSE_TICK_MS', () => {
    const expectedSeconds = (DIAG_SPARKLINE_DEPTH * SSE_TICK_MS) / 1000;
    const expectedSubstring = `${expectedSeconds} s`;

    const cmp = mount(System, { target, props: {} });
    flushSync();

    const cpuPanel = target.querySelector('[data-testid="panel-cpu-temp"]') as HTMLElement;
    expect(cpuPanel).not.toBeNull();
    // The sparkline label lives inside the panel; `DiagSparkline` puts
    // it in `.sparkline-label`.
    const label = cpuPanel.querySelector('.sparkline-label') as HTMLElement;
    expect(label).not.toBeNull();
    expect(label.textContent).toContain(expectedSubstring);

    unmount(cmp);
  });

  it('anon viewer sees disabled reboot + shutdown buttons and the verbatim anon-hint', () => {
    auth.set(null);

    const cmp = mount(System, { target, props: {} });
    flushSync();

    const rebootBtn = target.querySelector('[data-testid="reboot-btn"]') as HTMLButtonElement;
    const shutdownBtn = target.querySelector('[data-testid="shutdown-btn"]') as HTMLButtonElement;
    expect(rebootBtn.disabled).toBe(true);
    expect(shutdownBtn.disabled).toBe(true);

    const hint = target.querySelector('[data-testid="anon-hint"]') as HTMLElement;
    expect(hint).not.toBeNull();
    // M2 fold: verbatim mirror of `routes/Local.svelte:169`. Whitespace is
    // trimmed because Svelte preserves the surrounding template indentation.
    expect(hint.textContent?.trim()).toBe('제어 동작은 로그인이 필요합니다.');

    unmount(cmp);
  });

  it('admin viewer sees enabled reboot + shutdown buttons (no anon-hint)', () => {
    setAdminSession();

    const cmp = mount(System, { target, props: {} });
    flushSync();

    const rebootBtn = target.querySelector('[data-testid="reboot-btn"]') as HTMLButtonElement;
    const shutdownBtn = target.querySelector('[data-testid="shutdown-btn"]') as HTMLButtonElement;
    expect(rebootBtn.disabled).toBe(false);
    expect(shutdownBtn.disabled).toBe(false);
    expect(target.querySelector('[data-testid="anon-hint"]')).toBeNull();

    unmount(cmp);
  });

  it('reboot click opens the confirm dialog; cancel does NOT call apiPost', () => {
    setAdminSession();
    const apiPostSpy = vi.spyOn(api, 'apiPost').mockResolvedValue(null);

    const cmp = mount(System, { target, props: {} });
    flushSync();

    expect(target.querySelector('[data-testid="confirm-dialog"]')).toBeNull();

    const rebootBtn = target.querySelector('[data-testid="reboot-btn"]') as HTMLButtonElement;
    rebootBtn.click();
    flushSync();

    expect(target.querySelector('[data-testid="confirm-dialog"]')).not.toBeNull();

    const cancelBtn = target.querySelector('[data-testid="confirm-cancel"]') as HTMLButtonElement;
    cancelBtn.click();
    flushSync();

    expect(target.querySelector('[data-testid="confirm-dialog"]')).toBeNull();
    expect(apiPostSpy).not.toHaveBeenCalled();

    unmount(cmp);
  });

  it("reboot confirm-confirm calls apiPost('/api/system/reboot') exactly once", async () => {
    setAdminSession();
    const apiPostSpy = vi.spyOn(api, 'apiPost').mockResolvedValue(null);

    const cmp = mount(System, { target, props: {} });
    flushSync();

    const rebootBtn = target.querySelector('[data-testid="reboot-btn"]') as HTMLButtonElement;
    rebootBtn.click();
    flushSync();

    const okBtn = target.querySelector('[data-testid="confirm-ok"]') as HTMLButtonElement;
    okBtn.click();
    // Allow the awaited apiPost promise inside the click handler to settle.
    await Promise.resolve();
    await Promise.resolve();
    flushSync();

    expect(apiPostSpy).toHaveBeenCalledTimes(1);
    expect(apiPostSpy).toHaveBeenCalledWith('/api/system/reboot');
    // M3 anti-typo pin: never the shutdown path.
    const calledPaths = apiPostSpy.mock.calls.map((c) => c[0]);
    expect(calledPaths).not.toContain('/api/system/shutdown');

    unmount(cmp);
  });

  // --- Track B-SYSTEM PR-2 — services panel + admin action wiring -------

  it('renders the services panel after the first poll (PR-2)', () => {
    seedServicesStore();
    const cmp = mount(System, { target, props: {} });
    flushSync();

    expect(target.querySelector('[data-testid="panel-services"]')).not.toBeNull();
    // Each card carries `data-testid="service-status-card-<name>"`.
    const card = target.querySelector('[data-testid="service-status-card-godo-tracker"]');
    expect(card).not.toBeNull();

    unmount(cmp);
  });

  it('renders redacted env entries with a (secret) label (PR-2)', () => {
    seedServicesStore();
    const cmp = mount(System, { target, props: {} });
    flushSync();

    // <details> is collapsed by default; querying the inner <li> still
    // finds it in the DOM tree.
    const secretTag = target.querySelector('[data-testid="env-secret-JWT_SECRET"]');
    expect(secretTag).not.toBeNull();
    expect(secretTag?.textContent).toContain('(secret)');

    unmount(cmp);
  });

  it('admin sees Start/Stop/Restart action buttons on each ServiceStatusCard (PR-2 §8)', () => {
    setAdminSession();
    seedServicesStore();
    const cmp = mount(System, { target, props: {} });
    flushSync();

    expect(target.querySelector('[data-testid="svc-action-start-godo-tracker"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="svc-action-stop-godo-tracker"]')).not.toBeNull();
    expect(target.querySelector('[data-testid="svc-action-restart-godo-tracker"]')).not.toBeNull();

    unmount(cmp);
  });

  it('anon viewer sees no action buttons on ServiceStatusCard (PR-2 §8)', () => {
    auth.set(null);
    seedServicesStore();
    const cmp = mount(System, { target, props: {} });
    flushSync();

    expect(target.querySelector('[data-testid="svc-action-start-godo-tracker"]')).toBeNull();
    expect(target.querySelector('[data-testid="svc-action-stop-godo-tracker"]')).toBeNull();
    expect(target.querySelector('[data-testid="svc-action-restart-godo-tracker"]')).toBeNull();

    unmount(cmp);
  });

  it('clicking restart posts to /api/system/service/<name>/restart with no body (PR-2 §8)', async () => {
    setAdminSession();
    seedServicesStore();
    const apiPostSpy = vi.spyOn(api, 'apiPost').mockResolvedValue(null);

    const cmp = mount(System, { target, props: {} });
    flushSync();

    const btn = target.querySelector(
      '[data-testid="svc-action-restart-godo-tracker"]',
    ) as HTMLButtonElement;
    expect(btn).not.toBeNull();
    btn.click();
    await Promise.resolve();
    await Promise.resolve();
    flushSync();

    expect(apiPostSpy).toHaveBeenCalledWith('/api/system/service/godo-tracker/restart');

    unmount(cmp);
  });
});
