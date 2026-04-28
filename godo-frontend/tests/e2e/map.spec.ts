import { expect, test } from '@playwright/test';

async function loginAs(page: import('@playwright/test').Page) {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');
  await expect(page.locator('[data-testid="dashboard"]')).toBeVisible({ timeout: 5000 });
}

test('map: renders pose canvas + readout', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  await expect(page.locator('[data-testid="map-page"]')).toBeVisible();
  await expect(page.locator('[data-testid="pose-canvas"]')).toBeVisible();
  // Stub canned pose: x=1.50 m
  await expect(page.locator('[data-testid="pose-readout"]')).toContainText('1.50 m', {
    timeout: 5000,
  });
});

test('map: hover shows world coord', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  const canvas = page.locator('[data-testid="pose-canvas"]');
  await expect(canvas).toBeVisible();
  // Move into the canvas to trigger the hover-coord overlay.
  const box = await canvas.boundingBox();
  if (!box) throw new Error('canvas not laid out');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await expect(page.locator('[data-testid="hover-coord"]')).toBeVisible({ timeout: 2000 });
});
