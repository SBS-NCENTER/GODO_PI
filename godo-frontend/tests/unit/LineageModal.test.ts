/**
 * issue#30 — `<LineageModal>` rendering pin.
 *
 * Pins:
 * - operator_apply lineage renders clean tree (✓ glyph).
 * - synthesized lineage renders ⚠ glyph + tooltip "issue#30 이전 자동
 *   합성 (generation unknown)".
 * - auto_migrated_pre_issue30 lineage renders ⓘ glyph + tooltip
 *   "PR #81 이전 작업 자동 마이그레이션 (generation = 1 가정)".
 * - empty / null sidecar renders the legacy / pristine 메시지.
 */

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import LineageModal from '../../src/components/LineageModal.svelte';
import type { SidecarV1 } from '../../src/lib/protocol';

let target: HTMLElement;

beforeEach(() => {
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(() => {
  target.remove();
});

function makeSidecar(overrides: Partial<SidecarV1> = {}): SidecarV1 {
  return {
    schema: 'godo.map.sidecar.v1',
    kind: 'derived',
    source: { pristine_pgm: 'chroma.pgm', pristine_yaml: 'chroma.yaml' },
    lineage: { generation: 1, parents: ['chroma'], kind: 'operator_apply' },
    cumulative_from_pristine: { translate_x_m: 1.5, translate_y_m: -2.0, rotate_deg: 30 },
    this_step: {
      delta_translate_x_m: 0.5,
      delta_translate_y_m: 0,
      delta_rotate_deg: 0,
      picked_world_x_m: 1.5,
      picked_world_y_m: -2,
    },
    result_yaml_origin: { x_m: -3.5, y_m: -4.0, yaw_deg: 0 },
    result_canvas: { width_px: 200, height_px: 100 },
    integrity: { pgm_sha256: 'a' + '0'.repeat(63), yaml_sha256: 'b' + '0'.repeat(63) },
    created: { iso_kst: '2026-05-04T15:00:00+09:00', memo: 'wallcal01', reason: 'operator_apply' },
    ...overrides,
  };
}

describe('LineageModal (issue#30)', () => {
  it('does not render when open=false', () => {
    const sc = makeSidecar();
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: sc, name: 'foo', open: false, onClose: () => {} },
    });
    flushSync();
    expect(target.querySelector('[data-testid="lineage-modal"]')).toBeNull();
    unmount(inst);
  });

  it('renders operator_apply lineage with ✓ glyph', () => {
    const sc = makeSidecar({
      lineage: { generation: 1, parents: ['chroma'], kind: 'operator_apply' },
    });
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: sc, name: 'chroma.20260504-150000-wallcal01', open: true, onClose: () => {} },
    });
    flushSync();
    const modal = target.querySelector('[data-testid="lineage-modal"]');
    expect(modal).not.toBeNull();
    const badge = target.querySelector('.kind-badge')!;
    expect(badge.textContent).toContain('✓');
    expect(badge.getAttribute('title')).toContain('운영자 Apply');
    unmount(inst);
  });

  it('renders synthesized lineage with ⚠ glyph and Korean tooltip', () => {
    const sc = makeSidecar({
      kind: 'synthesized',
      lineage: { generation: -1, parents: [], kind: 'synthesized' },
    });
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: sc, name: 'orphan_foo', open: true, onClose: () => {} },
    });
    flushSync();
    const badge = target.querySelector('.kind-badge')!;
    expect(badge.textContent).toContain('⚠');
    expect(badge.getAttribute('title')).toContain('자동 합성');
    expect(badge.getAttribute('title')).toContain('generation unknown');
    // generation row should show "unknown (-1)".
    const table = target.querySelector('[data-testid="lineage-table"]')!;
    expect(table.textContent).toContain('unknown (-1)');
    unmount(inst);
  });

  it('renders auto_migrated_pre_issue30 lineage with ⓘ glyph and tooltip', () => {
    const sc = makeSidecar({
      lineage: { generation: 1, parents: ['chroma'], kind: 'auto_migrated_pre_issue30' },
    });
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: sc, name: 'chroma.20260504-150000-pr81', open: true, onClose: () => {} },
    });
    flushSync();
    const badge = target.querySelector('.kind-badge')!;
    expect(badge.textContent).toContain('ⓘ');
    expect(badge.getAttribute('title')).toContain('PR #81 이전');
    expect(badge.getAttribute('title')).toContain('generation = 1 가정');
    unmount(inst);
  });

  it('null sidecar shows legacy / pristine message', () => {
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: null, name: 'chroma', open: true, onClose: () => {} },
    });
    flushSync();
    const empty = target.querySelector('[data-testid="lineage-empty"]');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain('legacy');
    unmount(inst);
  });

  it('close button invokes onClose', () => {
    let closed = false;
    const sc = makeSidecar();
    const inst = mount(LineageModal, {
      target,
      props: {
        sidecar: sc,
        name: 'foo',
        open: true,
        onClose: () => {
          closed = true;
        },
      },
    });
    flushSync();
    const btn = target.querySelector<HTMLButtonElement>('[data-testid="lineage-modal-close"]')!;
    btn.click();
    flushSync();
    expect(closed).toBe(true);
    unmount(inst);
  });

  // issue#30.1 — Svelte a11y compile-warning fix.
  // Contract: exactly one element in the modal subtree carries
  // `role="dialog"`, and that element is the inner `.modal-card`
  // (NOT the click/keydown-handler-bearing backdrop). Pinning the
  // contract instead of the class-name choice avoids brittle coupling.
  // The backdrop carries `role="presentation"` to satisfy Svelte's
  // sister rule (a static div with handlers needs a role).
  it('role_dialog_lives_on_exactly_one_element_not_the_backdrop', () => {
    const sc = makeSidecar();
    const inst = mount(LineageModal, {
      target,
      props: { sidecar: sc, name: 'foo', open: true, onClose: () => {} },
    });
    flushSync();
    const dialogs = target.querySelectorAll('[role="dialog"]');
    expect(dialogs.length).toBe(1);
    const dialog = target.querySelector('[role="dialog"]');
    const card = target.querySelector('.modal-card');
    expect(dialog).not.toBeNull();
    expect(card).not.toBeNull();
    expect(dialog).toBe(card);
    // Backdrop must NOT carry the dialog role (its role is
    // `presentation`, semantically empty).
    const backdrop = target.querySelector('.modal-backdrop');
    expect(backdrop).not.toBeNull();
    expect(backdrop!.getAttribute('role')).not.toBe('dialog');
    unmount(inst);
  });
});
