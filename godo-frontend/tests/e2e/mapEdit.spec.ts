import { expect, test } from '@playwright/test';

test('map-edit: anon sees page but Apply is disabled', async ({ page }) => {
  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="map-edit-page"]')).toBeVisible({ timeout: 5000 });
  // The brush slider renders for anon viewers (read-only inspection is OK).
  await expect(page.locator('[data-testid="map-edit-brush-slider"]')).toBeVisible();
  // Apply button rendered but disabled.
  const applyBtn = page.locator('[data-testid="map-edit-apply-btn"]');
  await expect(applyBtn).toBeDisabled();
});

test('map-edit: admin login → paint+apply happy path → restart-pending banner', async ({
  page,
}) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="map-edit-page"]')).toBeVisible({ timeout: 5000 });

  const applyBtn = page.locator('[data-testid="map-edit-apply-btn"]');
  await expect(applyBtn).toBeEnabled();

  // Paint a single brush stroke at the centre of the mask layer. The
  // page renders the canvas at its natural CSS size; a single click is
  // enough for the stub-server happy path (the stub does not validate
  // the mask shape).
  const paintLayer = page.locator('[data-testid="mask-paint-layer"]');
  await paintLayer.click({ position: { x: 50, y: 50 } });

  await applyBtn.click();
  // Success banner contains the canonical-stamp prefix.
  const banner = page.locator('[data-testid="map-edit-banner"]');
  await expect(banner).toContainText('완료', { timeout: 5000 });

  // The restart-pending banner appears (refresh fired in onSuccess).
  await expect(page.locator('[data-testid="restart-pending-banner"]')).toBeVisible({
    timeout: 5000,
  });
});

test('map-edit: viewer cannot apply', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'viewer');
  await page.fill('[data-testid="login-password"]', 'viewer');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="map-edit-page"]')).toBeVisible({ timeout: 5000 });
  // Viewer role: Apply button disabled.
  await expect(page.locator('[data-testid="map-edit-apply-btn"]')).toBeDisabled();
});
