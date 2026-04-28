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
