# Qbank Render 改造與部署說明

## 修改摘要

### 統一執行架構

- `app.py` 改為 Flask app factory，同時輸出 `app` 供 Gunicorn 使用。
- `quiz_web.py` 改為同一個 app factory 的本機 CLI wrapper；不再另維護一套 route 與 process globals。
- `main.py` 也指向相同 CLI 入口。
- `Procfile` 與 `render.yaml` 使用 2 個 Gunicorn worker、每個 worker 4 threads。
- 新增 `/healthz` 作為 Render health check。
- Health check 不建立瀏覽器 session，避免平台輪詢持續製造無用資料列。

### 修正 worker 與題目索引不穩定

舊版在 Python module globals 儲存題庫、剩餘題目、索引、錯題、標記與 AI cache。Gunicorn worker 各有自己的記憶體，因此連續請求如果被分配到不同 worker，會看到不同資料。

新版將下列資料放入 SQLite：

- 使用者上傳的題庫與已正規化題目。
- 目前選取的題庫、題目順序、剩餘題目與作答進度。
- 錯題、標記、AI cache 與 token 統計。
- 使用者自行選擇的 AI provider、模型、端點與 API Key。

瀏覽器的簽章 cookie 只保存隨機 session ID 與登入狀態，不再塞入題目、AI 輸出或 API Key。SQLite 啟用 WAL、busy timeout，且每次操作明確關閉 connection，讓同一 Render service instance 內的多個 Gunicorn worker 能安全讀取相同狀態。

每題的內部 key 使用 `<bank UUID>:<index>`，畫面仍顯示原題號。即使複選的兩份題庫都有題號 `1`，也不會再發生 dictionary 覆蓋、跳題或抓到另一題庫答案。

### 題庫上傳與切換

- 題庫選單可一次上傳多個 JSON 或 ZIP。
- 一個 ZIP 可含多份 JSON，以及各自的 `<題庫名>_image` 圖片目錄（相容 `_images`）。
- 圖片會在匯入時轉成 data URL，因此各 worker 不依賴暫存解壓目錄。
- 題庫清單顯示每份題庫偵測到的圖檔數量，並可刪除使用者自己的上傳題庫。
- 題庫名稱採不分大小寫的原子重名檢查；即使兩個 worker 同時上傳，也只會建立一份，略過項目會顯示 warning。
- 題庫清單使用 checkbox，可複選、全選、反選並合併作答。
- 作答頁新增「更換題庫」，重新選擇時會建立乾淨的新進度，避免錯題混到另一組題庫。
- CLI 仍支援多個路徑與目錄複選；匯入資料也走同一個驗證／儲存層。

### 多 AI provider、fallback 與安全性

- 登入頁可選 Gemini、OpenAI Responses API、Anthropic Messages API，或 Ollama/OpenAI-compatible API，模型名稱不寫死。
- Gemini、OpenAI、Anthropic 需要個人 API Key；Ollama 可不填 Key並可設定 base URL。
- 選擇無 AI 時，不渲染 AI 按鈕、設定、詳解面板或詳解紀錄入口，答題區改為置中；AI endpoints 也回傳 HTTP 403。
- API Key 只存於 server-side SQLite，登出時清除，不放進 Flask client-side cookie。
- AI cache 指紋包含 provider、模型、base URL 與 prompt，切換模型後不會誤用舊快取。
- Render 環境的自訂 AI endpoint 必須是公開 HTTPS 網址，並拒絕 loopback／私人 IP，避免 server-side request forgery。因而 Render 上不能直接連到使用者電腦的 `localhost` Ollama；需使用具 HTTPS 與存取控制的公開端點。
- AI route 只接受目前使用者已選題庫內的 internal question key，不能用偽造 request 任意建立詳解。

### 其他修正與防護

- 驗證 JSON 最外層、必要欄位及選項型別，錯誤檔案不會建立半成品題庫。
- ZIP 不實際解壓到檔案系統，拒絕 `..` traversal，並限制解壓後總容量。
- Flask 限制 request upload size，預設 25 MB，可由 `MAX_UPLOAD_MB` 調整。
- 答案以 server-side 原題判定，不信任瀏覽器送回的答案欄位。
- 多選答案會先移除分隔符並排序，`AC`、`C,A` 可得到一致判定。
- 搜尋頁以 DOM text node 與 `<mark>` 安全建立高亮內容，避免上傳題庫文字形成 stored XSS。
- 修正 SQLite connection 未關閉造成 Windows 鎖檔與 descriptor 累積的問題。
- Render production 若缺少 `APP_SECRET_KEY` 會拒絕啟動，避免不同 workers 各自產生 secret 或使用不安全預設值。

