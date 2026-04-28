import { expect, test } from '@playwright/test';

async function login(page: import('@playwright/test').Page): Promise<void> {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
}

test('config: anonymous viewer sees the table with disabled inputs', async ({ page }) => {
  await page.goto('/#/config');
  await expect(page.locator('[data-testid="config-page"]')).toBeVisible({ timeout: 5000 });
  // The stub schema has 4 rows; one row per visible <tr>.
  const rows = page.locator('[data-testid="config-table"] tbody tr');
  await expect(rows).toHaveCount(4);
  // Every input is disabled for anon.
  const disabledInputs = page.locator('[data-testid="config-table"] input:disabled');
  await expect(disabledInputs).toHaveCount(4);
});

test('config: admin sees the Config nav row + edit a hot key triggers PATCH', async ({ page }) => {
  await login(page);
  // Sidebar exposes Config row when logged in as admin.
  await expect(page.locator('[data-testid="nav-config"]')).toBeVisible();
  await page.click('[data-testid="nav-config"]');
  await expect(page.locator('[data-testid="config-page"]')).toBeVisible();
  // Edit a hot-class double key.
  const input = page.locator('[data-testid="input-smoother.deadband_mm"]');
  await input.fill('15.5');
  await input.blur();
  // The current cell updates after the refresh round-trip.
  await expect(page.locator('[data-testid="row-smoother.deadband_mm"]')).toContainText('15.5', {
    timeout: 3000,
  });
});

test('config: edit a restart-class key triggers RestartPendingBanner', async ({ page }) => {
  await login(page);
  await page.goto('/#/config');
  await expect(page.locator('[data-testid="config-page"]')).toBeVisible();
  // Edit a restart-class int key.
  const input = page.locator('[data-testid="input-network.ue_port"]');
  await input.fill('7777');
  await input.blur();
  // The banner appears after refresh of /api/system/restart_pending.
  await expect(page.locator('[data-testid="restart-pending-banner"]')).toBeVisible({
    timeout: 5000,
  });
});

test('config: anonymous viewer does NOT see the Config nav row', async ({ page }) => {
  await page.goto('/#/');
  // No login; anon viewer.
  const navConfig = page.locator('[data-testid="nav-config"]');
  await expect(navConfig).toHaveCount(0);
});

test('config: edit a bad value (string into int field) shows inline error', async ({ page }) => {
  await login(page);
  await page.goto('/#/config');
  const input = page.locator('[data-testid="input-network.ue_port"]');
  // The input is type="number" so the SPA-side coerce rejects nonsense.
  // Force a non-numeric via JS to bypass the browser's number validation
  // and let the store's `coerce()` see the bad string. (In practice the
  // browser already strips non-numeric input.) Instead, send an
  // out-of-range int — the stub's `_h_patch_config` accepts any int, so
  // we reproduce the 400 path by editing the map_path with an empty
  // string (string types pass through, which the stub accepts) → trim
  // to the bad-key shape.
  // Simpler: use the `bad_key` route by manipulating the request via
  // page.route to inject a 400 response.
  await page.route('**/api/config', async (route) => {
    if (route.request().method() === 'PATCH') {
      await route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, err: 'bad_value', detail: 'simulated' }),
      });
      return;
    }
    await route.continue();
  });
  await input.fill('99999');
  await input.blur();
  await expect(page.locator('[data-testid="error-network.ue_port"]')).toBeVisible({
    timeout: 5000,
  });
});
