<script lang="ts">
  /**
   * issue#14 — Live preview canvas.
   *
   * Cache-busts `/api/mapping/preview?ts=<unix>` at 1 Hz. The webctl
   * endpoint re-encodes the on-disk PGM to PNG (D5) so the browser
   * renders without any custom decoder.
   */

  import { onDestroy, onMount } from 'svelte';
  import { MAPPING_PREVIEW_REFRESH_MS } from '$lib/constants';

  interface Props {
    mapName: string;
  }
  let { mapName }: Props = $props();

  let src = $state(`/api/mapping/preview?ts=${Date.now()}`);
  let timer: ReturnType<typeof setInterval> | null = null;
  let imgError = $state(false);

  function bumpUrl(): void {
    imgError = false;
    src = `/api/mapping/preview?ts=${Date.now()}`;
  }

  onMount(() => {
    timer = setInterval(bumpUrl, MAPPING_PREVIEW_REFRESH_MS);
  });

  onDestroy(() => {
    if (timer !== null) clearInterval(timer);
  });

  function onError(): void {
    imgError = true;
  }
</script>

<section class="preview" data-testid="mapping-preview">
  <h4>미리보기 — {mapName}</h4>
  {#if imgError}
    <p class="muted">아직 미리보기 PGM이 발행되지 않았습니다 (1초 후 재시도).</p>
  {:else}
    <img
      class="canvas"
      {src}
      alt="mapping preview {mapName}"
      onerror={onError}
    />
  {/if}
</section>

<style>
  .preview {
    margin: var(--space-2) 0;
  }
  .canvas {
    display: block;
    max-width: 100%;
    border: 1px solid var(--color-border);
    image-rendering: pixelated;
  }
  .muted {
    opacity: 0.7;
  }
</style>
