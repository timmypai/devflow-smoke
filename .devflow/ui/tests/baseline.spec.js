const { test, expect } = require('@playwright/test');
const path = require('node:path');

// Baseline only: future stats AC-1 / AC-2 must add their own journeys.
test('baseline HTTP and real browser homepage', async ({ page, request }) => {
  const health = await request.get('/health');
  expect(health.status()).toBe(200);
  expect(health.headers()['content-type']).toBe('application/json');
  expect(await health.text()).toBe('{"status":"ok"}');
  if (process.env.DEVFLOW_VERSION_ENDPOINT === '1') {
    const version = await request.get('/version');
    expect(version.status()).toBe(200);
    expect(version.headers()['content-type']).toBe('application/json');
    expect(await version.json()).toEqual({ revision: process.env.DEVFLOW_EXPECTED_REVISION });
  }
  const response = await page.goto('/');
  // Capture what actually rendered even if a subsequent assertion fails.
  await page.screenshot({ path: path.join(process.env.DEVFLOW_EVIDENCE, 'baseline-home.png'), fullPage: true });
  expect(response.status()).toBe(200);
  expect(response.headers()['content-type']).toBe('text/plain; charset=utf-8');
  expect(await response.text()).toBe('hello devflow');
  await expect(page.locator('body')).toHaveText('hello devflow');
});
