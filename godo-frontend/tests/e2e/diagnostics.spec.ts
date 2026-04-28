import { expect, test } from '@playwright/test';

test('diagnostics: /diag route renders the page header', async ({ page }) => {
  await page.goto('/#/diag');
  await expect(page.locator('[data-testid="diag-page"]')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('h2')).toContainText('Diagnostics');
});

test('diagnostics: all four sub-panels are visible after load', async ({ page }) => {
  await page.goto('/#/diag');
  await expect(page.locator('[data-testid="panel-pose"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-jitter"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-amcl-rate"]')).toBeVisible();
  await expect(page.locator('[data-testid="panel-journal"]')).toBeVisible();
});

test('diagnostics: pose + jitter chips populate from the SSE frame after login', async ({
  page,
}) => {
  // Log in so the SSE token gate opens (the stub's /api/diag/stream is
  // anon, but the SPA's SSEClient still requires a non-expired token).
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await page.goto('/#/diag');
  // The stub emits 3 SSE frames at ~50 ms cadence; the first frame
  // populates the jitter panel within ~5 s.
  await expect(page.locator('[data-testid="panel-jitter"]')).toContainText('p50', {
    timeout: 5000,
  });
});

test('diagnostics: journal-tail allow-list dropdown has three entries', async ({ page }) => {
  await page.goto('/#/diag');
  const select = page.locator('[data-testid="journal-unit"]');
  await expect(select).toBeVisible();
  const opts = await select.locator('option').allTextContents();
  expect(opts).toEqual(['godo-tracker', 'godo-webctl', 'godo-irq-pin']);
});

test('diagnostics: journal-tail Refresh button fetches lines', async ({ page }) => {
  await page.goto('/#/diag');
  await page.click('[data-testid="journal-refresh"]');
  await expect(page.locator('[data-testid="journal-body"]')).toContainText('log line 0', {
    timeout: 5000,
  });
});
