const { defineConfig } = require('@playwright/test');
const path = require('node:path');
const evidence = process.env.DEVFLOW_EVIDENCE;
if (!evidence) throw new Error('DEVFLOW_EVIDENCE required');
module.exports = defineConfig({
  testDir: './tests',
  retries: 0,
  workers: 1,
  timeout: 30000,
  outputDir: path.join(evidence, 'test-results'),
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(evidence, 'playwright.json') }],
    ['html', { outputFolder: path.join(evidence, 'playwright-report'), open: 'never' }],
  ],
  use: { browserName: 'chromium', baseURL: process.env.DEVFLOW_INNER_URL, trace: 'retain-on-failure' },
});
