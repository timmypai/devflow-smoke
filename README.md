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
| `/` | 200 | `text/html; charset=utf-8` | HTML 保留 `hello devflow`，可見「目前請求數」及本次 GET 的整數快照 |
| `/stats` | 200 | `application/json` | 解析後精確單鍵 `{"requests": <非負整數>}`，不接受 bool／浮點／字串 |
| `/version` | 200 | `application/json` | 解析後精確為 `{"revision":"<DEVFLOW_REVISION 原值>"}` |

`/version` 僅在環境變數不存在時回 `unknown`，空字串保持空字串；使用 JSON serializer 跳脫，
不執行 git，也不需要 checkout。不指定 `--expected-revision` 時，smoke 仍驗證 `/stats`、`/health` 及 HTML 首頁，只略過 `/version`。
其他路徑回傳 404。

計數來源是每個服務實例的記憶體計數器，所有 GET（含 `/`、`/health`、`/version`、`/stats` 自身及 404）
各加一，回應快照包含該次 GET；鎖保護多執行緒併發，不同實例互不污染。新實例或重啟歸零，
不跨重啟持久化，其他 HTTP 方法不在此契約。首頁重新整理才更新，不即時輪詢；favicon、
healthcheck 等額外 GET 也會增加數字。隔離 HTTP 測試驗精確增量，部署 journeys 只驗單調增加。

## 容器與 CI

有 Docker daemon 時執行：

```sh
GITHUB_SHA=$(git rev-parse HEAD) .devflow/container-smoke.sh
```

此入口會 build、run、明確注入完整來源 SHA 至 `DEVFLOW_REVISION`，
從宿主的動態 loopback 埠驗證 stats／HTML／health／version、核對 OCI revision，並清理容器。
PR／分支 CI 在 GitHub-hosted x64 與 ARM64 runner 對完整來源 SHA 執行 unittest 與同一容器驗證。

## 部署驗收

僅 `main` push 或經授權的 `main` workflow_dispatch 觸發 `.github/workflows/deploy.yml`，
在 Oracle self-hosted ARM64 devflow runner 執行 `.devflow/deploy.sh`；不需要新增 secrets。
Compose 固定 loopback 綁定 `127.0.0.1:18100:8080`，不設定公開 ingress。

部署使用 SHA image tag，先核對完整 40 位 `GITHUB_SHA` 與 checkout HEAD 一致，
再將其作為 `VCS_REF` 寫入 OCI revision，並經 Compose 明確映射到 runtime `DEVFLOW_REVISION`；
runner 殘留的同名變數不能取代此值。
部署後從 VM 宿主驗證 stats／HTML／health／version的 status、Content-Type、內容（`/version` 比較解析後的精確 JSON 物件），
並將來源 SHA、expected revision、runner、架構、container/image ID、OCI revision 與 HTTP 實測結果
寫入 Actions log／step summary；checkout、OCI 與 runtime revision 不相符即失敗。
啟動或驗證失敗時，若已有 `live` 映像則使用該映像的完整 OCI revision 注入回滾容器，
不沿用失敗候選的 SHA；回滾仍核對 OCI，workflow 仍回報失敗。
新映像以 `io.devflow.version-endpoint=1` 與 `io.devflow.stats-endpoint=1` 標記能力。
正常候選強制驗 stats／HTML／AC-1／AC-2，壞回應不會觸發降級。僅回滾時，可信 live OCI
缺少 stats 標記才驗舊純文字 `hello devflow`；若仍有 version 標記則照常驗 revision。
也無 version 標記才略過 `/version` 並明確記錄 `NOT verified`。未知／不一致 capability
直接失敗；stats-capable 回滾不可略過新契約。舊首頁回滾不宣稱 AC-1／AC-2 通過。
獨立審查與實際 merge／部署由下游 REVIEW／SHIP 卡執行。

## 共用驗證與瀏覽器證據

`.devflow/verify.sh` 是 PR 與部署的同一入口：

- **AC-1**：真實 HTTP 驗 `/stats` 的狀態、JSON 契約及經過 GET 後增加，並驗 health／HTML／revision。
- **AC-2**：真 Chromium 驗可見標籤、整數、刷新增加；以同源 `/stats` 前後快照夾住首頁值，
  保存 `AC-2-http-dom.json` 的 HTTP／DOM 觀測、`AC-2.png` 與 Playwright JSON／HTML report。

成功候選另複製截圖至 `.devflow/evidence/AC-2.png`；完整證據留在各自的 `attempt-*`。
Playwright npm 套件與官方 multi-arch Noble 映像均釘選 `1.58.2`，npm lockfile 含 integrity。

```sh
# 在具備 Docker 的 Actions runner（不是 Hermes 容器）內：
export GITHUB_SHA=$(git rev-parse HEAD)
.devflow/prepare-evidence.sh
# GITHUB_ENV / GITHUB_RUN_ID / GITHUB_RUN_ATTEMPT / RUNNER_ARCH 由 Actions 提供。
.devflow/up.sh                    # 獨立 compose project + 動態 loopback 埠
# 下一個 Actions step 會取得 up.sh 寫入 GITHUB_ENV 的變數：
.devflow/verify.sh
```

