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
  // Banner renders in two slots (TopBar + MapEdit) — assert the first.
  await expect(page.locator('[data-testid="restart-pending-banner"]').first()).toBeVisible({
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

// Track B-MAPEDIT-2 — origin pick e2e cases.

test('origin-pick: admin numeric absolute apply → success banner', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="origin-picker"]')).toBeVisible({ timeout: 5000 });

  await page.fill('[data-testid="origin-x-input"]', '0.32');
  await page.fill('[data-testid="origin-y-input"]', '-0.18');
  const applyBtn = page.locator('[data-testid="origin-apply-btn"]');
  await expect(applyBtn).toBeEnabled();
  await applyBtn.click();
  // Success banner inside the picker.
  await expect(page.locator('[data-testid="origin-banner"]')).toContainText('완료', {
    timeout: 5000,
  });
  // Restart-pending banner appears (refresh fired in onSuccess).
  // The banner renders in two slots (TopBar + page-local) — assert the
  // first occurrence is visible.
  await expect(page.locator('[data-testid="restart-pending-banner"]').first()).toBeVisible({
    timeout: 5000,
  });
});

test('origin-pick: admin GUI-pick pre-fills picker from canvas click', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="origin-picker"]')).toBeVisible({ timeout: 5000 });

  // Toggle origin-pick mode on, then click the canvas.
  await page.locator('[data-testid="origin-pick-toggle"]').check();
  await page.locator('[data-testid="mask-paint-layer"]').click({ position: { x: 50, y: 50 } });

  // Inputs are pre-filled (with whatever pixelToWorld returns; the
  // exact value depends on the stub's mapMetadata, but we at least
  // assert non-empty).
  const xInput = page.locator('[data-testid="origin-x-input"]');
  await expect(xInput).not.toHaveValue('', { timeout: 2000 });
  await expect(page.locator('[data-testid="origin-apply-btn"]')).toBeEnabled();
});

test('origin-pick: viewer cannot apply', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'viewer');
  await page.fill('[data-testid="login-password"]', 'viewer');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/map-edit');
  await expect(page.locator('[data-testid="origin-picker"]')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('[data-testid="origin-apply-btn"]')).toBeDisabled();
});
