# devflow-smoke

僅使用 Python 標準函式庫的 HTTP 服務（Python 3.14）。

```sh
python3 app.py                 # 預設 0.0.0.0:8080
PORT=8090 python3 app.py       # 可覆寫監聽埠
.devflow/test.sh               # unittest：動態埠真實 HTTP 與 smoke 反例
python3 smoke.py http://127.0.0.1:8080
DEVFLOW_REVISION=local python3 app.py
# 另一個終端驗證包含 /version 的三端點契約：
python3 smoke.py http://127.0.0.1:8080 --expected-revision local
```

| GET 路徑 | 狀態碼 | Content-Type | 精確 body（無換行） |
| --- | --- | --- | --- |
| `/health` | 200 | `application/json` | `{"status":"ok"}` |
| `/` | 200 | `text/plain; charset=utf-8` | `hello devflow` |
| `/version` | 200 | `application/json` | 解析後精確為 `{"revision":"<DEVFLOW_REVISION 原值>"}` |

`/version` 僅在環境變數不存在時回 `unknown`，空字串保持空字串；使用 JSON serializer 跳脫，
不執行 git，也不需要 checkout。不指定 `--expected-revision` 時，smoke 維持原本的雙端點檢查。
其他路徑回傳 404。

## 容器與 CI

有 Docker daemon 時執行：

```sh
GITHUB_SHA=$(git rev-parse HEAD) .devflow/container-smoke.sh
```

此入口會 build、run、明確注入完整來源 SHA 至 `DEVFLOW_REVISION`，
從宿主的動態 loopback 埠驗證三端點、核對 OCI revision，並清理容器。
PR／分支 CI 在 GitHub-hosted x64 與 ARM64 runner 對完整來源 SHA 執行 unittest 與同一容器驗證。

## 部署驗收

僅 `main` push 或經授權的 `main` workflow_dispatch 觸發 `.github/workflows/deploy.yml`，
在 Oracle self-hosted ARM64 devflow runner 執行 `.devflow/deploy.sh`；不需要新增 secrets。
Compose 固定 loopback 綁定 `127.0.0.1:18100:8080`，不設定公開 ingress。

部署使用 SHA image tag，先核對完整 40 位 `GITHUB_SHA` 與 checkout HEAD 一致，
再將其作為 `VCS_REF` 寫入 OCI revision，並經 Compose 明確映射到 runtime `DEVFLOW_REVISION`；
runner 殘留的同名變數不能取代此值。
部署後從 VM 宿主驗證三端點的 status、Content-Type、內容（`/version` 比較解析後的精確 JSON 物件），
並將來源 SHA、expected revision、runner、架構、container/image ID、OCI revision 與 HTTP 實測結果
寫入 Actions log／step summary；checkout、OCI 與 runtime revision 不相符即失敗。
啟動或驗證失敗時，若已有 `live` 映像則使用該映像的完整 OCI revision 注入回滾容器，
不沿用失敗候選的 SHA；回滾仍核對 OCI，workflow 仍回報失敗。
新映像以 `io.devflow.version-endpoint=1` 標記支援 `/version`，回滾時必須驗證三端點；
只有無此標記的功能上線前映像允許雙端點驗證，log 明確註記 `/version NOT verified`。
獨立審查與實際 merge／部署由下游 REVIEW／SHIP 卡執行。

## 共用驗證與瀏覽器證據

`.devflow/verify.sh` 是 PR 與部署的同一入口，目前只驗證既有 baseline：
`/health`、純文字首頁、完整 `/version` revision，加上真 Chromium 首頁斷言及截圖。
**不代表未實作的 stats AC-1 / AC-2 通過**；後續功能 PR 應擴充 journeys。
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
回滾使用舊 OCI revision，無 version 標記的舊映像才用 legacy 雙端點／瀏覽器首頁契約。
rootless Docker 不使用 host-loopback 作為瀏覽器 URL，且容器 UID 0 對應 runner owner。

CI 保留原本 x64／ARM64 test matrix，另有兩架構真實 compose + browser verify matrix。
`devflow-ci` 只接受 test、verify 均為 success（skipped 也失敗）。
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