契約：`DEVFLOW_BASE_URL` 供宿主 HTTP smoke；`DEVFLOW_NET` 是瀏覽器容器加入的 Docker network，
`DEVFLOW_INNER_URL` 是該 network 可達的 app URL（通常 `http://app:8080`）；
`DEVFLOW_EVIDENCE` 預設為 repo 內 `.devflow/evidence`，可改成 repo 內其他目錄。
`GITHUB_SHA` 永遠是候選來源 SHA；`DEVFLOW_EXPECTED_REVISION` 才是本輪 runtime 預期值。
`DEVFLOW_VERIFY_PHASE` 為 `candidate`（預設）或 `rollback`；`DEVFLOW_STATS_ENDPOINT`／
`DEVFLOW_VERSION_ENDPOINT` 預設為 `1`，回滾由 deploy.sh 從 live OCI 讀取，不根據 HTTP 回應猜測。
回滾使用舊 OCI revision，無 stats 標記才用 legacy 純文字／瀏覽器首頁契約。
rootless Docker 不使用 host-loopback 作為瀏覽器 URL，且容器 UID 0 對應 runner owner。

CI 保留原本 x64／ARM64 test matrix，另有兩架構真實 compose + browser verify matrix。
`devflow-ci` 只接受 check、test、verify 均為 success（skipped／cancelled 也失敗）。
經授權執行 `gh workflow run ci.yml --ref <trusted-branch>` 時，另加 Oracle ARM64 verify，
仍只使用臨時 project／動態埠，不改 production project、18100 或 `:live`。

每個 workflow 開始清除固定 evidence root；每次 verify 再建立獨立 `attempt-*`，
含來源 SHA、expected revision、runner／架構、HTTP/browser log、exit code、PNG、JSON 與 HTML report。
成功必須具備所有必需檔案及非 skipped 的通過報告。候選失敗與回滾證據分開保留，
不能把舊 PASS 當成本輪成功；回滾健康也仍讓 deployment workflow 失敗。
部署在 verify 通過後才更新 `:live`，不更動既有 provenance 與 loopback 保護。
CI／部署都以 `always()` 上傳 `devflow-evidence-pr-<sha>-<arch>`／
`devflow-evidence-deploy-<sha>` artifacts，缺目錄即失敗。服務 project 與瀏覽器容器會清理。
本機 unittest 的 Docker／verify double **只證明控制流程**；實容器、Chromium 與 ARM64
可執行性應以 exact-head Actions logs 和 artifacts 為準。

## 契約規則、品質與安全採證

`bash .devflow/check.sh` 自測三條非空規則、驗證教訓格式／enforcement ref，再掃描 git tracked
檔案。不使用 baseline，也不排除 tests／UI。`smoke.py` 唯一單行豁免引用 `L-0001`：
連線失敗才做 0.2 秒 backoff，持續重試明確 HTTP 條件且有 monotonic deadline；不是盲目等待 readiness，
回應契約錯誤不會重試。保留原有邏輯，不改用等價 API 規避掃描。

`.devflow/contract-evidence.py` 在 PR check job、main 部署前與 repro 執行；`contracts/mapping.json`
記錄本 Epic `t_97e7e941` 的 AC 對應，`CONTRACT-AC-1..3.json/.log` 帶來源 SHA、檔案 SHA256、
命令與 exit code。AC-1 驗 check exact-head/strict needs（真實 CI conclusion 另外核對）；
AC-2 驗 rules／lesson／新增違規及失效 ref 負例；AC-3 驗必需檔案與 synthetic redaction／fail-closed。
既有 stats **AC-1**／首頁 **AC-2** 名稱與 `attempt-*` 的 candidate／rollback validator 不變，
它們不是這次 Epic 的契約驗收；main checkout、部署健康與正式 repro dispatch 由 SHIP 實測。

`quality.yml` 是獨立、非 required 的品質訊號，僅在 GitHub-hosted/read-only token 執行
釘選 commit 的 crapper／dryer／mutator，結果放 `devflow-quality-<exact-head-sha>`（`.metrics`）。
不在 Hermes 或 production 執行第三方工具；工具失敗不影響 `devflow-ci`。

```sh
# repro.yml 必須先存在 main 才能 dispatch：
gh workflow run repro.yml --ref <trusted-branch>
```

repro 跑完整 HTTP + Chromium journeys，**不支援 AC selector 或 trace input**。
先 prepare-evidence，再 up.sh 將實際 `devflow-verify-<run>-<attempt>-<arch>`、動態 loopback URL
寫入 GITHUB_ENV。always 先採集該 project，再用 cleanup.sh 核對本次 run 身分後 down；
always 上傳 `devflow-repro-<run>-<attempt>`。不讀 production secrets、不使用 18100／`:live`。

capture 是唯讀且 best-effort，僅取指定 compose label 的容器、State／exit／OOM／restart、
限時限量 logs、loopback health 與 host 資源，不輸出 Config.Env。原始檔先放 artifact 外的
私有 staging；所有欄位遮罩成功才發布，否則丟棄**全部** payload（含 State／health／errors），
僅留固定錯誤訊息。deploy/.env 所有非空 literal（含短值）及常見 credential 樣式會遮罩；
不支援／無法讀取的 dotenv 語法會 fail closed，可能犧牲診斷，但不發布原文。
相同 label 可重跑，拒絕 traversal／symlink output，不清除專案外資料。
CI/repro 在清理前採證；部署 build 失敗不換服務，候選失敗在 rollback **前**採證，
rollback 後另採證。capture 故障不覆蓋原失敗／rollback 結果，不再直接印未遮罩容器 logs。
CI 與 deploy 另以 always 上傳 `devflow-diagnostics-pr-<sha>-<arch>`／
`devflow-diagnostics-deploy-<sha>`（7 天）；成功部署沒有 diagnostics 是正常的。
GitHub-hosted verify/repro 另以同一臨時 project 的合成容器實測 exit 7、State、遮罩 logs 與
動態 health URL，結果為 `diagnostics-probe.json`；只使用 synthetic secrets，要求空 .env，
清理精確 probe container 並還原空 .env，不在 Oracle／Hermes 執行此 probe。
