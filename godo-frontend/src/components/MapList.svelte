<script lang="ts">
  /**
   * issue#28 → issue#30 — grouped map list (pristine parents +
   * indented variants).
   *
   * Sole owner of the grouped-tree rendering for `/api/maps` results.
   * Click a row → confirm dialog → activate. Active map carries a
   * badge. Each variant carries an optional `!` lineage button which
   * the parent route wires to `LineageModal.svelte`.
   */

  export interface MapEntryView {
    name: string;
    is_active: boolean;
    width_px: number | null;
    height_px: number | null;
    resolution_m: number | null;
  }

  export interface MapGroupView {
    base: string;
    pristine: MapEntryView | null;
    variants: MapEntryView[];
  }

  interface Props {
    groups: MapGroupView[];
    onActivate: (name: string) => void;
    onDelete?: (name: string) => void;
    /**
     * issue#30 — open the LineageModal for the named map. When omitted
     * the lineage button is hidden (back-compat for callers that don't
     * yet wire LineageModal).
     */
    onShowLineage?: (name: string) => void;
  }

  let { groups, onActivate, onDelete, onShowLineage }: Props = $props();

  function formatDims(e: MapEntryView | null): string {
    if (!e || e.width_px === null || e.height_px === null) return '';
    const meters =
      e.resolution_m !== null
        ? ` (${(e.width_px * e.resolution_m).toFixed(1)}×${(e.height_px * e.resolution_m).toFixed(1)} m)`
        : '';
    return `${e.width_px}×${e.height_px} px${meters}`;
  }
</script>

<ul class="map-list">
  {#each groups as group (group.base)}
    <li class="group">
      {#if group.pristine}
        <button
          type="button"
          class="row pristine-row"
          class:active={group.pristine.is_active}
          onclick={() => onActivate(group.pristine!.name)}
        >
          <span class="name">{group.pristine.name}</span>
          <span class="dims">{formatDims(group.pristine)}</span>
          {#if group.pristine.is_active}<span class="badge">활성</span>{/if}
        </button>
      {:else}
        <div class="row pristine-row orphan">
          <span class="name">{group.base}</span>
          <span class="dims">(원본 없음)</span>
        </div>
      {/if}
      {#if group.variants.length > 0}
        <ul class="variants">
          {#each group.variants as v (v.name)}
            <li class="variant-cell" class:active={v.is_active}>
              <button
                type="button"
                class="row variant-row"
                class:active={v.is_active}
                onclick={() => onActivate(v.name)}
              >
                <span class="name">{v.name.slice(group.base.length + 1)}</span>
                <span class="dims">{formatDims(v)}</span>
                {#if v.is_active}<span class="badge">활성</span>{/if}
              </button>
              {#if onShowLineage}
                <button
                  type="button"
                  class="lineage-btn"
                  onclick={() => onShowLineage(v.name)}
                  title="lineage 보기"
                  aria-label="lineage 보기"
                  data-testid="map-lineage-btn-{v.name}"
                >
                  !
                </button>
              {/if}
              {#if onDelete && !v.is_active}
                <button
                  type="button"
                  class="del"
                  onclick={() => onDelete(v.name)}
                >
                  삭제
                </button>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </li>
  {/each}
</ul>

<style>
  .map-list { list-style: none; padding: 0; margin: 0; }
  .group { margin-bottom: 6px; }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    width: 100%;
    text-align: left;
    background: var(--color-surface, #f8fafc);
    border: 1px solid var(--color-border, #cbd5e1);
    border-radius: 6px;
    font: inherit;
    cursor: pointer;
  }
  .row.active { background: var(--color-accent-soft, #dbeafe); }
  .pristine-row { font-weight: 600; }
  .orphan { color: var(--color-muted, #6b7280); }
  .variants { list-style: none; padding-left: 18px; margin: 4px 0 0; }
  .variants .row { font-weight: 400; }
  .name { flex: 1; }
  .dims { font-size: 12px; color: var(--color-muted, #6b7280); }
  .badge {
    font-size: 11px;
    background: var(--color-accent, #2563eb);
    color: var(--color-on-accent, #fff);
    padding: 2px 6px;
    border-radius: 4px;
  }
  .del {
    font-size: 11px;
    background: transparent;
    border: 1px solid var(--color-border, #cbd5e1);
    border-radius: 4px;
    padding: 2px 6px;
    cursor: pointer;
    color: var(--color-muted, #6b7280);
  }
  .lineage-btn {
    font-size: 13px;
    background: transparent;
    border: 1px solid var(--color-border, #cbd5e1);
    border-radius: 4px;
    padding: 2px 8px;
    cursor: pointer;
    color: var(--color-accent, #2563eb);
    font-weight: 600;
    line-height: 1;
  }
  .lineage-btn:hover {
    background: var(--color-accent-soft, #dbeafe);
  }
</style>
