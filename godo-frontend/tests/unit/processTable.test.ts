/**
 * Track B-SYSTEM PR-B — `<ProcessTable/>` component tests.
 *
 * Covers (Final fold S4 + Mode-A M3 + duplicate-banner pin):
 *   - default sort cpu_pct desc
 *   - text search filters by name OR cmdline
 *   - "GODO only" toggle hides general rows
 *   - duplicate-alert banner appears when snapshot.duplicate_alert
 *   - per-row dup styling
 *   - info popover renders the 3 documented bullet strings
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProcessTable from '../../src/components/ProcessTable.svelte';
import type { ProcessesSnapshot } from '../../src/lib/protocol';

let target: HTMLDivElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  document.body.removeChild(target);
});

function snapshot(): ProcessesSnapshot {
  return {
    processes: [
      {
        name: 'godo_tracker_rt',
        pid: 100,
        user: 'ncenter',
        state: 'S',
        cmdline: ['godo_tracker_rt', '--config', '/etc/godo/tracker.toml'],
        cpu_pct: 12.5,
        rss_mb: 60.0,
        etime_s: 120,
        category: 'managed',
        duplicate: false,
      },
      {
        name: 'bash',
        pid: 200,
        user: 'ncenter',
        state: 'S',
        cmdline: ['bash'],
        cpu_pct: 0.0,
        rss_mb: 4.0,
        etime_s: 3600,
        category: 'general',
        duplicate: false,
      },
      {
        name: 'godo_smoke',
        pid: 300,
        user: 'ncenter',
        state: 'R',
        cmdline: ['godo_smoke', '--ms', '300'],
        cpu_pct: 4.5,
        rss_mb: 2.0,
        etime_s: 30,
        category: 'godo',
        duplicate: false,
      },
    ],
    duplicate_alert: false,
    published_mono_ns: 1,
  };
}

describe('<ProcessTable/>', () => {
  it('renders all rows with default cpu_pct desc sort', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const rows = Array.from(target.querySelectorAll('tbody tr')) as HTMLTableRowElement[];
    expect(rows.length).toBe(3);
    // Default sort: 12.5 (godo_tracker_rt) > 4.5 (godo_smoke) > 0.0 (bash).
    expect(rows[0].dataset.testid).toBe('proc-row-100');
    expect(rows[1].dataset.testid).toBe('proc-row-300');
    expect(rows[2].dataset.testid).toBe('proc-row-200');
    unmount(cmp);
  });

  it('text search filters by name OR cmdline (case-insensitive)', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const search = target.querySelector('[data-testid="proc-search"]') as HTMLInputElement;
    search.value = 'TRACKER';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const rows = target.querySelectorAll('tbody tr');
    expect(rows.length).toBe(1);
    expect((rows[0] as HTMLTableRowElement).dataset.testid).toBe('proc-row-100');
    unmount(cmp);
  });

  it('text search matches cmdline tokens (not just name)', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const search = target.querySelector('[data-testid="proc-search"]') as HTMLInputElement;
    search.value = '/etc/godo';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const rows = target.querySelectorAll('tbody tr');
    expect(rows.length).toBe(1);
    unmount(cmp);
  });

  it('GODO-only toggle hides general rows', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const toggle = target.querySelector('[data-testid="proc-godo-only"]') as HTMLInputElement;
    toggle.checked = true;
    toggle.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    const rows = target.querySelectorAll('tbody tr');
    expect(rows.length).toBe(2);
    // bash (general) should be hidden.
    const ids = Array.from(rows).map((r) => (r as HTMLTableRowElement).dataset.testid);
    expect(ids).not.toContain('proc-row-200');
    unmount(cmp);
  });

  it('duplicate-alert banner renders when snapshot.duplicate_alert', () => {
    const snap = snapshot();
    snap.duplicate_alert = true;
    snap.processes[0].duplicate = true;
    const cmp = mount(ProcessTable, { target, props: { snapshot: snap } });
    flushSync();
    const banner = target.querySelector('[data-testid="proc-duplicate-banner"]');
    expect(banner).not.toBeNull();
    // The duplicate row carries the .dup class (CSS adds the
    // `border-left: var(--border-width-emphasis) ...` rule).
    const dupRow = target.querySelector('[data-testid="proc-row-100"]') as HTMLTableRowElement;
    expect(dupRow.classList.contains('dup')).toBe(true);
    unmount(cmp);
  });

  it('info popover bullets render the three documented strings (Final fold S4)', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const items = target.querySelectorAll('[data-testid="proc-info-content"] li');
    expect(items.length).toBe(3);
    const texts = Array.from(items).map((li) => li.textContent ?? '');
    expect(texts.some((t) => t.includes('godo-irq-pin'))).toBe(true);
    expect(texts.some((t) => t.includes('Managed services'))).toBe(true);
    expect(texts.some((t) => t.includes('빨간 배너'))).toBe(true);
    unmount(cmp);
  });

  it('managed-category name uses --color-status-warn class (Mode-A M5 + Final fold O1)', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const cell = target.querySelector('[data-testid="proc-row-100"] .name-cell') as HTMLElement;
    expect(cell).not.toBeNull();
    expect(cell.classList.contains('name-managed')).toBe(true);
    expect(cell.dataset.category).toBe('managed');
    unmount(cmp);
  });

  it('count summary reflects filtered visible / total', () => {
    const cmp = mount(ProcessTable, { target, props: { snapshot: snapshot() } });
    flushSync();
    const count = target.querySelector('[data-testid="proc-count"]') as HTMLElement;
    expect(count.textContent).toContain('3 / 3');
    const search = target.querySelector('[data-testid="proc-search"]') as HTMLInputElement;
    search.value = 'godo';
    search.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(count.textContent).toContain('2 / 3');
    unmount(cmp);
  });
});
