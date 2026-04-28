<script lang="ts">
  interface Props {
    open: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  }
  let {
    open,
    title,
    message,
    confirmLabel = '확인',
    cancelLabel = '취소',
    danger = false,
    onConfirm,
    onCancel,
  }: Props = $props();
</script>

{#if open}
  <div
    class="confirm-overlay"
    role="dialog"
    aria-modal="true"
    aria-labelledby="confirm-title"
    data-testid="confirm-dialog"
  >
    <div class="confirm-card">
      <h3 id="confirm-title">{title}</h3>
      <p>{message}</p>
      <div class="hstack" style="justify-content: flex-end; margin-top: 16px;">
        <button onclick={onCancel} data-testid="confirm-cancel">{cancelLabel}</button>
        <button class={danger ? 'danger' : 'primary'} onclick={onConfirm} data-testid="confirm-ok"
          >{confirmLabel}</button
        >
      </div>
    </div>
  </div>
{/if}

<style>
  .confirm-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.4);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 200;
  }
  .confirm-card {
    background: var(--color-bg-elev);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: var(--space-5);
    min-width: 320px;
    max-width: 480px;
    box-shadow: var(--shadow-card);
  }
  h3 {
    margin: 0 0 var(--space-3) 0;
    font-size: var(--font-size-lg);
  }
  p {
    margin: 0;
    color: var(--color-text);
  }
</style>
