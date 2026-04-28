import { expect, test } from '@playwright/test';

async function loginAs(page: import('@playwright/test').Page, user: 'ncenter' | 'viewer') {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', user);
  await page.fill('[data-testid="login-password"]', user);
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible({ timeout: 5000 });
}

test('local: loopback host shows cards', async ({ page }) => {
  // Default base URL is 127.0.0.1 — loopback per LOCAL_HOSTNAMES.
  await loginAs(page, 'ncenter');
  await page.goto('/#/local');
  await expect(page.locator('[data-testid="local-page"]')).toBeVisible();
  // Three service cards from the stub list.
  await expect(page.locator('[data-testid="service-card-godo-tracker"]')).toBeVisible({
    timeout: 5000,
  });
  await expect(page.locator('[data-testid="service-card-godo-webctl"]')).toBeVisible();
  await expect(page.locator('[data-testid="service-card-godo-irq-pin"]')).toBeVisible();
});

test('local: reboot button gated by confirm dialog', async ({ page }) => {
  await loginAs(page, 'ncenter');
  await page.goto('/#/local');
  await expect(page.locator('[data-testid="local-page"]')).toBeVisible();
  await page.click('[data-testid="reboot-btn"]');
  await expect(page.locator('[data-testid="confirm-dialog"]')).toBeVisible();
  // Cancelling closes without firing the API.
  await page.click('[data-testid="confirm-cancel"]');
  await expect(page.locator('[data-testid="confirm-dialog"]')).not.toBeVisible();
});

test('local: viewer cannot click admin buttons', async ({ page }) => {
  await loginAs(page, 'viewer');
  await page.goto('/#/local');
  await expect(page.locator('[data-testid="local-page"]')).toBeVisible();
  await expect(page.locator('[data-testid="reboot-btn"]')).toBeDisabled();
  await expect(page.locator('[data-testid="shutdown-btn"]')).toBeDisabled();
});
