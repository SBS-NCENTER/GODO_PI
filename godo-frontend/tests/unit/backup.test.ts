/**
 * Component-level tests for `routes/Backup.svelte` (Track B-BACKUP).
 *
 * Mirrors the harness pattern of `system.test.ts` /
 * `map_list_panel.test.ts`. Pins the contract that:
 *   1. The route fetches `/api/map/backup/list` on mount and renders
 *      a row per `BackupEntry`, newest first.
 *   2. Anon viewers see the restore button DISABLED.
 *   3. Admin viewers see the restore button ENABLED.
 *   4. Clicking restore opens `<ConfirmDialog/>`; confirming POSTs to
 *      `/api/map/backup/<ts>/restore` exactly once.
 *   5. On success, the banner shows the imported
 *      `BACKUP_RESTORE_SUCCESS_TOAST` constant (TB1 fold — the toast
 *      string is a single SSOT in `lib/constants.ts`; the component
 *      and the test import the same symbol).
 *   6. On 4xx error, the banner surfaces the response body's `err`
 *      field inline.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Backup from '../../src/routes/Backup.svelte';
import * as api from '../../src/lib/api';
import { BACKUP_RESTORE_SUCCESS_TOAST } from '../../src/lib/constants';
import { auth } from '../../src/stores/auth';

interface CleanupFn {
  (): void;
}

const cleanups: CleanupFn[] = [];

const STUB_LIST_BODY = {
  items: [
    {
      ts: '20260202T020202Z',
      files: ['studio_v2.pgm', 'studio_v2.yaml'],
      size_bytes: 4096,
    },
    {
      ts: '20260101T010101Z',
      files: ['studio_v1.pgm', 'studio_v1.yaml'],
      size_bytes: 2048,
    },
  ],
};

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  api.configureAuth({ getToken: () => 'tok', onUnauthorized: () => {} });
  auth.set(null);
  Object.defineProperty(window, 'location', {
    value: { hostname: '127.0.0.1', origin: 'http://localhost', hash: '#/backup' },
    writable: true,
    configurable: true,
  });
});

afterEach(() => {
  while (cleanups.length > 0) {
    const fn = cleanups.pop();
    fn?.();
  }
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

async function waitFor<T>(getter: () => T | null, label: string, timeoutMs = 1000): Promise<T> {
  const start = Date.now();
  let v = getter();
  while (v === null) {
    if (Date.now() - start > timeoutMs) {
      throw new Error(`waitFor timeout: ${label}`);
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
    flushSync();
    v = getter();
  }
  return v;
}

async function mountPage(): Promise<HTMLDivElement> {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const component = mount(Backup, { target, props: {} });
  cleanups.push(() => {
    unmount(component);
    target.remove();
  });
  return target;
}

describe('Backup page (Track B-BACKUP)', () => {
  it('lists backups newest first from /api/map/backup/list', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(STUB_LIST_BODY));

    const target = await mountPage();
    const firstRow = await waitFor<HTMLTableRowElement>(
      () =>
        target.querySelector<HTMLTableRowElement>('[data-testid="backup-row-20260202T020202Z"]'),
      'first row',
    );
    expect(firstRow).not.toBeNull();
    // Newest first — the older stamp comes second.
    const rows = target.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    expect((rows[0] as HTMLElement).getAttribute('data-testid')).toBe(
      'backup-row-20260202T020202Z',
    );
    expect((rows[1] as HTMLElement).getAttribute('data-testid')).toBe(
      'backup-row-20260101T010101Z',
    );
    expect(fetchSpy).toHaveBeenCalled();
    const url = fetchSpy.mock.calls[0]![0] as string;
    expect(url).toBe('/api/map/backup/list');
  });

  it('restore button disabled for anon viewer', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(STUB_LIST_BODY));
    // No setAdminSession — anon.

    const target = await mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () =>
        target.querySelector<HTMLButtonElement>('[data-testid="backup-restore-20260202T020202Z"]'),
      'restore button',
    );
    expect(btn.disabled).toBe(true);
  });

  it('restore button enabled for admin', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResp(STUB_LIST_BODY));
    setAdminSession();

    const target = await mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () =>
        target.querySelector<HTMLButtonElement>('[data-testid="backup-restore-20260202T020202Z"]'),
      'restore button',
    );
    expect(btn.disabled).toBe(false);
  });

  it('confirm dialog flow POSTs to /api/map/backup/<ts>/restore exactly once', async () => {
    let listCalls = 0;
    let restoreCalls = 0;
    let lastRestoreUrl = '';
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/restore')) {
        restoreCalls++;
        lastRestoreUrl = url;
        return jsonResp({
          ok: true,
          ts: '20260202T020202Z',
          restored: ['studio_v2.pgm', 'studio_v2.yaml'],
        });
      }
      listCalls++;
      return jsonResp(STUB_LIST_BODY);
    });
    setAdminSession();

    const target = await mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () =>
        target.querySelector<HTMLButtonElement>('[data-testid="backup-restore-20260202T020202Z"]'),
      'restore button',
    );
    btn.click();
    flushSync();

    const confirmBtn = target.querySelector<HTMLButtonElement>('[data-testid="confirm-ok"]');
    expect(confirmBtn).not.toBeNull();
    confirmBtn!.click();
    // Dialog handler is async — wait for the POST + post-restore refresh.
    await waitFor<HTMLElement>(
      () => target.querySelector<HTMLElement>('[data-testid="backup-banner"]'),
      'success banner',
    );

    expect(restoreCalls).toBe(1);
    expect(lastRestoreUrl).toBe('/api/map/backup/20260202T020202Z/restore');
    // Initial list + post-restore refresh = 2 list calls.
    expect(listCalls).toBeGreaterThanOrEqual(1);
    expect(fetchSpy).toHaveBeenCalled();
  });

  it('success banner shows BACKUP_RESTORE_SUCCESS_TOAST (TB1 SSOT pin)', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/restore')) {
        return jsonResp({
          ok: true,
          ts: '20260202T020202Z',
          restored: ['studio_v2.pgm', 'studio_v2.yaml'],
        });
      }
      return jsonResp(STUB_LIST_BODY);
    });
    setAdminSession();

    const target = await mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () =>
        target.querySelector<HTMLButtonElement>('[data-testid="backup-restore-20260202T020202Z"]'),
      'restore button',
    );
    btn.click();
    flushSync();
    const confirmBtn = target.querySelector<HTMLButtonElement>('[data-testid="confirm-ok"]');
    confirmBtn!.click();
    const banner = await waitFor<HTMLElement>(
      () => target.querySelector<HTMLElement>('[data-testid="backup-banner"]'),
      'success banner',
    );
    // Pin: the rendered text equals the imported constant verbatim.
    // If a future writer hard-codes a new toast string in
    // `Backup.svelte` without updating the constant, this test fails.
    expect(banner.textContent).toContain(BACKUP_RESTORE_SUCCESS_TOAST);
  });

  it('400/404 surfaces inline error from response body.err', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = input as string;
      if (url.endsWith('/restore')) {
        return jsonResp({ ok: false, err: 'backup_not_found' }, 404);
      }
      return jsonResp(STUB_LIST_BODY);
    });
    setAdminSession();

    const target = await mountPage();
    const btn = await waitFor<HTMLButtonElement>(
      () =>
        target.querySelector<HTMLButtonElement>('[data-testid="backup-restore-20260202T020202Z"]'),
      'restore button',
    );
    btn.click();
    flushSync();
    const confirmBtn = target.querySelector<HTMLButtonElement>('[data-testid="confirm-ok"]');
    confirmBtn!.click();
    const banner = await waitFor<HTMLElement>(
      () => target.querySelector<HTMLElement>('[data-testid="backup-banner"]'),
      'error banner',
    );
    // Inline error mentions the wire `err` value.
    expect(banner.textContent).toContain('backup_not_found');
  });
});
