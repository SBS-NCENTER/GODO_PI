import { expect, test } from '@playwright/test';

test('backup: anon sees table; restore button is disabled', async ({ page }) => {
  await page.goto('/#/backup');
  await expect(page.locator('[data-testid="backup-page"]')).toBeVisible({ timeout: 5000 });
  await expect(page.locator('[data-testid="backup-table"]')).toBeVisible();
  // Stub seeds two backups; both rows should render.
  await expect(page.locator('[data-testid="backup-row-20260202T020202Z"]')).toBeVisible();
  await expect(page.locator('[data-testid="backup-row-20260101T010101Z"]')).toBeVisible();
  // Anon: restore button rendered but disabled.
  const restoreBtn = page.locator('[data-testid="backup-restore-20260202T020202Z"]');
  await expect(restoreBtn).toBeDisabled();
});

test('backup: admin login → restore confirm flow → success toast', async ({ page }) => {
  await page.goto('/#/login');
  await page.fill('[data-testid="login-username"]', 'ncenter');
  await page.fill('[data-testid="login-password"]', 'ncenter');
  await page.click('[data-testid="login-submit"]');

  await page.goto('/#/backup');
  await expect(page.locator('[data-testid="backup-page"]')).toBeVisible({ timeout: 5000 });

  const restoreBtn = page.locator('[data-testid="backup-restore-20260202T020202Z"]');
  await expect(restoreBtn).toBeEnabled();
  await restoreBtn.click();
  // Confirm dialog opens with the two-line body.
  await expect(page.locator('[data-testid="confirm-dialog"]')).toBeVisible();
  await page.click('[data-testid="confirm-ok"]');

  // Mode-A N1 fold: success toast wording is the imported constant
  // (mirrors Track E activate flow). Match the leading literal so a
  // future copy edit fails this test.
  const banner = page.locator('[data-testid="backup-banner"]');
  await expect(banner).toContainText('복원 완료. /map에서 활성화하면 godo-tracker 재시작', {
    timeout: 5000,
  });
});

test('backup: sidebar nav link routes to /backup', async ({ page }) => {
  await page.goto('/');
  await page.click('[data-testid="nav-backup"]');
  await expect(page).toHaveURL(/#\/backup$/);
  await expect(page.locator('[data-testid="backup-page"]')).toBeVisible();
});
