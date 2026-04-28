<script lang="ts">
  import type { Mode } from '$lib/protocol';
  import { MODE_IDLE, MODE_LIVE, MODE_ONESHOT } from '$lib/protocol';

  interface Props {
    mode: Mode | null;
  }
  let { mode }: Props = $props();

  const labelMap: Record<Mode, string> = {
    [MODE_IDLE]: 'Idle',
    [MODE_ONESHOT]: 'OneShot',
    [MODE_LIVE]: 'Live',
  };

  const classMap: Record<Mode, string> = {
    [MODE_IDLE]: 'idle',
    [MODE_ONESHOT]: 'warn',
    [MODE_LIVE]: 'ok',
  };
</script>

{#if mode === null}
  <span class="chip idle" data-testid="mode-chip">unknown</span>
{:else}
  <span class="chip {classMap[mode]}" data-testid="mode-chip">{labelMap[mode]}</span>
{/if}
