# devflow-smoke

僅使用 Python 標準函式庫的 HTTP 服務（Python 3.14）。

```sh
python3 app.py                 # 預設 0.0.0.0:8080
PORT=8090 python3 app.py       # 可覆寫監聽埠
.devflow/test.sh               # unittest：動態埠真實 HTTP 與 smoke 反例
python3 smoke.py http://127.0.0.1:8080
DEVFLOW_REVISION=local python3 app.py
# 另一個終端驗證包含 /version 的完整契約：
python3 smoke.py http://127.0.0.1:8080 --expected-revision local
```

| GET 路徑 | 狀態碼 | Content-Type | 回應契約 |
| --- | --- | --- | --- |
| `/health` | 200 | `application/json` | `{"status":"ok"}` |
| `/` | 200 | `text/html; charset=utf-8` | HTML 保留 `hello devflow`，可見「目前請求數」及本次 GET 的整數快照；按「更新」透過 `/stats` JSON 更新同一頁面，不整頁重載 |
| `/stats` | 200 | `application/json` | 解析後精確單鍵 `{"requests": <非負整數>}`，不接受 bool／浮點／字串 |
| `/stats?format=text` | 200 | `text/plain; charset=utf-8` | 精確為 `requests: N`（N 是非負十進位整數），不附換行；可帶其他參數，如 `/stats?probe=1&format=text` |
| `/version` | 200 | `application/json` | 解析後精確為 `{"revision":"<DEVFLOW_REVISION 原值>"}` |

`/version` 僅在環境變數不存在時回 `unknown`，空字串保持空字串；使用 JSON serializer 跳脫，
不執行 git，也不需要 checkout。不指定 `--expected-revision` 時，smoke 仍驗證 `/stats`、`/health` 及 HTML 首頁，只略過 `/version`。
其他路徑回傳 404。

計數來源是每個服務實例的記憶體計數器，成功（200）的 GET（含 `/`、`/health`、`/version`、`/stats` 自身）
各加一，404 不計數；回應快照包含該次成功 GET；鎖保護多執行緒併發，不同實例互不污染。新實例或重啟歸零，
不跨重啟持久化，其他 HTTP 方法不在此契約。首頁只在按「更新」時取得最新快照，不自動輪詢；healthcheck 等額外成功 GET 也會增加數字，
favicon 等 404 不增加。

JSON 與純文字格式共用同一計數器，每次請求仍只加一。`/stats` 未指定 `format=text` 時保持 JSON；
既有端點仍接受額外查詢參數，`format=text` 不會改變 `/`、`/health` 或 `/version` 的格式。

## 測試、CI 與部署（devflow 契約）

`.devflow/` 與 `.github/workflows/` 是 devflow 範本（`devflow contract devflow-smoke . --ui`），只有以下專案設定：

- `.devflow/test.sh` 用標準函式庫的 `.devflow/unittest-runner.py`，支援 lesson gate 需要的 `DEVFLOW_TEST_ONLY`（只跑一個測試檔）與 `DEVFLOW_JUNIT`（JUnit 輸出）。runner 本身由 `tests/test_lesson_gate.py` 驗證。
- `deploy/compose.yml` 把 `GITHUB_SHA` 傳成映像的 OCI revision（`VCS_REF`）與 runtime 的 `DEVFLOW_REVISION`，`/version` 回報它。
- `quality.yml`／`quality.sh`／`coverage.sh`：非必過的品質訊號；coverage 用 `unittest discover -s tests`，mutation 限 180 秒。

驗收情境寫在 `.devflow/ui/ac.spec.ts`（ui / api，Playwright）或 `.devflow/verify.sh`（cli / lib，shell）。每個情境的 id 是 `<EPIC>/AC-n.Sm`，Given / When / Then 文字與 EPIC 相同。CI 的 `verify` 對 PR 版本跑全部情境，`verify-base` 對 PR 說明 `Covers:` 列出的情境在改動前的版本跑（必須紅燈）；部署後只跑 `smoke` 情境，失敗就回滾。報告是 artifact `devflow-evidence-*` 裡的 `acceptance.json` 與 `acceptance-matrix.md`。

本機：

```sh
.devflow/test.sh               # 單元與 HTTP 測試
bash .devflow/check.sh         # 規則自測、教訓、規則掃描
```
