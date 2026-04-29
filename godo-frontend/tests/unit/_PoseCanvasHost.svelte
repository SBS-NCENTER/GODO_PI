<script lang="ts">
  import PoseCanvas from '../../src/components/PoseCanvas.svelte';
  import type { LastPose } from '../../src/lib/protocol';
  // Test host that forwards a reactive `mapImageUrl` to PoseCanvas.
  // Used by `poseCanvasImageReload.test.ts`.
  //
  // The host carries an internal `$state` and exports a `setUrl(s)`
  // function so the test can mutate it from the OUTSIDE. Mutating
  // `$state` re-renders PoseCanvas; the `$effect(() => mapImageUrl)`
  // inside PoseCanvas then re-runs and triggers a fresh image fetch.

  interface Props {
    pose: LastPose | null;
    initialUrl: string;
  }
  let { pose = null, initialUrl = '/api/map/image' }: Props = $props();

  let url = $state(initialUrl);

  export function setUrl(next: string): void {
    url = next;
  }
</script>

<PoseCanvas {pose} mapImageUrl={url} />
