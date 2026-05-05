<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import ConfirmDialog from '$components/ConfirmDialog.svelte';
  import LastPoseCard from '$components/LastPoseCard.svelte';
  import LineageModal from '$components/LineageModal.svelte';
  import MapList from '$components/MapList.svelte';
  import MapListPanel from '$components/MapListPanel.svelte';
  import MapZoomControls from '$components/MapZoomControls.svelte';
  import OverlayToggleRow from '$components/OverlayToggleRow.svelte';
  import PoseCanvas from '$components/PoseCanvas.svelte';
  import PoseHintLayer, { type HintPose } from '$components/PoseHintLayer.svelte';
  import PoseHintNumericFields from '$components/PoseHintNumericFields.svelte';
  import ScanToggle from '$components/ScanToggle.svelte';
  import TrackerControls from '$components/TrackerControls.svelte';
  import { MAP_SUBTAB_EDIT, MAP_SUBTAB_MAPPING, MAP_SUBTAB_OVERVIEW } from '$lib/constants';
  import { formatDegrees, formatMeters } from '$lib/format';
  import { createMapViewport } from '$lib/mapViewport.svelte';
  import {
    MAPPING_STATE_RUNNING,
    MAPPING_STATE_STARTING,
    MAPPING_STATE_STOPPING,
    type LastPose,
    type LastScan,
    type MappingStatus,
    type SidecarResponse,
    type SidecarV1,
  } from '$lib/protocol';
  import { apiGet } from '$lib/api';
  import { navigate, route } from '$lib/router';
  import { subscribeLastPose } from '$stores/lastPose';
  import { subscribeLastScan } from '$stores/lastScan';
  import { mapMetadata } from '$stores/mapMetadata';
  import { activate, mapGroups, refresh as refreshMaps, remove } from '$stores/maps';
  import { subscribeMappingStatus } from '$stores/mappingStatus';
  import { overlayToggles } from '$stores/overlayToggles';
  import { scanOverlay } from '$stores/scanOverlay';
  import MapEdit from './MapEdit.svelte';
  import MapMapping from './MapMapping.svelte';

  // Per-route viewport instance (Q2 — operator navigating /map ↔
  // /map-edit gets a fresh viewport). Shared between `<PoseCanvas/>`
  // and `<MapZoomControls/>` so the buttons drive the same zoom state.
  const viewport = createMapViewport();

  let pose = $state<LastPose | null>(null);
  let scan = $state<LastScan | null>(null);
  let scanOn = $state(false);
  let unsub: (() => void) | null = null;
  let unsubScan: (() => void) | null = null;
  let unsubOverlay: (() => void) | null = null;
  let unsubRoute: (() => void) | null = null;

  // issue#28 (HIL fix) — grouped map list state. `<MapList>` is the
  // operator-locked grouped-tree renderer; activate/delete go through
  // `<ConfirmDialog>` for safety per spec.
  let groups = $state<typeof $mapGroups>([]);
  let unsubGroups: (() => void) | null = null;
  let activateOpen = $state(false);
  let activateTarget = $state<string | null>(null);
  let deleteOpen = $state(false);
  let deleteTarget = $state<string | null>(null);
  let mapListBanner = $state<{ msg: string; tone: 'info' | 'error' } | null>(null);

  // issue#30 — LineageModal state.
  let lineageOpen = $state<boolean>(false);
  let lineageTarget = $state<string | null>(null);
  let lineageData = $state<SidecarV1 | null>(null);

  async function openLineage(name: string): Promise<void> {
    lineageTarget = name;
    lineageData = null;
    lineageOpen = true;
    try {
      const resp = await apiGet<SidecarResponse>(
        `/api/maps/${encodeURIComponent(name)}/sidecar`,
      );
      lineageData = resp.sidecar;
    } catch {
      lineageData = null;
    }
  }

  function closeLineage(): void {
    lineageOpen = false;
    lineageTarget = null;
    lineageData = null;
  }

  function openActivate(name: string): void {
    activateTarget = name;
    activateOpen = true;
  }
  function openDelete(name: string): void {
    deleteTarget = name;
    deleteOpen = true;
  }
  async function confirmActivate(): Promise<void> {
    const name = activateTarget;
    activateOpen = false;
    activateTarget = null;
    if (!name) return;
    try {
      await activate(name);
      mapListBanner = {
        msg: `'${name}' 활성화 완료. godo-tracker 재시작 후 적용됩니다.`,
        tone: 'info',
      };
    } catch (e) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      mapListBanner = { msg: err ? `활성화 실패: ${err}` : '활성화 실패', tone: 'error' };
    }
  }
  async function confirmDelete(): Promise<void> {
    const name = deleteTarget;
    deleteOpen = false;
    deleteTarget = null;
    if (!name) return;
    try {
      await remove(name);
      mapListBanner = { msg: `'${name}' 삭제 완료`, tone: 'info' };
    } catch (e) {
      const err = (e as { body?: { err?: string } })?.body?.err;
      mapListBanner = { msg: err ? `삭제 실패: ${err}` : '삭제 실패', tone: 'error' };
    }
  }

  // Default `previewUrl` mirrors the pre-Track-E behaviour: PoseCanvas
  // fetches the active map via `/api/map/image` (resolves through the
  // `active.pgm` symlink). Selecting a non-active row in the
  // MapListPanel re-points to `/api/maps/<name>/image` for read-only
  // preview without altering the active state.
  let previewUrl = $state('/api/map/image');

  // issue#3 — pose hint state. Mode-A M6: lives in Map.svelte parent
  // so it survives sub-tab switching (PoseHintLayer is unmounted on
  // Edit, but the placed hint persists; common-header
  // <TrackerControls> can still issue "Calibrate from hint" from
  // either sub-tab).
  let poseHintEnabled = $state(false);
  let hint = $state<HintPose | null>(null);
  function onHintChange(next: HintPose | null): void {
    hint = next;
  }

  // Sub-tab is URL-backed (3 sub-tabs as of issue#14): `/map` → Overview,
  // `/map-edit` → Edit, `/map-mapping` → Mapping. Refresh + browser
  // back-button preserve the active view.
  let activeSubtab = $state<string>(MAP_SUBTAB_OVERVIEW);

  // issue#14 — mappingStatus drives:
  //   - Disabled state on the Edit sub-tab tab button (operator cannot
  //     concurrently edit + map).
  //   - Tooltip on the disabled Edit button.
  let mappingStatus = $state<MappingStatus | null>(null);
  let unsubMapping: (() => void) | null = null;

  // issue#28 — overlay toggles + map metadata for the world-anchored
  // grid + origin/axis overlays mounted on the Overview sub-tab.
  let originAxisOn = $state(false);
  let gridOn = $state(false);
  let unsubToggles: (() => void) | null = null;
  let mapDimsState = $state<{ width: number; height: number } | null>(null);
  let mapResolution = $state<number | null>(null);
  let mapOrigin = $state<readonly [number, number, number] | null>(null);
  let unsubMeta: (() => void) | null = null;
  // Note: pre-issue#28 used standalone overlay canvases here; HIL fix
  // 2026-05-04 KST moved them into PoseCanvas's drawPoseLayer so they
  // share the underlay's pan/zoom transform.

  let mappingActive = $derived(
    mappingStatus !== null &&
      (mappingStatus.state === MAPPING_STATE_STARTING ||
        mappingStatus.state === MAPPING_STATE_RUNNING ||
        mappingStatus.state === MAPPING_STATE_STOPPING),
  );

  function pathToSubtab(path: string): string {
    if (path === '/map-edit') return MAP_SUBTAB_EDIT;
    if (path === '/map-mapping') return MAP_SUBTAB_MAPPING;
    return MAP_SUBTAB_OVERVIEW;
  }

  function selectSubtab(key: string): void {
    if (key === activeSubtab) return;
    if (key === MAP_SUBTAB_EDIT && mappingActive) return; // L14 lock
    if (key === MAP_SUBTAB_MAPPING) navigate('/map-mapping');
    else if (key === MAP_SUBTAB_EDIT) navigate('/map-edit');
    else navigate('/map');
  }

  function onPreviewSelect(url: string): void {
    previewUrl = url;
  }

  onMount(() => {
    unsub = subscribeLastPose((p) => (pose = p));
    // Track D — subscribe to the LastScan store; lifecycle is managed
    // by the store (gated on the scanOverlay flag). When the overlay
    // flag is off the store does not even open the SSE.
    unsubScan = subscribeLastScan((s) => (scan = s));
    unsubOverlay = scanOverlay.subscribe((v) => (scanOn = v));
    unsubRoute = route.subscribe((p) => (activeSubtab = pathToSubtab(p)));
    // issue#14 — subscribe to the mapping store so the sub-tab buttons
    // can disable the Edit sub-tab while mapping is active.
    unsubMapping = subscribeMappingStatus((s) => (mappingStatus = s));
    // issue#28 — overlay toggles + map metadata for the world-anchored
    // overlays mounted on Overview.
    unsubToggles = overlayToggles.subscribe((s) => {
      originAxisOn = s.originAxisOn;
      gridOn = s.gridOn;
    });
    unsubMeta = mapMetadata.subscribe((m) => {
      if (m) {
        mapDimsState = { width: m.width, height: m.height };
        mapResolution = m.resolution;
        mapOrigin = m.origin;
      }
    });
    // issue#28 (HIL fix) — keep `groups` mirrored from the store so
    // <MapList> rerenders after each refresh()/activate()/remove().
    unsubGroups = mapGroups.subscribe((g) => (groups = g));
    // Trigger initial fetch — MapListPanel does this too, but the
    // grouped renderer ALSO needs the data. Idempotent.
    void refreshMaps().catch(() => {
      mapListBanner = { msg: '맵 목록을 가져오지 못했습니다.', tone: 'error' };
    });
  });

  onDestroy(() => {
    unsub?.();
    unsubScan?.();
    unsubOverlay?.();
    unsubRoute?.();
    unsubMapping?.();
    unsubToggles?.();
    unsubMeta?.();
    unsubGroups?.();
  });

  let yamlYawDeg = $derived(mapOrigin === null ? 0 : mapOrigin[2] * (180 / Math.PI));
