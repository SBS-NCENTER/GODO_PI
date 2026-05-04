/**
 * issue#28 — `<ApplyMemoModal>` validation pin.
 *
 * Pins:
 * - Invalid memo blocks the Apply button.
 * - Valid memo enables Apply; clicking it invokes `onApply` with the
 *   memo string.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ApplyMemoModal from '../../src/components/ApplyMemoModal.svelte';

let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  target.remove();
});

describe('ApplyMemoModal', () => {
  it('invalid memo blocks Apply button', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();
    const inst = mount(ApplyMemoModal, {
      target,
      props: { open: true, onApply, onCancel },
    });
    flushSync();
    const input = target.querySelector('input[type="text"]') as HTMLInputElement;
    const buttons = Array.from(target.querySelectorAll('.actions button')) as HTMLButtonElement[];
    const applyBtn = buttons[1];
    // Empty memo → button disabled.
    expect(applyBtn.disabled).toBe(true);

    input.value = 'bad memo';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(applyBtn.disabled).toBe(true);
    unmount(inst);
  });

  it('valid memo enables Apply and clicking invokes onApply with the memo', () => {
    const onApply = vi.fn();
    const onCancel = vi.fn();
    const inst = mount(ApplyMemoModal, {
      target,
      props: { open: true, onApply, onCancel },
    });
    flushSync();
    const input = target.querySelector('input[type="text"]') as HTMLInputElement;
    input.value = 'wallcal01';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    const buttons = Array.from(target.querySelectorAll('.actions button')) as HTMLButtonElement[];
    const applyBtn = buttons[1];
    expect(applyBtn.disabled).toBe(false);
    applyBtn.click();
    flushSync();
    expect(onApply).toHaveBeenCalledWith('wallcal01');
    unmount(inst);
  });

  // issue#28 (Mode-B CR3) — SSE frame filtering by request_id.
  // When sessionRequestId is set, frames whose `request_id` does NOT
  // match are silently dropped (no progress update). A regression that
  // ignores `request_id` would let stale-tab frames bleed into the
  // progress bar of a fresh Apply session.
  it('drops SSE frames with mismatched request_id', () => {
    // Capture the EventSource instance the modal opens so we can drive
    // it from the test.
    let captured: MockEventSource | null = null;
    class MockEventSource {
      onmessage: ((ev: MessageEvent<string>) => void) | null = null;
      onerror: ((ev: Event) => void) | null = null;
      readyState = 0;
      url: string;
      constructor(url: string) {
        this.url = url;
        captured = this;
      }
      close(): void {
        this.readyState = 2;
      }
      emit(data: unknown): void {
        this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
      }
    }
    // jsdom does not provide EventSource; install our mock.
    const prev = (globalThis as unknown as { EventSource?: typeof EventSource }).EventSource;
    (globalThis as unknown as { EventSource: typeof EventSource }).EventSource =
      MockEventSource as unknown as typeof EventSource;

    try {
      const onApply = vi.fn();
      const onCancel = vi.fn();
      const inst = mount(ApplyMemoModal, {
        target,
        props: {
          open: true,
          onApply,
          onCancel,
          sessionRequestId: 'session-A',
        },
      });
      flushSync();
      expect(captured).not.toBeNull();
      const es = captured as unknown as MockEventSource;

      // Frame #1: matching request_id → drives progress.
      es.emit({ phase: 'starting', progress: 0.1, request_id: 'session-A' });
      flushSync();
      let phaseEl = target.querySelector('.phase') as HTMLElement | null;
      expect(phaseEl?.textContent).toContain('starting');
      expect(phaseEl?.textContent).toContain('10%');

      // Frame #2: stale request_id → DROPPED (progress unchanged).
      es.emit({ phase: 'rotate', progress: 0.5, request_id: 'session-B' });
      flushSync();
      phaseEl = target.querySelector('.phase') as HTMLElement | null;
      // Still the previous phase from the matching frame.
      expect(phaseEl?.textContent).toContain('starting');
      expect(phaseEl?.textContent).toContain('10%');

      // Frame #3: matching request_id again → progress advances.
      es.emit({ phase: 'done', progress: 1.0, request_id: 'session-A' });
      flushSync();
      phaseEl = target.querySelector('.phase') as HTMLElement | null;
      expect(phaseEl?.textContent).toContain('done');
      expect(phaseEl?.textContent).toContain('100%');

      unmount(inst);
    } finally {
      // Restore original EventSource (or remove if it didn't exist).
      if (prev === undefined) {
        delete (globalThis as unknown as { EventSource?: unknown }).EventSource;
      } else {
        (globalThis as unknown as { EventSource: typeof EventSource }).EventSource = prev;
      }
    }
  });
});
