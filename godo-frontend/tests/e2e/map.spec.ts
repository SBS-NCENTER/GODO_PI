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

// --- Track E (PR-C) — multi-map management e2e ---------------------------

test('map: list panel shows ≥ 1 map with exactly one active', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  await expect(page.locator('[data-testid="map-list-panel"]')).toBeVisible();
  await expect(page.locator('[data-testid="map-list-table"]')).toBeVisible();
  const rows = page.locator('[data-testid^="map-row-"]');
  await expect(rows.first()).toBeVisible();
  const activeBadges = page.locator('[data-testid^="map-active-"]');
  await expect(activeBadges).toHaveCount(1);
});

test('map: activate flow shows confirm dialog with restart option (loopback)', async ({ page }) => {
  // Reset stub state by hitting the loopback flag back to true (default).
  await loginAs(page);
  // Hit /api/maps with the loopback flag once to reset the stub state.
  await page.goto('/?stub_loopback=true#/map');
  await expect(page.locator('[data-testid="map-list-panel"]')).toBeVisible();
  // studio_v2 row is the non-active one in the canned stub state.
  const activateBtn = page.locator('[data-testid="map-activate-studio_v2"]');
  await expect(activateBtn).toBeEnabled();
  await activateBtn.click();
  // Three-button dialog: cancel + secondary (재시작하지 않음) + primary
  // (godo-tracker 재시작) on loopback.
  await expect(page.locator('[data-testid="confirm-dialog"]')).toBeVisible();
  await expect(page.locator('[data-testid="confirm-cancel"]')).toBeVisible();
  await expect(page.locator('[data-testid="confirm-secondary"]')).toBeVisible();
  await expect(page.locator('[data-testid="confirm-ok"]')).toBeVisible();
  // Click "재시작하지 않음" — the simpler path that doesn't depend on
  // the loopback restart endpoint.
  await page.locator('[data-testid="confirm-secondary"]').click();
  // After refresh, studio_v2 should be the active row.
  await expect(page.locator('[data-testid="map-active-studio_v2"]')).toBeVisible({
    timeout: 5000,
  });
});

test('map: delete button is disabled on the active row', async ({ page }) => {
  await loginAs(page);
  await page.goto('/?stub_loopback=true#/map');
  await expect(page.locator('[data-testid="map-list-panel"]')).toBeVisible();
  // Wait for table to render.
  await expect(page.locator('[data-testid^="map-row-"]').first()).toBeVisible();
  // Find the active row — read the badge presence then resolve the
  // sibling delete button.
  const activeBadge = page.locator('[data-testid^="map-active-"]').first();
  const activeName = await activeBadge.getAttribute('data-testid');
  if (!activeName) throw new Error('active badge has no testid');
  const name = activeName.replace('map-active-', '');
  const deleteBtn = page.locator(`[data-testid="map-delete-${name}"]`);
  await expect(deleteBtn).toBeDisabled();
});

// --- Track D — Live LIDAR overlay e2e -----------------------------------

test('map: scan toggle is visible and defaults off', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  const toggle = page.locator('[data-testid="scan-toggle-btn"]');
  await expect(toggle).toBeVisible();
  // Initial label is "라이다 보기 꺼짐" (off-state); aria-pressed=false.
  await expect(toggle).toHaveAttribute('aria-pressed', 'false');
  // Wrap div carries data-scan-count="0" while overlay is off.
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '0',
  );
});

test('map: toggling scan overlay on shows ≥ 1 dot via data-scan-count', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  const toggle = page.locator('[data-testid="scan-toggle-btn"]');
  await expect(toggle).toBeVisible();
  await toggle.click();
  // After toggle on, the SSE delivers a 5-dot canned scan; freshness
  // gate keeps it visible. data-scan-count should rise to 5.
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '5',
    { timeout: 5000 },
  );
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-fresh',
    'true',
  );
});

test('map: toggling scan overlay off clears the dot count to 0', async ({ page }) => {
  await loginAs(page);
  await page.goto('/#/map');
  const toggle = page.locator('[data-testid="scan-toggle-btn"]');
  await toggle.click();
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '5',
    { timeout: 5000 },
  );
  // Toggle off — count drops back to 0 within the next redraw.
  await toggle.click();
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '0',
    { timeout: 2000 },
  );
});

test('map: scan overlay survives wheel-zoom (Track D scale fix)', async ({ page }) => {
  // Track D scale fix — toggle overlay ON, wheel-zoom in 3 times,
  // assert the overlay stays at 5 dots and stays fresh. Pixel-exact
  // alignment is covered by the deterministic unit math in §C; this
  // case is end-to-end integration sanity (YAML + dimensions both
  // fetched, no console errors, dot count stable through zoom).
  await loginAs(page);
  await page.goto('/#/map');
  const toggle = page.locator('[data-testid="scan-toggle-btn"]');
  await toggle.click();
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '5',
    { timeout: 5000 },
  );

  // Move into the canvas and wheel-zoom in 3 times.
  const canvas = page.locator('[data-testid="pose-canvas"]');
  const box = await canvas.boundingBox();
  if (!box) throw new Error('canvas not laid out');
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 3; i++) {
    await page.mouse.wheel(0, -100);
  }

  // After zoom, dot count stays at 5 and overlay stays fresh.
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-count',
    '5',
  );
  await expect(page.locator('[data-testid="pose-canvas-wrap"]')).toHaveAttribute(
    'data-scan-fresh',
    'true',
  );
});

test('map: scan toggle state persists through same-tab reload (sessionStorage)', async ({
  page,
}) => {
  await loginAs(page);
  await page.goto('/#/map');
  const toggle = page.locator('[data-testid="scan-toggle-btn"]');
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  // Reload preserves sessionStorage in the same tab (Q-OQ-D2).
  await page.reload();
  const toggleAfter = page.locator('[data-testid="scan-toggle-btn"]');
  await expect(toggleAfter).toHaveAttribute('aria-pressed', 'true');
});
