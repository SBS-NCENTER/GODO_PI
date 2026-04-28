import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const STUB_PORT = 8081;
const HERE = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${STUB_PORT}`,
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `python3 ${HERE}/_stub_server.py --port ${STUB_PORT}`,
      url: `http://127.0.0.1:${STUB_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
  ],
});
