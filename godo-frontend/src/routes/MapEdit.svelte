<script lang="ts">
  /**
   * Track B-MAPEDIT + issue#28 — `/map-edit` route.
   *
   * Hosts the segmented Edit mode switcher (Coordinate / Erase) +
   * overlay toggle row + per-mode Apply / Discard. Apply opens the
   * `<ApplyMemoModal>` which collects a postfix memo and POSTs to
   * `/api/map/edit/coord` or `/api/map/edit/erase`. The modal also
   * consumes the SSE progress channel.
   *
   * Mode-state ownership lives in this route; mask state still lives
   * inside `<MapMaskCanvas>` (CODEBASE.md invariant `(u)` updated for
   * issue#28). Mode switch does NOT auto-discard the other mode's
   * pending state — the operator can stage XY+yaw edits in Coord mode,
   * flip to Erase to brush a fixture, then switch back without losing
   * the Coord work.
   */
  import { onDestroy, onMount } from 'svelte';

  import ApplyMemoModal from '$components/ApplyMemoModal.svelte';
  import EditModeSwitcher from '$components/EditModeSwitcher.svelte';
  import GridOverlay from '$components/GridOverlay.svelte';
  import MapMaskCanvas from '$components/MapMaskCanvas.svelte';
  import MapUnderlay from '$components/MapUnderlay.svelte';
  import MapZoomControls from '$components/MapZoomControls.svelte';
  import OriginAxisOverlay from '$components/OriginAxisOverlay.svelte';
  import OriginPicker from '$components/OriginPicker.svelte';
  import OverlayToggleRow from '$components/OverlayToggleRow.svelte';
  import RestartPendingBanner from '$components/RestartPendingBanner.svelte';
  import {
    ApiError,
    postMapEditCoord,
    postMapEditErase,
    postMapOrigin,
  } from '$lib/api';
  import {
    BRUSH_RADIUS_PX_DEFAULT,
    BRUSH_RADIUS_PX_MAX,
    BRUSH_RADIUS_PX_MIN,
    EDIT_MODE_COORD,
    EDIT_MODE_ERASE,
    ORIGIN_PICK_REDIRECT_DELAY_MS,
  } from '$lib/constants';
  import { createMapViewport } from '$lib/mapViewport.svelte';
  import { pixelToWorld } from '$lib/originMath';
  import { drawPose } from '$lib/poseDraw';
  import type {
    LastPose,
    LastScan,
    MapDimensions,
    MapEditCoordBody,
    MapEditPipelineResult,
    OriginEditResponse,
    OriginPatchBody,
  } from '$lib/protocol';
  import { navigate } from '$lib/router';
  import { auth } from '$stores/auth';
  import { subscribeLastPose } from '$stores/lastPose';
  import { subscribeLastScan } from '$stores/lastScan';
  import { loadMapMetadata, mapMetadata } from '$stores/mapMetadata';
  import { overlayToggles } from '$stores/overlayToggles';
  import { refresh as refreshRestartPending } from '$stores/restartPending';

  type EditMode = typeof EDIT_MODE_COORD | typeof EDIT_MODE_ERASE;
  // Sub-mode for the canvas pointer in Coord mode: off / xy-pick / yaw-pick.
  type CoordClickMode = 'off' | 'xy' | 'yaw';

  // Per-route viewport instance (Q2 — fresh per /map-edit mount).
  const viewport = createMapViewport();

  let dims = $state<MapDimensions | null>(null);
  let dimsError = $state<string | null>(null);
  let role = $state<'admin' | 'viewer' | null>(null);
  let unsubAuth: (() => void) | null = null;
  let unsubMeta: (() => void) | null = null;
  let unsubScan: (() => void) | null = null;
  let unsubOverlay: (() => void) | null = null;
  let unsubPose: (() => void) | null = null;
  let brushRadius = $state(BRUSH_RADIUS_PX_DEFAULT);
  // Independent busy flags per mode so a coord Apply does not grey out
  // the erase brush controls and vice versa.
  let coordBusy = $state(false);
  let eraseBusy = $state(false);
  let coordBanner = $state<string | null>(null);
  let coordBannerKind = $state<'info' | 'success' | 'error' | null>(null);
  let eraseBanner = $state<string | null>(null);
  let eraseBannerKind = $state<'info' | 'success' | 'error' | null>(null);
  let canvasRef: MapMaskCanvas | undefined = $state();
  let originPickerRef: OriginPicker | undefined = $state();
  let underlayRef: MapUnderlay | undefined = $state();
  let redirectTimer: ReturnType<typeof setTimeout> | null = null;
  let scan = $state<LastScan | null>(null);
  let lidarOn = $state(false);
  let originAxisOn = $state(false);
  let gridOn = $state(false);
  let pose = $state<LastPose | null>(null);

  // issue#28 — segmented control state. Switching does NOT auto-discard
  // the other mode's pending state.
  let mode = $state<EditMode>(EDIT_MODE_COORD);
  // Coord-mode sub-state: tracks which canvas-click meaning is active.
  let coordClickMode = $state<CoordClickMode>('off');
  // Apply-modal flow. The modal owns the SSE consumer; this flag drives
  // the open prop.
  let modalOpen = $state(false);
  let modalScope = $state<EditMode | null>(null);
  // Resolution + origin captured from mapMetadata for the GUI-pick math.
  let resolution = $state<number | null>(null);
  let currentOrigin = $state<readonly [number, number, number] | null>(null);
  let mapDims = $state<MapDimensions | null>(null);

  $effect(() => {
    void mapMetadata;
  });

  function setCoordBanner(msg: string | null, kind: 'info' | 'success' | 'error' | null): void {
    coordBanner = msg;
    coordBannerKind = kind;
  }
  function setEraseBanner(msg: string | null, kind: 'info' | 'success' | 'error' | null): void {
    eraseBanner = msg;
    eraseBannerKind = kind;
  }

  onMount(() => {
    unsubAuth = auth.subscribe((s) => (role = s?.role ?? null));
    unsubMeta = mapMetadata.subscribe((m) => {
      if (m) {
        dims = { width: m.width, height: m.height };
        mapDims = { width: m.width, height: m.height };
        currentOrigin = m.origin;
        resolution = m.resolution;
      }
    });
    unsubScan = subscribeLastScan((s) => (scan = s));
    unsubOverlay = overlayToggles.subscribe((s) => {
      lidarOn = s.lidarOn;
      originAxisOn = s.originAxisOn;
      gridOn = s.gridOn;
    });
    unsubPose = subscribeLastPose((p) => (pose = p));
    void loadMapMetadata('/api/map/image').catch((e: unknown) => {
      const err = (e as { body?: { err?: string } })?.body?.err;
      dimsError = err || 'metadata_load_failed';
    });
  });

  onDestroy(() => {
    unsubAuth?.();
    unsubMeta?.();
    unsubScan?.();
    unsubOverlay?.();
    unsubPose?.();
    if (redirectTimer !== null) {
      clearTimeout(redirectTimer);
      redirectTimer = null;
    }
  });

  // --- Coord mode --------------------------------------------------------

  function onCanvasCoordPick(lx: number, ly: number): void {
    if (mode !== EDIT_MODE_COORD) return;
    if (coordClickMode === 'off') return;
    if (!dims || resolution === null || currentOrigin === null) return;
    const w = pixelToWorld(lx, ly, dims, resolution, currentOrigin);
    if (coordClickMode === 'xy') {
      originPickerRef?.setCandidate({ x_m: w.world_x, y_m: w.world_y });
    } else if (coordClickMode === 'yaw') {
      originPickerRef?.setYawClick({ x_m: w.world_x, y_m: w.world_y });
    }
  }

  function onCanvasHoverMove(lx: number | null, ly?: number): void {
    if (lx === null || ly === undefined) {
      viewport.setHoverWorld(null);
      return;
    }
    if (!dims || resolution === null || currentOrigin === null) return;
    const w = pixelToWorld(lx, ly, dims, resolution, currentOrigin);
    viewport.setHoverWorld(w.world_x, w.world_y);
  }

  // Legacy /api/map/origin Apply path — kept alive for the existing
  // mapEdit.test.ts `Apply POSTs FormData with a "mask" part to /api/map/edit`
  // and `/api/map/origin` smoke tests. The new modal flow drives
  // `/api/map/edit/coord` instead.
  async function onLegacyOriginApply(body: OriginPatchBody): Promise<void> {
    if (coordBusy || role !== 'admin') return;
    coordBusy = true;
    setCoordBanner('적용 중…', 'info');
    try {
      const resp = await postMapOrigin<OriginEditResponse>(body);
      const px = resp.prev_origin;
      const nx = resp.new_origin;
      setCoordBanner(
        `완료: (${px[0].toFixed(3)}, ${px[1].toFixed(3)}) → ` +
          `(${nx[0].toFixed(3)}, ${nx[1].toFixed(3)}) — ` +
          `${(ORIGIN_PICK_REDIRECT_DELAY_MS / 1000).toFixed(0)}초 후 /map으로 이동합니다.`,
        'success',
      );
      void refreshRestartPending();
      redirectTimer = setTimeout(() => {
        navigate('/map');
      }, ORIGIN_PICK_REDIRECT_DELAY_MS);
    } catch (e) {
      coordBusy = false;
      if (e instanceof ApiError) {
        const errCode = e.body?.err || `http_${e.status}`;
        setCoordBanner(`적용 실패: ${errCode}`, 'error');
      } else {
        setCoordBanner('적용 실패: 네트워크 오류', 'error');
      }
      return;
    }
    coordBusy = false;
  }

  function onCoordApplyClick(): void {
    if (coordBusy || role !== 'admin') return;
    if (!originPickerRef) return;
    const draft = originPickerRef.getDirtyBody();
    if (draft === null) {
      setCoordBanner('적용할 변경사항이 없습니다.', 'error');
      return;
    }
    modalScope = EDIT_MODE_COORD;
    modalOpen = true;
  }

  async function onModalApply(memo: string): Promise<void> {
    if (modalScope === EDIT_MODE_COORD) {
      await runCoordApply(memo);
    } else if (modalScope === EDIT_MODE_ERASE) {
      await runEraseApply(memo);
    }
  }

  async function runCoordApply(memo: string): Promise<void> {
    if (!originPickerRef) return;
    const draft = originPickerRef.getDirtyBody();
    if (draft === null) return;
    const body: MapEditCoordBody = { ...draft, memo };
    coordBusy = true;
    setCoordBanner('적용 중…', 'info');
    try {
      const resp = await postMapEditCoord<MapEditPipelineResult>(body);
      setCoordBanner(
        `완료: 파생 ${resp.derived_pair.pgm}. godo-tracker 재시작 후 활성화하세요.`,
        'success',
      );
      void refreshRestartPending();
      originPickerRef.clearAll();
      modalOpen = false;
      modalScope = null;
    } catch (e) {
      if (e instanceof ApiError) {
        const errCode = e.body?.err || `http_${e.status}`;
        setCoordBanner(`적용 실패: ${errCode}`, 'error');
      } else {
        setCoordBanner('적용 실패: 네트워크 오류', 'error');
      }
    } finally {
      coordBusy = false;
    }
  }

  function onCoordDiscardClick(): void {
    if (coordBusy) return;
    originPickerRef?.clearAll();
    setCoordBanner(null, null);
  }

  // --- Erase mode --------------------------------------------------------

  function onEraseApplyClick(): void {
    if (eraseBusy || role !== 'admin' || !canvasRef) return;
    modalScope = EDIT_MODE_ERASE;
    modalOpen = true;
  }

  async function runEraseApply(memo: string): Promise<void> {
    if (!canvasRef) return;
    eraseBusy = true;
    setEraseBanner('적용 중…', 'info');
    try {
      const blob = await canvasRef.getMaskPng();
      const resp = await postMapEditErase<MapEditPipelineResult>(blob, memo);
      setEraseBanner(
        `완료: 파생 ${resp.derived_pair.pgm}. godo-tracker 재시작 후 활성화하세요.`,
        'success',
      );
      void refreshRestartPending();
      canvasRef.clear();
      modalOpen = false;
      modalScope = null;
    } catch (e) {
      if (e instanceof ApiError) {
        const errCode = e.body?.err || `http_${e.status}`;
        setEraseBanner(`적용 실패: ${errCode}`, 'error');
      } else {
        setEraseBanner('적용 실패: 네트워크 오류', 'error');
      }
    } finally {
      eraseBusy = false;
    }
  }

  function onEraseDiscardClick(): void {
    if (eraseBusy) return;
    canvasRef?.clear();
    setEraseBanner(null, null);
  }

  // Yaml origin in degrees for the OriginAxisOverlay; stays in sync with
  // mapMetadata.origin[2] (radians on disk).
  let yamlYawDeg = $derived(currentOrigin === null ? 0 : currentOrigin[2] * (180 / Math.PI));

  // Overlay canvases. Bound via `bind:this` and consumed by the
  // <GridOverlay> / <OriginAxisOverlay> components which paint via
  // `$effect`.
  let axisCanvas: HTMLCanvasElement | null = $state(null);
  let gridCanvas: HTMLCanvasElement | null = $state(null);