</script>

<div data-testid="map-page">
  <div class="breadcrumb">
    GODO &gt; Map{activeSubtab === MAP_SUBTAB_EDIT
      ? ' > Edit'
      : activeSubtab === MAP_SUBTAB_MAPPING
        ? ' > Mapping'
        : ''}
  </div>
  <h2>Map</h2>

  <!-- issue#2.4 — common header above the sub-tab row. Operator HIL
       2026-04-30 KST late evening: TrackerControls + LastPoseCard
       must show on BOTH Overview and Edit. Promoted out of per-sub-tab
       blocks so they share a single mount lifecycle and a single
       lastPose / mode subscription pair.
       issue#3 — `hint` + `onClearHint` props supplied so the
       common-header "Calibrate from hint" button works on either
       sub-tab. -->
  <TrackerControls {hint} onClearHint={() => onHintChange(null)} />
  <LastPoseCard />

  <div class="subtabs-row">
    <div class="subtabs" role="tablist" data-testid="map-subtabs">
      <button
        class="subtab"
        class:active={activeSubtab === MAP_SUBTAB_OVERVIEW}
        role="tab"
        aria-selected={activeSubtab === MAP_SUBTAB_OVERVIEW}
        onclick={() => selectSubtab(MAP_SUBTAB_OVERVIEW)}
        data-testid="map-subtab-overview">Overview</button
      >
      <button
        class="subtab"
        class:active={activeSubtab === MAP_SUBTAB_EDIT}
        role="tab"
        aria-selected={activeSubtab === MAP_SUBTAB_EDIT}
        disabled={mappingActive}
        title={mappingActive ? '매핑 중에는 편집할 수 없습니다' : ''}
        onclick={() => selectSubtab(MAP_SUBTAB_EDIT)}
        data-testid="map-subtab-edit">Edit</button
      >
      <button
        class="subtab"
        class:active={activeSubtab === MAP_SUBTAB_MAPPING}
        role="tab"
        aria-selected={activeSubtab === MAP_SUBTAB_MAPPING}
        onclick={() => selectSubtab(MAP_SUBTAB_MAPPING)}
        data-testid="map-subtab-mapping">Mapping</button
      >
    </div>
    <!-- ScanToggle pinned to the right end of the sub-tabs row. Single
         mount; shows on both sub-tabs (the toggle's effect — LiDAR
         overlay on/off — applies to whichever map view is active).
         issue#3: pose-hint toggle sits next to ScanToggle (both are
         operator switches that bound canvas pointer behaviour). The
         toggle is gated on the Overview sub-tab — on Edit it is
         hidden because the brush layer needs the canvas events. -->
    <div class="hstack">
      {#if activeSubtab === MAP_SUBTAB_OVERVIEW}
        <label class="pose-hint-toggle" data-testid="pose-hint-toggle">
          <input type="checkbox" bind:checked={poseHintEnabled} />
          <span>위치 힌트</span>
        </label>
      {/if}
      <ScanToggle {scan} />
    </div>
  </div>

  {#if activeSubtab === MAP_SUBTAB_OVERVIEW}
    {#if pose && pose.valid}
      <div class="muted" style="margin-bottom: 8px;" data-testid="pose-readout">
        ({formatMeters(pose.x_m)}, {formatMeters(pose.y_m)}) · {formatDegrees(pose.yaw_deg)}
      </div>
    {/if}
    <!-- issue#28 — unified overlay toggle row. Mounted at the top of
         Overview (and on the same row as the segmented control on Edit). -->
    <div class="overlay-row" data-testid="map-overlay-row">
      <OverlayToggleRow />
    </div>
    <div class="canvas-stack">
      <PoseCanvas
        {viewport}
        {pose}
        mapImageUrl={previewUrl}
        {scan}
        scanOverlayOn={scanOn}
        {originAxisOn}
        {gridOn}
        mapMeta={$mapMetadata}
        {yamlYawDeg}
      />
      {#if poseHintEnabled}
        <PoseHintLayer
          {viewport}
          enabled={poseHintEnabled}
          {hint}
          onhintchange={onHintChange}
        />
      {/if}
      <MapZoomControls {viewport} />
    </div>
    {#if poseHintEnabled}
      <PoseHintNumericFields {hint} onhintchange={onHintChange} />
    {/if}
    <!-- Operator HIL 2026-04-30 KST: "map 미리보기 블럭이 위로, 맵
         목록 블럭이 아래로" — MapListPanel moved BELOW the canvas.
         issue#28 (HIL fix): grouped <MapList> hosted above the legacy
         <MapListPanel>. The grouped tree is the operator-locked
         primary view (pristine parent + indented variants); the legacy
         flat panel stays one release for the loopback-restart prompt
         + delete-confirm features that have not yet migrated. -->
    <section class="map-list-section" data-testid="map-list-grouped-section">
      <header><h3>맵 목록 (그룹 뷰)</h3></header>
      {#if mapListBanner}
        <div class="banner banner-{mapListBanner.tone}" role="status">
          {mapListBanner.msg}
        </div>
      {/if}
      {#if groups.length === 0}
        <p class="empty-hint">표시할 맵이 없습니다.</p>
      {:else}
        <MapList
          groups={groups.map((g) => ({
            base: g.pristine.name,
            pristine: g.pristine,
            variants: g.variants,
          }))}
          onActivate={openActivate}
          onDelete={openDelete}
          onShowLineage={(n) => {
            void openLineage(n);
          }}
        />
      {/if}
    </section>
    <LineageModal
      open={lineageOpen}
      name={lineageTarget ?? ''}
      sidecar={lineageData}
      onClose={closeLineage}
    />
    <ConfirmDialog
      open={activateOpen}
      title="맵 활성화"
      message={activateTarget
        ? `'${activateTarget}'을 활성화 할까요? godo-tracker 재시작 후 적용됩니다.`
        : ''}
      confirmLabel="활성화"
      cancelLabel="취소"
      onConfirm={confirmActivate}
      onCancel={() => {
        activateOpen = false;
        activateTarget = null;
      }}
    />
    <ConfirmDialog
      open={deleteOpen}
      title="맵 삭제"
      message={deleteTarget ? `'${deleteTarget}'을 영구 삭제 할까요?` : ''}
      confirmLabel="삭제"
      cancelLabel="취소"
      onConfirm={confirmDelete}
      onCancel={() => {
        deleteOpen = false;
        deleteTarget = null;
      }}
    />
    <MapListPanel {onPreviewSelect} />
  {:else if activeSubtab === MAP_SUBTAB_EDIT}
    <MapEdit />
  {:else if activeSubtab === MAP_SUBTAB_MAPPING}
    <MapMapping />
  {/if}
</div>

<style>
  h2 {
    margin-top: 0;
  }
  /* issue#2.4 — sub-tabs row hosts the tab buttons (left) and the
     ScanToggle (right end). Operator-locked: ScanToggle must sit at a
     consistent screen position across sub-tabs; the right end of the
     sub-tab row is the choice (mirrors Map title row but stays close
     to the content it controls). */
  .subtabs-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 12px 0;
    border-bottom: 1px solid var(--color-border);
  }
  /* PR β — wraps the underlay canvas so `<MapZoomControls/>` can sit
     in the top-left absolutely-positioned slot WITHOUT overlapping
     surrounding content. */
  .canvas-stack {
    position: relative;
    margin-bottom: 12px;
  }
  /* issue#28 — world-anchored overlays (axis, grid) live in the same
     stacking context as PoseCanvas; pointer-events: none so they don't
     swallow the underlay's pan/wheel/click handlers. */
  .overlay-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .overlay-row {
    margin: 8px 0;
  }
  /* Sub-tab styling mirrors System.svelte (PR-B Processes / Extended
     resources) so the visual idiom is consistent across the SPA. */
  .subtabs {
    display: flex;
    gap: 0;
  }
  .subtab {
    background: none;
    border: none;
    padding: 8px 16px;
    cursor: pointer;
    color: var(--color-text-muted);
    font-size: 14px;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .subtab:hover {
    color: var(--color-text);
  }
  .subtab.active {
    color: var(--color-text);
    border-bottom-color: var(--color-accent);
  }
  /* issue#3 — pose-hint toggle. Sits beside ScanToggle in the sub-tab
     row; visible only on Overview. */
  .pose-hint-toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 13px;
    cursor: pointer;
    user-select: none;
  }
  .hstack {
    display: flex;
    gap: 12px;
    align-items: center;
  }
  /* issue#28 (HIL fix) — grouped map list section */
  .map-list-section {
    margin: 12px 0;
    padding: 12px;
    border: 1px solid var(--color-border, #cbd5e1);
    border-radius: 6px;
    background: var(--color-surface-alt, #f1f5f9);
  }
  .map-list-section header h3 {
    margin: 0 0 8px;
    font-size: 14px;
  }
  .map-list-section .banner {
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 13px;
    margin-bottom: 8px;
  }
  .map-list-section .banner-info {
    background: var(--color-accent-soft, #dbeafe);
    color: var(--color-text, #0f172a);
  }
  .map-list-section .banner-error {
    background: #fee2e2;
    color: #991b1b;
  }
  .map-list-section .empty-hint {
    color: var(--color-muted, #6b7280);
    font-size: 13px;
    margin: 4px 0;
  }
</style>