## 測試

測試位於 `tests/`，使用 Python `unittest` 與 Flask test client。涵蓋：

- 多 JSON 上傳與題號碰撞。
- 兩個獨立 app instance 共用資料庫，模擬請求切換 Gunicorn worker。
- ZIP 圖片配對與 data URL。
- ZIP path traversal 拒絕。
- 題庫切換後進度隔離。
- API Key 選填、server-side 保存與無 AI UI。
- OpenAI、Anthropic、Ollama request 格式、回應解析、SSE 串流與 token 統計。
- 同名略過、`_image` 圖檔狀態、刪除、全選／反選、無 AI 置中及安全搜尋高亮。
- 無效 JSON 以及偽造／未選題目拒絕。

```bash
python -m unittest discover -s tests -v
```

## 部署到 Render

### 建議方式：Blueprint + persistent disk

此方式會保留使用者上傳的題庫與作答狀態。Render persistent disk 需要付費 web service，且掛載 disk 的 service 固定為單一 instance；本專案在該 instance 內以多個 Gunicorn workers 提供並行處理。

1. 將修改後的專案 push 到 GitHub。
2. 登入 Render Dashboard，選擇 **New > Blueprint**。
3. 連結 GitHub repository。Render 會讀取根目錄的 `render.yaml`。
4. 確認 service 規格：
   - Runtime：Python
   - Region：Singapore
   - Build：`pip install -r requirements-render.txt`
   - Start：`gunicorn --workers 2 --threads 4 --timeout 180 --bind 0.0.0.0:$PORT app:app`
   - Health check：`/healthz`
   - Disk mount：`/var/data`，1 GB
5. `APP_SECRET_KEY` 由 Blueprint 的 `generateValue: true` 自動建立。部署後不要更換，否則現有登入 cookie 會失效。
6. 若網站要加共用密碼，在 service 的 **Environment** 新增 `APP_PASSWORD`；不設定就只顯示 API Key 選填欄位。
7. 部署完成後開啟 `https://<service-name>.onrender.com/healthz`，應看到 `{"status":"ok"}`。
8. 開啟首頁登入，選擇 AI provider（或無 AI）、上傳題庫並測試切換。API Key 由每位使用者自行輸入，不需在 Render 設定全站 AI secret。

若選 Ollama，Render 不能連線至使用者本機的 `127.0.0.1:11434`。請提供可由 Render 存取、使用 HTTPS 且有身份驗證／網路防護的 Ollama-compatible endpoint；不應將未保護的 Ollama 服務直接公開到 Internet。

`render.yaml` 已將 `RENDER_DISK_PATH=/var/data`。程式會在該目錄建立 `qbank.sqlite3`、WAL 與同步檔；只有這個 mount path 下的資料會跨重啟／部署保留。

### 免費方案測試

如果只想短暫驗證，可在 Render 建立 free web service，使用同樣 build/start command，但不要加 disk，並設定：

```text
APP_SECRET_KEY=<固定且足夠長的隨機字串>
DATABASE_PATH=/tmp/qbank.sqlite3
```

多 worker 在該次 instance 存活期間仍共享 SQLite，因此不會重現 process-global index 問題；但 free/ephemeral filesystem 在 restart、spin-down 或 redeploy 後會遺失所有上傳與進度，不適合正式使用。

### 環境變數

| 名稱 | 必要 | 說明 |
| --- | --- | --- |
| `APP_SECRET_KEY` | Render 必要 | 固定的 Flask cookie 簽章 secret；Blueprint 自動產生 |
| `RENDER_DISK_PATH` | 建議 | persistent disk 目錄，Blueprint 為 `/var/data` |
| `DATABASE_PATH` | 選填 | 完整 SQLite 路徑；設定後優先於 `RENDER_DISK_PATH` |
| `APP_PASSWORD` | 選填 | 全站共用登入密碼 |
| `MAX_UPLOAD_MB` | 選填 | request 上傳上限，預設 25 |

### 架構限制與升級方向

SQLite + persistent disk 解決的是「同一個 service instance 中，多個 Gunicorn worker」的穩定性。Render 官方限制掛載 disk 的 service 不能水平擴充成多個 instances。如果日後需要多 instances、自動擴展或零停機部署，應把 `QBankStore` 換成 Render Postgres，圖片改存 object storage；不要讓多個 instances 各用一份本機 SQLite。

官方參考：

- https://render.com/docs/deploy-flask
- https://render.com/docs/blueprint-spec
- https://render.com/docs/disks
