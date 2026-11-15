const { test, expect } = require('@playwright/test');
const path = require('node:path');
const fs = require('node:fs');
const evidence = process.env.DEVFLOW_EVIDENCE;
const legacy = ['', '<no value>'].includes(process.env.DEVFLOW_STATS_ENDPOINT);
if (legacy && process.env.DEVFLOW_VERIFY_PHASE !== 'rollback') throw new Error('Legacy is rollback-only');
if (!legacy && process.env.DEVFLOW_STATS_ENDPOINT !== '1') throw new Error('Unknown stats capability');

if (legacy) {
  test('legacy rollback plain-text homepage (not stats ACs)', async ({ page, request }) => {
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
    await page.screenshot({ path: path.join(evidence, 'legacy-home.png'), fullPage: true });
    expect(response.status()).toBe(200);
    expect(response.headers()['content-type']).toBe('text/plain; charset=utf-8');
    expect(await response.text()).toBe('hello devflow');
    await expect(page.locator('body')).toHaveText('hello devflow');
  });
} else {
  test('AC-2 visible shared request count increases on refresh', async ({ page, request }) => {
    const records = [];
    async function stats() {
      const response = await request.get('/stats');
      const text = await response.text();
      records.push({ url: response.url(), status: response.status(), headers: response.headers(), body: text });
      expect(response.status()).toBe(200);
      expect(response.headers()['content-type']).toBe('application/json');
      const data = JSON.parse(text);
      expect(Object.keys(data)).toEqual(['requests']);
      expect(Number.isSafeInteger(data.requests)).toBe(true);
      expect(data.requests).toBeGreaterThanOrEqual(0);
      return data.requests;
    }
    async function homepage(response) {
      const html = await response.text();
      records.push({ url: response.url(), status: response.status(), headers: response.headers(), body: html });
      expect(response.status()).toBe(200);
      expect(response.headers()['content-type']).toBe('text/html; charset=utf-8');
      await expect(page.getByRole('heading', { name: 'hello devflow', exact: true })).toBeVisible();
      await expect(page.getByText('目前請求數', { exact: true })).toBeVisible();
      const output = page.getByRole('status', { name: '目前請求數', exact: true });
      await expect(output).toBeVisible();
      await expect(output).toHaveText(/^[0-9]+$/);
      const text = await output.innerText();
      const count = Number(text);
      expect(Number.isSafeInteger(count)).toBe(true);
      expect(count).toBeGreaterThanOrEqual(0);
      expect(html).toContain(`<output id="requests">${text}</output>`);
      records.push({ dom: await page.locator('body').innerText(), count });
      return count;
    }
    try {
      const before = await stats();
      const first = await homepage(await page.goto('/'));
      const middle = await stats();
      const refreshed = await homepage(await page.reload());
      const after = await stats();
      expect(before).toBeLessThan(first);
      expect(first).toBeLessThan(middle);
      expect(middle).toBeLessThan(refreshed);
      expect(refreshed).toBeLessThan(after);
      records.push({ snapshots: { before, first, middle, refreshed, after } });
    } finally {
      fs.writeFileSync(path.join(evidence, 'AC-2-http-dom.json'), JSON.stringify(records, null, 2));
      await page.screenshot({ path: path.join(evidence, 'AC-2.png'), fullPage: true });
    }
  });
}
