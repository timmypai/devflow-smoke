import { expect, type APIResponse, type Page } from '@playwright/test';
import { scenario } from './ac';

async function displayedCount(page: Page): Promise<number> {
  const text = await page.getByLabel('目前請求數').innerText();
  expect(text).toMatch(/^[0-9]+$/);
  return Number(text);
}

for (const spec of [
  {
    "id": "t_e07b5ec1/AC-1.S1",
    "description": "單次更新且不重新載入頁面",
    "given": "首頁已開啟，標題為「hello devflow」，「目前請求數」顯示非負整數，已記錄數字與目前文件身分",
    "when": "按一次「更新」按鈕",
    "then": "「目前請求數」顯示大於原數字的整數，目前文件身分不變且未發生主頁面導覽",
    "clicks": 1
  },
  {
    "id": "t_e07b5ec1/AC-1.S2",
    "description": "重複更新仍有效",
    "given": "首頁已開啟，「目前請求數」顯示非負整數，已記錄數字與目前文件身分",
    "when": "依序按兩次「更新」按鈕，每次等候計數更新後再繼續",
    "then": "每次更新後的數字均大於該次按之前的數字，目前文件身分不變且未發生主頁面導覽",
    "clicks": 2
  }
]) {
  let initial: number;
  let documentId: string;
  let navigations: string[];
  let updates: { before: number; after: number }[];

  scenario(spec.id, spec.description, {
    kind: 'ui',
    smoke: true,
    given: {
      title: spec.given,
      act: async ({ page }) => { await page.goto('/'); },
      check: async ({ page }) => {
        await expect(page).toHaveTitle('hello devflow');
        await expect(page.getByRole('heading', { level: 1, name: 'hello devflow' })).toBeVisible();
        initial = await displayedCount(page);
        documentId = await page.evaluate(() => {
          const id = crypto.randomUUID();
          document.documentElement.dataset.devflowDocument = id;
          return id;
        });
        navigations = [];
        updates = [];
        page.on('framenavigated', frame => {
          if (frame === page.mainFrame()) navigations.push(frame.url());
        });
        page.on('request', request => {
          if (request.isNavigationRequest() && request.frame() === page.mainFrame()) {
            navigations.push(request.url());
          }
        });
        expect(Number.isInteger(initial) && initial >= 0).toBe(true);
        expect(await page.locator('html').getAttribute('data-devflow-document')).toBe(documentId);
      },
    },
    when: {
      title: spec.when,
      act: async ({ page }) => {
        for (let click = 0; click < spec.clicks; click++) {
          const before = await displayedCount(page);
          await page.getByRole('button', { name: '更新', exact: true }).click();
          await expect.poll(() => displayedCount(page)).toBeGreaterThan(before);
          updates.push({ before, after: await displayedCount(page) });
        }
      },
    },
    then: {
      title: spec.then,
      check: async ({ page }) => {
        expect(updates).toHaveLength(spec.clicks);
        for (const update of updates) expect(update.after).toBeGreaterThan(update.before);
        expect(await displayedCount(page)).toBeGreaterThan(initial);
        expect(await page.locator('html').getAttribute('data-devflow-document')).toBe(documentId);
        expect(navigations).toEqual([]);
      },
    },
  });
}

for (const spec of [
  {
    "id": "t_e07b5ec1/AC-2.S1",
    "description": "純文字計數",
    "given": "服務已啟動，GET / 回應 200",
    "when": "呼叫 GET /stats?format=text",
    "then": "回應 200，Content-Type 精確為 text/plain; charset=utf-8，UTF-8 內容精確符合 requests: 加一個空白及一個非負十進位整數，無其他內容",
    "path": "/stats?format=text",
    "contract": "text"
  },
  {
    "id": "t_e07b5ec1/AC-2.S2",
    "description": "額外查詢參數不影響純文字格式",
    "given": "服務已啟動，GET / 回應 200",
    "when": "呼叫 GET /stats?probe=1&format=text",
    "then": "回應 200，Content-Type 精確為 text/plain; charset=utf-8，UTF-8 內容精確符合 requests: 加一個空白及一個非負十進位整數，無其他內容",
    "path": "/stats?probe=1&format=text",
    "contract": "text"
  },
  {
    "id": "t_e07b5ec1/AC-2.S3",
    "description": "預設 JSON 契約保持不變",
    "given": "服務已啟動，GET / 回應 200",
    "when": "呼叫 GET /stats",
    "then": "回應 200，Content-Type 精確為 application/json，JSON 只有 requests 單鍵且值為非負整數",
    "path": "/stats",
    "contract": "json"
  },
  {
    "id": "t_e07b5ec1/AC-2.S4",
    "description": "健康檢查契約保持不變",
    "given": "服務已啟動，GET / 回應 200",
    "when": "呼叫 GET /health",
    "then": "回應 200，Content-Type 精確為 application/json，回應內容精確為 {\"status\":\"ok\"}",
    "path": "/health",
    "contract": "health"
  },
  {
    "id": "t_e07b5ec1/AC-2.S5",
    "description": "版本端點契約保持不變",
    "given": "服務已啟動，GET /version 回應 200 且 JSON 只有 revision 字串單鍵，已記錄該字串",
    "when": "呼叫 GET /version",
    "then": "回應 200，Content-Type 精確為 application/json，JSON 只有 revision 單鍵且值等於已記錄的字串",
    "path": "/version",
    "contract": "version"
  }
]) {
  let response: APIResponse;
  let revision: string;

  scenario(spec.id, spec.description, {
    kind: 'api',
    smoke: true,
    given: {
      title: spec.given,
      check: async ({ request }) => {
        if (spec.contract === 'version') {
          const before = await request.get('/version');
          expect(before.status()).toBe(200);
          const payload = await before.json();
          expect(Object.keys(payload)).toEqual(['revision']);
          expect(typeof payload.revision).toBe('string');
          revision = payload.revision;
          expect(payload).toEqual({ revision });
        } else {
          expect((await request.get('/')).status()).toBe(200);
        }
      },
    },
    when: {
      title: spec.when,
      act: async ({ request }) => { response = await request.get(spec.path); },
    },
    then: {
      title: spec.then,
      check: async () => {
        expect(response.status()).toBe(200);
        if (spec.contract === 'text') {
          expect(response.headers()['content-type']).toBe('text/plain; charset=utf-8');
          const text = new TextDecoder('utf-8', { fatal: true }).decode(await response.body());
          expect(text.match(/^requests: [0-9]+/)?.[0]).toBe(text);
        } else {
          expect(response.headers()['content-type']).toBe('application/json');
          if (spec.contract === 'health') {
            expect(await response.text()).toBe('{"status":"ok"}');
          } else if (spec.contract === 'version') {
            expect(await response.json()).toEqual({ revision });
          } else {
            const payload = await response.json();
            expect(Object.keys(payload)).toEqual(['requests']);
            expect(Number.isInteger(payload.requests) && payload.requests >= 0).toBe(true);
          }
        }
      },
    },
  });
}
