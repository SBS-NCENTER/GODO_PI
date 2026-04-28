import { expect, test } from '@playwright/test';

test.beforeEach(async ({ context }) => {
  // Wipe localStorage to ensure clean session per test.
  await context.clearCookies();
});

test('login: invalid credentials show error', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'bogus');
  await page.fill('[data-testid="login-password"]', 'wrong');
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="login-error"]')).toBeVisible();
});

test('login: valid credentials land on dashboard', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('[data-testid="session-info"]')).toContainText('ncenter');
});

test('login: logged-in user visiting /login is bounced to /', async ({ page }) => {
  // First log in.
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible();

  // Now visit /login again — should bounce.
  await page.goto('/#/login');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible({ timeout: 5000 });
});
