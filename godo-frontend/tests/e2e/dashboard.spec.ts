import { expect, test } from '@playwright/test';

async function loginAs(page: import('@playwright/test').Page, user: 'ncenter' | 'viewer') {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', user);
  await page.fill('[data-testid="login-password"]', user);
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible({ timeout: 5000 });
}

test('dashboard: admin sees enabled action buttons', async ({ page }) => {
  await loginAs(page, 'ncenter');
  await expect(page.locator('[data-testid="calibrate-btn"]')).toBeEnabled();
  await expect(page.locator('[data-testid="live-btn"]')).toBeEnabled();
  await expect(page.locator('[data-testid="backup-btn"]')).toBeEnabled();
});

test('dashboard: viewer sees disabled action buttons', async ({ page }) => {
  await loginAs(page, 'viewer');
  await expect(page.locator('[data-testid="calibrate-btn"]')).toBeDisabled();
  await expect(page.locator('[data-testid="live-btn"]')).toBeDisabled();
  await expect(page.locator('[data-testid="backup-btn"]')).toBeDisabled();
});

test('dashboard: mode chip reflects /api/health', async ({ page }) => {
  await loginAs(page, 'ncenter');
  // Initial mode = Idle (per stub).
  await expect(page.locator('[data-testid="mode-chip"]')).toContainText('Idle', { timeout: 3000 });
  // Click Live → toggles. Stub flips current_mode to "Live".
  await page.click('[data-testid="live-btn"]');
  await expect(page.locator('[data-testid="mode-chip"]')).toContainText('Live', { timeout: 3000 });
});
