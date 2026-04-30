<script lang="ts">
  /**
   * Track B-MAPEDIT — `/map-edit` route.
   *
   * Renders the active map underlay + brush surface + Apply / Discard
   * controls. Apply path:
   *   1. Build a PNG blob from MapMaskCanvas's `getMaskPng()`.
   *   2. POST /api/map/edit (multipart) via `postMapEdit`.
   *   3. On 200: show success toast, refresh the restart-pending flag,
   *      navigate back to /map after MAP_EDIT_REDIRECT_DELAY_MS.
   *   4. On 4xx: render the response's `err` string inline; brush state
   *      is preserved so the operator can retry without redrawing.
   *
   * Anonymous viewers see the page (READ-only) but the Apply button is
   * disabled. The backend separately enforces 401 on the POST.
   *
   * The brush radius is held in this component (not the child) so that
   * the slider can drive the child's brush size prop without round-trip.
   * Mask state lives ENTIRELY inside `<MapMaskCanvas/>` per
   * CODEBASE.md invariant (u).
   */
  import { onDestroy, onMount } from 'svelte';

  import MapMaskCanvas from '$components/MapMaskCanvas.svelte';
  import OriginPicker from '$components/OriginPicker.svelte';
  import RestartPendingBanner from '$components/RestartPendingBanner.svelte';
  import { ApiError, postMapEdit, postMapOrigin } from '$lib/api';
  import {
    BRUSH_RADIUS_PX_DEFAULT,
    BRUSH_RADIUS_PX_MAX,
    BRUSH_RADIUS_PX_MIN,
    MAP_EDIT_REDIRECT_DELAY_MS,
    ORIGIN_PICK_REDIRECT_DELAY_MS,
  } from '$lib/constants';
  import { pixelToWorld } from '$lib/originMath';
  import type {
    EditResponse,
    MapDimensions,
    OriginEditResponse,
    OriginPatchBody,
  } from '$lib/protocol';
  import { navigate } from '$lib/router';
  import { auth } from '$stores/auth';
  import { loadMapMetadata, mapMetadata } from '$stores/mapMetadata';
  import { refresh as refreshRestartPending } from '$stores/restartPending';

  let dims = $state<MapDimensions | null>(null);
  let dimsError = $state<string | null>(null);
  let role = $state<'admin' | 'viewer' | null>(null);
  let unsubAuth: (() => void) | null = null;
  let unsubMeta: (() => void) | null = null;
  let brushRadius = $state(BRUSH_RADIUS_PX_DEFAULT);
  let busy = $state(false);
  let banner = $state<string | null>(null);
  let bannerKind = $state<'info' | 'success' | 'error'>('info');
  let canvasRef: MapMaskCanvas | undefined = $state();
  let originPickerRef: OriginPicker | undefined = $state();
  let redirectTimer: ReturnType<typeof setTimeout> | null = null;

  // Track B-MAPEDIT-2 — origin pick state.
  let originPickEnabled = $state(false);
  let originBusy = $state(false);
  let originBanner = $state<string | null>(null);
  let originBannerKind = $state<'info' | 'success' | 'error' | null>(null);
  let currentOrigin = $state<readonly [number, number, number] | null>(null);
  // Resolution + origin captured from mapMetadata for the GUI-pick math.
  let resolution = $state<number | null>(null);

  $effect(() => {
    void mapMetadata;
  });

  function fmtRedirectMs(ms: number): string {
    return `${(ms / 1000).toFixed(0)}초`;
  }

  function setBanner(msg: string, kind: 'info' | 'success' | 'error'): void {
    banner = msg;
    bannerKind = kind;
  }

  onMount(() => {
    unsubAuth = auth.subscribe((s) => (role = s?.role ?? null));
    unsubMeta = mapMetadata.subscribe((m) => {
      if (m) {
        dims = { width: m.width, height: m.height };
        currentOrigin = m.origin;
        resolution = m.resolution;
      }
    });
    // The /map page also calls loadMapMetadata; calling here too is
    // idempotent (same store, abort-cancellable). Without this,
    // operators landing on /map-edit directly would see "loading…"
    // forever.
    void loadMapMetadata('/api/map/image').catch((e: unknown) => {
      const err = (e as { body?: { err?: string } })?.body?.err;
      dimsError = err || 'metadata_load_failed';
    });
  });

  onDestroy(() => {
    unsubAuth?.();
    unsubMeta?.();
    if (redirectTimer !== null) {
      clearTimeout(redirectTimer);
      redirectTimer = null;
    }
  });

  async function onApply(): Promise<void> {
    if (busy || !canvasRef || role !== 'admin') return;
    busy = true;
    setBanner('적용 중…', 'info');
    try {
      const blob = await canvasRef.getMaskPng();
      const resp = await postMapEdit<EditResponse>(blob);
      setBanner(
        `완료: ${resp.pixels_changed} 셀 변경 — ${fmtRedirectMs(MAP_EDIT_REDIRECT_DELAY_MS)} 후 /map으로 이동합니다. ` +
          `적용은 godo-tracker 재시작 후 (System 탭 또는 /local).`,
        'success',
      );
      void refreshRestartPending();
      redirectTimer = setTimeout(() => {
        navigate('/map');
      }, MAP_EDIT_REDIRECT_DELAY_MS);
    } catch (e) {
      busy = false;
      if (e instanceof ApiError) {
        const errCode = e.body?.err || `http_${e.status}`;
        setBanner(`적용 실패: ${errCode}`, 'error');
      } else {
        setBanner('적용 실패: 네트워크 오류', 'error');
      }
      return;
    }
    busy = false;
  }

  function onDiscard(): void {
    if (busy) return;
    canvasRef?.clear();
    banner = null;
  }

  // Track B-MAPEDIT-2 — GUI-pick: convert logical pixel → world coords
  // using the active map's resolution + origin, pre-fill the picker.
  function onCanvasCoordPick(lx: number, ly: number): void {
    if (!dims || resolution === null || currentOrigin === null) return;
    const w = pixelToWorld(lx, ly, dims, resolution, currentOrigin);
    originPickerRef?.setCandidate({ x_m: w.world_x, y_m: w.world_y });
  }

  async function onOriginApply(body: OriginPatchBody): Promise<void> {
    if (originBusy || role !== 'admin') return;
    originBusy = true;
    originBanner = '적용 중…';
    originBannerKind = 'info';
    try {
      const resp = await postMapOrigin<OriginEditResponse>(body);
      const px = resp.prev_origin;
      const nx = resp.new_origin;
      originBanner =
        `완료: (${px[0].toFixed(3)}, ${px[1].toFixed(3)}) → ` +
        `(${nx[0].toFixed(3)}, ${nx[1].toFixed(3)}) — ` +
        `${(ORIGIN_PICK_REDIRECT_DELAY_MS / 1000).toFixed(0)}초 후 /map으로 이동합니다. ` +
        `적용은 godo-tracker 재시작 후.`;
      originBannerKind = 'success';
      void refreshRestartPending();
      redirectTimer = setTimeout(() => {
        navigate('/map');
      }, ORIGIN_PICK_REDIRECT_DELAY_MS);
    } catch (e) {
      originBusy = false;
      if (e instanceof ApiError) {
        const errCode = e.body?.err || `http_${e.status}`;
        originBanner = `적용 실패: ${errCode}`;
      } else {
        originBanner = '적용 실패: 네트워크 오류';
      }
      originBannerKind = 'error';
      return;
    }
    originBusy = false;
  }
