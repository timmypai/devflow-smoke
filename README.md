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
