import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount, flushSync, unmount } from 'svelte';

import JournalTail from '../../src/components/JournalTail.svelte';

let target: HTMLDivElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  document.body.removeChild(target);
  vi.restoreAllMocks();
});

describe('JournalTail', () => {
  it('renders the three-entry allow-list dropdown', () => {
    const cmp = mount(JournalTail, { target });
    flushSync();
    const select = target.querySelector('select[data-testid="journal-unit"]') as HTMLSelectElement;
    const opts = Array.from(select.options).map((o) => o.value);
    expect(opts).toEqual(['godo-tracker', 'godo-webctl', 'godo-irq-pin']);
    unmount(cmp);
  });

  it('disables the refresh button while loading', async () => {
    const { _resetJournalTailForTests, journalTail } = await import('../../src/stores/journalTail');
    _resetJournalTailForTests();
    const cmp = mount(JournalTail, { target });
    flushSync();
    journalTail.update((s) => ({ ...s, loading: true }));
    flushSync();
    const btn = target.querySelector('button[data-testid="journal-refresh"]') as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
    unmount(cmp);
    _resetJournalTailForTests();
  });

  it('renders the empty-state placeholder before any fetch', async () => {
    const { _resetJournalTailForTests } = await import('../../src/stores/journalTail');
    _resetJournalTailForTests();
    const cmp = mount(JournalTail, { target });
    flushSync();
    expect(target.querySelector('[data-testid="journal-empty"]')).toBeTruthy();
    unmount(cmp);
  });

  it('renders the error state when the store carries an error', async () => {
    const { _resetJournalTailForTests, journalTail } = await import('../../src/stores/journalTail');
    _resetJournalTailForTests();
    const cmp = mount(JournalTail, { target });
    flushSync();
    journalTail.update((s) => ({ ...s, error: 'http_500' }));
    flushSync();
    const err = target.querySelector('[data-testid="journal-error"]');
    expect(err?.textContent).toContain('http_500');
    unmount(cmp);
    _resetJournalTailForTests();
  });
});
