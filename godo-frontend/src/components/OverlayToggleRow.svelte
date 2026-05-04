<script lang="ts">
  /**
   * issue#28 — unified overlay toggle row.
   *
   * Sole owner of the per-overlay-surface toggle UI. Mounted on `/map`
   * and `/map-edit`; persistence is via `overlayToggles` store
   * (localStorage-backed). Origin/Axis, LiDAR, Grid in that order.
   */

  import {
    overlayToggles,
    toggleGrid,
    toggleLidar,
    toggleOriginAxis,
  } from '../stores/overlayToggles.js';

  let state = $state($overlayToggles);
  $effect(() => {
    const unsub = overlayToggles.subscribe((s) => {
      state = s;
    });
    return () => unsub();
  });
</script>

<div class="overlay-toggle-row" role="group" aria-label="Map overlays">
  <label class="toggle">
    <input
      type="checkbox"
      checked={state.originAxisOn}
      onchange={() => toggleOriginAxis()}
    />
    <span>원점 / 축</span>
  </label>
  <label class="toggle">
    <input
      type="checkbox"
      checked={state.lidarOn}
      onchange={() => toggleLidar()}
    />
    <span>LiDAR</span>
  </label>
  <label class="toggle">
    <input
      type="checkbox"
      checked={state.gridOn}
      onchange={() => toggleGrid()}
    />
    <span>그리드</span>
  </label>
</div>

<style>
  .overlay-toggle-row {
    display: inline-flex;
    gap: 12px;
    align-items: center;
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    cursor: pointer;
    user-select: none;
    color: var(--color-text, #1f2937);
  }
</style>
