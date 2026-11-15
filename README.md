# devflow-smoke

僅使用 Python 標準函式庫的 HTTP 服務（Python 3.14）。

```sh
python3 app.py                 # 預設 0.0.0.0:8080
PORT=8090 python3 app.py       # 可覆寫監聽埠
.devflow/test.sh               # unittest：動態埠真實 HTTP 與 smoke 反例
python3 smoke.py http://127.0.0.1:8080
```

| GET 路徑 | 狀態碼 | Content-Type | 精確 body（無換行） |
| --- | --- | --- | --- |
| `/health` | 200 | `application/json` | `{"status":"ok"}` |
| `/` | 200 | `text/plain; charset=utf-8` | `hello devflow` |

其他路徑回傳 404。

## 容器與 CI

有 Docker daemon 時執行：

```sh
GITHUB_SHA=$(git rev-parse HEAD) .devflow/container-smoke.sh
```

此入口會 build、run、從宿主的動態 loopback 埠驗證雙端點、核對 OCI revision，並清理容器。
PR／分支 CI 在 GitHub-hosted x64 與 ARM64 runner 對完整來源 SHA 執行 unittest 與同一容器驗證。

## 部署驗收

僅 `main` push 或經授權的 `main` workflow_dispatch 觸發 `.github/workflows/deploy.yml`，
在 Oracle self-hosted ARM64 devflow runner 執行 `.devflow/deploy.sh`；不需要新增 secrets。
Compose 固定 loopback 綁定 `127.0.0.1:18100:8080`，不設定公開 ingress。

部署使用 SHA image tag，完整 `GITHUB_SHA` 作為 `VCS_REF` 寫入 OCI revision。
部署後從 VM 宿主驗證雙端點的 status、Content-Type、精確 body，並將來源 SHA、runner、架構、
container/image ID 與 OCI revision 寫入 Actions log／step summary；revision 不相符即失敗。
啟動或驗證失敗時，若已有 `live` 映像則回滾並重驗雙端點，但 workflow 仍回報失敗。
獨立審查與實際 merge／部署由下游 REVIEW／SHIP 卡執行。
