import { expect, test } from '@playwright/test';

test('system: happy path renders all four panels with SSE-fed resources', async ({ page }) => {
  // Log in first so the SSEClient token gate opens — the stub's
  // /api/diag/stream is anon-readable, but the SPA still requires a
  // non-expired token to construct the EventSource URL. Same pattern
  // as `diagnostics.spec.ts::pose + jitter chips populate ...`.
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await page.goto('/#/system');
  await expect(page.locator('[data-testid="system-page"]')).toBeVisible({ timeout: 5000 });

  // (a) CPU temperature sparkline panel — selector scoped (N1 fold) so
  // it never collides with /diag's own sparkline.
  const cpuPanel = page.getByTestId('panel-cpu-temp');
  await expect(cpuPanel).toBeVisible();
  await expect(cpuPanel.getByTestId('diag-sparkline')).toBeVisible();

  // (b) Resources panel renders mem + disk numbers from the SSE frame.
  const resources = page.getByTestId('panel-resources');
  await expect(resources).toBeVisible();
  await expect(resources.getByTestId('resources-mem')).toContainText('GiB', { timeout: 5000 });
  await expect(resources.getByTestId('resources-disk')).toContainText('GiB');

  // (c) Journal tail panel is visible with its empty-state placeholder.
  const journal = page.getByTestId('panel-journal');
  await expect(journal).toBeVisible();
  await expect(journal.getByTestId('journal-empty')).toContainText(
    'Refresh를 눌러 로그를 불러오세요.',
  );
});

test('system: anon viewer sees disabled reboot button + verbatim hint', async ({ page }) => {
  await page.goto('/#/system');
  await expect(page.locator('[data-testid="system-page"]')).toBeVisible();

  await expect(page.locator('[data-testid="reboot-btn"]')).toBeDisabled();
  await expect(page.locator('[data-testid="shutdown-btn"]')).toBeDisabled();
  await expect(page.locator('[data-testid="anon-hint"]')).toContainText(
    '제어 동작은 로그인이 필요합니다.',
  );
});

test('system: sidebar nav link routes to /system', async ({ page }) => {
  await page.goto('/');
  await page.click('[data-testid="nav-system"]');
  await expect(page).toHaveURL(/#\/system$/);
  await expect(page.locator('[data-testid="system-page"]')).toBeVisible();
});

// --- Track B-SYSTEM PR-2 — service observability ----------------------

test('system: services panel renders 3 cards after navigation', async ({ page }) => {
  await page.goto('/#/system');
  await expect(page.locator('[data-testid="panel-services"]')).toBeVisible();
  // Stub returns 3 canned services; each card has a deterministic test-id.
  await expect(page.locator('[data-testid="service-status-card-godo-tracker"]')).toBeVisible();
  await expect(page.locator('[data-testid="service-status-card-godo-webctl"]')).toBeVisible();
  await expect(page.locator('[data-testid="service-status-card-godo-irq-pin"]')).toBeVisible();
});

test('system: env collapse reveals one redacted KEY + one non-redacted KEY (T6 fold)', async ({
  page,
}) => {
  await page.goto('/#/system');
  await expect(page.locator('[data-testid="panel-services"]')).toBeVisible();

  // Open the env <details> on the godo-tracker card; the canned stub
  // includes JWT_SECRET=<redacted> AND GODO_LOG_DIR=/var/log/godo.
  const card = page.locator('[data-testid="service-status-card-godo-tracker"]');
  const summary = card.locator('details > summary');
  await summary.click();

  // Redacted row carries a `(secret)` tag with a deterministic test-id.
  await expect(card.locator('[data-testid="env-secret-JWT_SECRET"]')).toContainText('(secret)');
  // Non-redacted row renders the plain value verbatim.
  await expect(card.locator('[data-testid="env-row-GODO_LOG_DIR"]')).toContainText('/var/log/godo');
});

test('system: admin clicks restart, stubbed 409 toast renders Korean detail', async ({ page }) => {
  // Login first so we have an admin token; flip the stub flag so the
  // next /api/system/service/* POST returns 409 service_starting.
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await page.goto('/?stub_svc_409=starting#/system');
  await expect(page.locator('[data-testid="panel-services"]')).toBeVisible();

  const card = page.locator('[data-testid="service-status-card-godo-tracker"]');
  await card.locator('[data-testid="svc-action-restart-godo-tracker"]').click();

  await expect(card.locator('[data-testid="svc-error-godo-tracker"]')).toContainText(
    '시동 중입니다',
  );
});
