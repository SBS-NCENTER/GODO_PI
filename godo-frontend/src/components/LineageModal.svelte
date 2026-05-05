<script lang="ts">
  /**
   * issue#30 — sidecar lineage viewer.
   *
   * Renders the `godo.map.sidecar.v1` lineage tree (parent chain +
   * generation + cumulative + this_step) for a given map's sidecar.
   * Categorizes the entry by `lineage.kind`:
   *   - `operator_apply` — clean operator-driven Apply.
   *   - `synthesized` — recovery sweep synthesized for genuine
   *     crash-window orphan; ⚠ glyph + tooltip
   *     "issue#30 이전 자동 합성 (generation unknown)".
   *   - `auto_migrated_pre_issue30` — PR #81-era derived auto-migrated;
   *     ⓘ glyph + tooltip "PR #81 이전 작업 자동 마이그레이션
   *     (generation = 1 가정)".
   *
   * Sidecar fetch wire shape per godo-frontend `protocol.ts::SidecarV1`.
   */

  import type { SidecarV1 } from '$lib/protocol';
  import { LINEAGE_GLYPHS, LINEAGE_GLYPH_FALLBACK } from '$lib/constants';

  interface Props {
    sidecar: SidecarV1 | null;
    name: string;
    open: boolean;
    onClose: () => void;
  }

  const { sidecar, name, open, onClose }: Props = $props();

  // issue#30.1 — `LINEAGE_GLYPHS` is the SSOT (shared with `<MapList>`).
  // Unmapped non-string `kind` falls back through `LINEAGE_GLYPH_FALLBACK`
  // — operator still sees the raw kind string in the `<td>` next to the
  // glyph, so a future schema addition is debuggable in-place.
  function lineageBadge(kind: string): { glyph: string; tooltip: string } {
    return LINEAGE_GLYPHS[kind] ?? { glyph: LINEAGE_GLYPH_FALLBACK.glyph, tooltip: kind };
  }

  function backdropClick(ev: MouseEvent): void {
    if (ev.target === ev.currentTarget) {
      onClose();
    }
  }
</script>

{#if open}
  <!--
    issue#30.1 — a11y split: outer backdrop carries click/keydown
    handlers + `role="presentation"` (semantically empty wrapper);
    inner card carries `role="dialog"` + `aria-modal` + `data-testid`.
    Keeping `role="dialog"` on a click/keydown-handler-bearing element
    triggered Svelte's `a11y_no_noninteractive_element_interactions`
    warning. `role="presentation"` on the backdrop satisfies the sister
    rule `a11y_no_static_element_interactions` (static elements with
    interaction handlers need a role) while keeping the click-outside-
    to-close UX.
  -->
  <div
    class="modal-backdrop"
    role="presentation"
    onclick={backdropClick}
    onkeydown={(e) => {
      if (e.key === 'Escape') onClose();
    }}
    tabindex="-1"
  >
    <div
      class="modal-card"
      role="dialog"
      aria-modal="true"
      aria-label="Sidecar lineage viewer"
      data-testid="lineage-modal"
    >
      <header class="modal-header">
        <h3>맵 lineage — {name}</h3>
        <button
          type="button"
          class="close-btn"
          onclick={onClose}
          data-testid="lineage-modal-close"
        >
          ×
        </button>
      </header>
      <div class="modal-body">
        {#if sidecar === null}
          <p class="muted" data-testid="lineage-empty">
            이 맵에는 sidecar JSON이 없습니다 (legacy / pristine 맵).
          </p>
        {:else}
          {@const badge = lineageBadge(sidecar.lineage.kind)}
          <table class="lineage-table" data-testid="lineage-table">
            <tbody>
              <tr>
                <th>Kind</th>
                <td>
                  <span class="kind-badge" title={badge.tooltip}>{badge.glyph}</span>
                  {sidecar.kind} / {sidecar.lineage.kind}
                </td>
              </tr>
              <tr>
                <th>Generation</th>
                <td>
                  {sidecar.lineage.generation === -1
                    ? 'unknown (-1)'
                    : sidecar.lineage.generation}
                </td>
              </tr>
              <tr>
                <th>Parents</th>
                <td>
                  {#if sidecar.lineage.parents.length === 0}
                    <em>(none)</em>
                  {:else}
                    <ol class="parents-chain">
                      {#each sidecar.lineage.parents as p (p)}
                        <li>{p}</li>
                      {/each}
                    </ol>
                  {/if}
                </td>
              </tr>
              <tr>
                <th>Cumulative</th>
                <td>
                  ({sidecar.cumulative_from_pristine.translate_x_m.toFixed(3)},
                  {sidecar.cumulative_from_pristine.translate_y_m.toFixed(3)}) m,
                  {sidecar.cumulative_from_pristine.rotate_deg.toFixed(1)}°
                </td>
              </tr>
              <tr>
                <th>Result origin</th>
                <td>
                  ({sidecar.result_yaml_origin.x_m.toFixed(3)},
                  {sidecar.result_yaml_origin.y_m.toFixed(3)}) m,
                  {sidecar.result_yaml_origin.yaw_deg.toFixed(1)}°
                </td>
              </tr>
              <tr>
                <th>Canvas</th>
                <td>
                  {sidecar.result_canvas.width_px} × {sidecar.result_canvas.height_px} px
                </td>
              </tr>
              <tr>
                <th>Created</th>
                <td>
                  {sidecar.created.iso_kst} — memo: {sidecar.created.memo || '(none)'}
                  ({sidecar.created.reason})
                </td>
              </tr>
              {#if sidecar.this_step !== null}
                <tr>
                  <th>This step</th>
                  <td>
                    typed Δ = ({sidecar.this_step.delta_translate_x_m.toFixed(3)},
                    {sidecar.this_step.delta_translate_y_m.toFixed(3)}) m,
                    {sidecar.this_step.delta_rotate_deg.toFixed(1)}°<br />
                    picked = ({sidecar.this_step.picked_world_x_m.toFixed(3)},
                    {sidecar.this_step.picked_world_y_m.toFixed(3)}) m
                  </td>
                </tr>
              {/if}
            </tbody>
          </table>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.45);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .modal-card {
    background: var(--color-bg, #fff);
    border-radius: 6px;
    min-width: 480px;
    max-width: 720px;
    max-height: 80vh;
    overflow: auto;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  }
  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 12px 16px;
    border-bottom: 1px solid var(--color-border, #cbd5e1);
  }
  .modal-header h3 {
    margin: 0;
    font-size: 1.05em;
  }
  .close-btn {
    background: transparent;
    border: none;
    font-size: 1.4em;
    cursor: pointer;
    line-height: 1;
    padding: 0 6px;
  }
  .modal-body {
    padding: 12px 16px;
  }
  .lineage-table {
    width: 100%;
    border-collapse: collapse;
  }
  .lineage-table th {
    text-align: left;
    width: 30%;
    padding: 6px 8px;
    background: var(--color-surface, #f8fafc);
    font-weight: 500;
  }
  .lineage-table td {
    padding: 6px 8px;
    border-bottom: 1px solid var(--color-border, #cbd5e1);
  }
  .kind-badge {
    display: inline-block;
    margin-right: 6px;
    font-size: 1.1em;
    cursor: help;
  }
  .parents-chain {
    margin: 0;
    padding-left: 18px;
  }
  .muted {
    color: var(--color-text-muted, #666);
    font-style: italic;
  }
</style>
