<script lang="ts">
  /**
   * Track E (PR-C) extension: optional `secondaryAction` prop.
   * When set, the dialog renders three buttons: cancel / secondary /
   * primary. Used by `MapListPanel` activate dialog to offer
   * "재시작하지 않음" (secondary) vs "godo-tracker 재시작" (primary).
   * The cancel button is always rendered.
   */
  interface SecondaryAction {
    label: string;
    handler: () => void;
  }

  interface Props {
    open: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onConfirm: () => void;
    onCancel: () => void;
    /** Optional 3rd button between cancel and confirm. */
    secondaryAction?: SecondaryAction | null;
    /** When false, the primary (`onConfirm`) button is hidden entirely.
     * Used by the activate dialog on non-loopback hostnames per Mode-A
     * M4: the SPA cannot trigger a tracker restart over the LAN, so
     * the button collapses and only cancel + secondary remain. */
    showPrimary?: boolean;
    /** Tooltip shown on the placeholder area where the primary button
     * would have been, when `showPrimary === false`. */
    primaryHiddenTooltip?: string;
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
    secondaryAction = null,
    showPrimary = true,
    primaryHiddenTooltip = '',
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
        {#if secondaryAction}
          <button onclick={secondaryAction.handler} data-testid="confirm-secondary">
            {secondaryAction.label}
          </button>
        {/if}
        {#if showPrimary}
          <button
            class={danger ? 'danger' : 'primary'}
            onclick={onConfirm}
            data-testid="confirm-ok"
          >
            {confirmLabel}
          </button>
        {:else}
          <span
            class="primary-placeholder"
            data-testid="confirm-primary-hidden"
            title={primaryHiddenTooltip}
          >
            ({primaryHiddenTooltip})
          </span>
        {/if}
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
  .primary-placeholder {
    color: var(--color-text-muted, #666);
    font-style: italic;
    padding: 4px 8px;
  }
</style>