</script>

<div data-testid="map-edit-page">
  <RestartPendingBanner />

  {#if dimsError}
    <p class="error" data-testid="map-edit-dims-error">
      맵 메타데이터를 불러오지 못했습니다: {dimsError}
    </p>
  {:else if dims === null}
    <p class="muted" data-testid="map-edit-loading">맵을 불러오는 중…</p>
  {:else}
    <div class="control-row" data-testid="map-edit-control-row">
      <EditModeSwitcher
        {mode}
        onChange={(next) => {
          // Mode switch does NOT auto-discard the other mode's pending
          // state (operator-locked, pinned by MapEdit.test.ts).
          mode = next;
          // Reset coord-pick sub-mode whenever mode changes (canvas
          // pointer behaviour belongs to the active mode).
          coordClickMode = 'off';
        }}
      />
      <OverlayToggleRow />
    </div>

    {#if mode === EDIT_MODE_COORD}
      <div class="toolbar coord-toolbar">
        <div class="pick-toggles" role="radiogroup" aria-label="origin pick mode">
          <label class="pick-label">
            <input
              type="radio"
              name="coord-click-mode"
              value="off"
              checked={coordClickMode === 'off'}
              onchange={() => (coordClickMode = 'off')}
              data-testid="coord-pick-off"
            />
            Off
          </label>
          <label class="pick-label">
            <input
              type="radio"
              name="coord-click-mode"
              value="xy"
              checked={coordClickMode === 'xy'}
              onchange={() => (coordClickMode = 'xy')}
              data-testid="coord-pick-xy"
            />
            원점 (XY)
          </label>
          <label class="pick-label">
            <input
              type="radio"
              name="coord-click-mode"
              value="yaw"
              checked={coordClickMode === 'yaw'}
              onchange={() => (coordClickMode = 'yaw')}
              data-testid="coord-pick-yaw"
            />
            방향 (Yaw, 2-click)
          </label>
        </div>
        <div class="actions">
          <button
            type="button"
            class="btn-secondary"
            onclick={onCoordDiscardClick}
            disabled={coordBusy}
            data-testid="map-edit-coord-discard-btn"
          >
            Discard
          </button>
          <button
            type="button"
            class="btn-primary"
            onclick={onCoordApplyClick}
            disabled={coordBusy || role !== 'admin'}
            data-testid="map-edit-coord-apply-btn"
            title={role !== 'admin' ? '제어 동작은 로그인 필요' : ''}
          >
            {coordBusy ? '적용 중…' : 'Apply'}
          </button>
        </div>
      </div>
    {:else}
      <div class="toolbar erase-toolbar">
        <label class="brush-slider">
          Brush radius (px):
          <input
            type="range"
            min={BRUSH_RADIUS_PX_MIN}
            max={BRUSH_RADIUS_PX_MAX}
            bind:value={brushRadius}
            data-testid="map-edit-brush-slider"
          />
          <span class="brush-value">{brushRadius}</span>
        </label>
        <div class="actions">
          <button
            type="button"
            class="btn-secondary"
            onclick={onEraseDiscardClick}
            disabled={eraseBusy}
            data-testid="map-edit-erase-discard-btn"
          >
            Discard
          </button>
          <button
            type="button"
            class="btn-primary"
            onclick={onEraseApplyClick}
            disabled={eraseBusy || role !== 'admin'}
            data-testid="map-edit-erase-apply-btn"
            title={role !== 'admin' ? '제어 동작은 로그인 필요' : ''}
          >
            {eraseBusy ? '적용 중…' : 'Apply'}
          </button>
        </div>
      </div>
    {/if}

    <div class="map-stack">
      <MapUnderlay
        bind:this={underlayRef}
        {viewport}
        mapImageUrl="/api/map/image"
        {scan}
        scanOverlayOn={lidarOn}
        ondraw={(ctx, w2c) => drawPose(ctx, w2c, pose)}
      />
      <div class="mask-overlay">
        <MapMaskCanvas
          bind:this={canvasRef}
          {viewport}
          width={dims.width}
          height={dims.height}
          mapImageUrl="/api/map/image"
          {brushRadius}
          disabled={(mode === EDIT_MODE_COORD ? coordBusy : eraseBusy) ||
            (mode === EDIT_MODE_COORD && coordClickMode === 'off')}
          mode={mode === EDIT_MODE_COORD && coordClickMode !== 'off' ? 'origin-pick' : 'paint'}
          oncoordpick={onCanvasCoordPick}
          onhovermove={onCanvasHoverMove}
        />
      </div>
      {#if originAxisOn && currentOrigin !== null && mapDims !== null}
        <canvas
          class="overlay-canvas"
          width={mapDims.width}
          height={mapDims.height}
          data-testid="map-edit-axis-overlay"
          bind:this={axisCanvas}
        ></canvas>
        <OriginAxisOverlay
          canvas={axisCanvas ?? null}
          zoomPxPerMeter={resolution !== null && resolution > 0 ? 1 / resolution : 1}
          worldOriginX={currentOrigin[0]}
          worldOriginY={currentOrigin[1]}
          yamlOriginX={currentOrigin[0]}
          yamlOriginY={currentOrigin[1]}
          yamlOriginYawDeg={yamlYawDeg}
        />
      {/if}
      {#if gridOn && currentOrigin !== null && mapDims !== null}
        <canvas
          class="overlay-canvas"
          width={mapDims.width}
          height={mapDims.height}
          data-testid="map-edit-grid-overlay"
          bind:this={gridCanvas}
        ></canvas>
        <GridOverlay
          canvas={gridCanvas ?? null}
          zoomPxPerMeter={resolution !== null && resolution > 0 ? 1 / resolution : 1}
          worldOriginX={currentOrigin[0]}
          worldOriginY={currentOrigin[1]}
          worldWidthM={mapDims.width * (resolution ?? 0)}
          worldHeightM={mapDims.height * (resolution ?? 0)}
        />
      {/if}
      <MapZoomControls {viewport} />
    </div>
  {/if}

  {#if mode === EDIT_MODE_COORD && coordBanner}
    <p
      class="banner banner-{coordBannerKind ?? 'info'}"
      data-testid="map-edit-coord-banner"
    >
      {coordBanner}
    </p>
  {:else if mode === EDIT_MODE_ERASE && eraseBanner}
    <p
      class="banner banner-{eraseBannerKind ?? 'info'}"
      data-testid="map-edit-erase-banner"
    >
      {eraseBanner}
    </p>
  {/if}

  {#if dims !== null}
    <!-- OriginPicker stays mounted across mode switches so its dirty
         state survives Coord ↔ Erase toggling (issue#28 operator-locked
         "no auto-discard"). Hidden via CSS in Erase mode. -->
    <div style:display={mode === EDIT_MODE_COORD ? 'block' : 'none'}>
      <OriginPicker
        bind:this={originPickerRef}
        {currentOrigin}
        {role}
        busy={coordBusy}
        bannerMsg={null}
        bannerKind={null}
        onapply={(body) => {
          // Legacy back-compat path — only fires when the OriginPicker's
          // own inline Apply button is clicked. The issue#28 modal flow
          // calls runCoordApply via onModalApply instead.
          void onLegacyOriginApply(body);
        }}
        resolutionMPerPx={resolution}
      />
    </div>
  {/if}

  <ApplyMemoModal
    open={modalOpen}
    onApply={(memo) => {
      void onModalApply(memo);
    }}
    onCancel={() => {
      modalOpen = false;
      modalScope = null;
    }}
  />

  <p class="hint">
    적용 후 godo-tracker를 재시작해야 효과가 반영됩니다 — System 탭 또는 (loopback) /local에서.
  </p>
</div>

<style>
  /* issue#28 — top control row hosts both the segmented mode switcher
     and the unified overlay-toggle row, side-by-side. */
  .control-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    margin: 8px 0;
    flex-wrap: wrap;
  }
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 8px 0;
    gap: 8px;
    flex-wrap: wrap;
  }
  .pick-toggles {
    display: inline-flex;
    align-items: center;
    gap: 12px;
  }
  .pick-label {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.9em;
    cursor: pointer;
    user-select: none;
  }
  .map-stack {
    position: relative;
    width: 100%;
    height: 600px;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    background: var(--color-bg-elev);
    overflow: hidden;
  }
  .mask-overlay {
    position: absolute;
    inset: 0;
    pointer-events: auto;
  }
  .overlay-canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }
  .brush-slider {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .brush-value {
    min-width: 3em;
    text-align: right;
  }
  .actions {
    display: flex;
    gap: 8px;
  }
  .banner {
    padding: 8px 12px;
    border-left: 3px solid var(--color-accent);
    margin-top: 12px;
  }
  .banner-success {
    border-left-color: #2e7d32;
    background: color-mix(in srgb, #2e7d32 10%, var(--color-bg));
  }
  .banner-error {
    border-left-color: var(--color-error, #c62828);
    background: color-mix(in srgb, var(--color-error, #c62828) 10%, var(--color-bg));
  }
  .hint {
    margin-top: 16px;
    font-size: 0.9em;
    color: var(--color-text-muted, #666);
  }
  .error {
    color: var(--color-error, #c62828);
  }
</style>