</script>

<div data-testid="map-edit-page">
  <!-- Top-level breadcrumb + h2 live on the parent Map.svelte (the
       brush editor is now an Edit sub-tab inside the Map page). The
       data-testid is preserved so the existing e2e + unit tests
       continue to anchor on this container. -->
  <RestartPendingBanner />

  {#if dimsError}
    <p class="error" data-testid="map-edit-dims-error">
      맵 메타데이터를 불러오지 못했습니다: {dimsError}
    </p>
  {:else if dims === null}
    <p class="muted" data-testid="map-edit-loading">맵을 불러오는 중…</p>
  {:else}
    <div class="toolbar">
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
          onclick={onDiscard}
          disabled={busy}
          data-testid="map-edit-discard-btn"
        >
          Discard
        </button>
        <button
          type="button"
          class="btn-primary"
          onclick={onApply}
          disabled={busy || role !== 'admin'}
          data-testid="map-edit-apply-btn"
          title={role !== 'admin' ? '제어 동작은 로그인 필요' : ''}
        >
          {busy ? '적용 중…' : 'Apply'}
        </button>
      </div>
    </div>

    <MapMaskCanvas
      bind:this={canvasRef}
      width={dims.width}
      height={dims.height}
      mapImageUrl="/api/map/image"
      {brushRadius}
      disabled={busy || originBusy}
      mode={originPickEnabled ? 'origin-pick' : 'paint'}
      oncoordpick={onCanvasCoordPick}
    />
  {/if}

  {#if banner}
    <p class="banner banner-{bannerKind}" data-testid="map-edit-banner">{banner}</p>
  {/if}

  {#if dims !== null}
    <label class="pick-toggle" data-testid="origin-pick-toggle-label">
      <input
        type="checkbox"
        bind:checked={originPickEnabled}
        disabled={busy || originBusy}
        data-testid="origin-pick-toggle"
      />
      Click on canvas to pre-fill (origin-pick mode)
    </label>

    <OriginPicker
      bind:this={originPickerRef}
      {currentOrigin}
      {role}
      busy={originBusy}
      bannerMsg={originBanner}
      bannerKind={originBannerKind}
      onapply={(body) => {
        void onOriginApply(body);
      }}
    />
  {/if}

  <p class="hint">
    적용 후 godo-tracker를 재시작해야 효과가 반영됩니다 — System 탭 또는 (loopback) /local에서.
  </p>
</div>

<style>
  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 8px 0;
    gap: 8px;
    flex-wrap: wrap;
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
  .pick-toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    margin-top: 12px;
    font-size: 0.9em;
  }
</style>
