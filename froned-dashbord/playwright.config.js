import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests', timeout: 30000, workers: 1,
  reporter: 'list', outputDir: 'artifacts/test-results',
  use: { baseURL: process.env.DASHBOARD_URL || 'http://127.0.0.1:8100',
    launchOptions: { executablePath: process.env.CHROMIUM_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' },
    screenshot: 'only-on-failure' },
  webServer: { command: 'npm start', url: 'http://127.0.0.1:8100', reuseExistingServer: true },
});
