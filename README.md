# Qbank 線上出題機

Qbank 是 Flask 題庫練習工具。本機與 Render 現在使用同一套應用程式，可由瀏覽器上傳 JSON 或含圖片的 ZIP、複選多份題庫一起作答，並隨時回到題庫選單切換。

## 主要功能

- 瀏覽器上傳單一或多個 `.json` / `.zip` 題庫。
- 同時選擇多份題庫，並提供全選／反選；重複題號也不會互相覆蓋。
- 同名題庫會略過並顯示警告；清單可查看圖檔偵測數量及刪除個人題庫。
- 依序、隨機、錯題模式，包含錯題、標記、搜尋與進度下載。
- 單選及 `複`、`複選題`、`多選題`。
- AI 詳解支援 Gemini、OpenAI、Anthropic Claude 與 Ollama/OpenAI-compatible 模型。
- 可不啟用 AI；此時完全隱藏詳解功能，答題視窗置中顯示。
- 搜尋結果會高亮關鍵字（亦支援既有的 `r/` 正規表示式搜尋）。
- SQLite server-side state，支援同一 Render instance 的多個 Gunicorn worker。

## 題庫格式

每個 JSON 最外層必須是陣列，每題至少包含 `題號`、`題目`、`選項`、`答案`：

```json
[
  {
    "題別": "單選題",
    "題號": "1",
    "題目": "以下哪個是 Python 關鍵字？",
    "選項": ["A. list", "B. class", "C. dict", "D. tuple"],
    "答案": "B",
    "出處": "Python 基礎"
  }
]
```

圖片可直接是 JSON 裡的 image data URL，也可以打包成 ZIP：

```text
question-pack.zip
└─ exam/
   ├─ exam.json
   └─ exam_image/
      ├─ exam_1.png
      └─ exam_2.jpg
```

圖片資料夾使用 `<題庫名>_image`（也相容舊版 `_images`）；圖片命名可用 `<題庫名>_<題號>.<副檔名>` 或 `<題號>.<副檔名>`，支援 PNG、JPEG、GIF、WebP。ZIP 可放多份 JSON，系統會分別建立題庫。

## 本機執行

```powershell
uv sync
uv run python quiz_web.py --open
```

開啟後可在登入頁選擇無 AI、Gemini、OpenAI、Anthropic 或 Ollama，填入模型名稱及需要的 Key，再於題庫選單上傳檔案。Ollama 預設端點為 `http://127.0.0.1:11434/v1`。也可預載一個或多個檔案／目錄；互動式終端會顯示複選器：

```powershell
uv run python quiz_web.py "C:\path\to\banks" --open
uv run python quiz_web.py first.json second.json --open
```

常用參數：`--host`、`--port`、`--database`、`--open`。若設定 `APP_PASSWORD`，登入頁會要求網站密碼。

執行測試：

```powershell
uv run python -m unittest discover -s tests -v
```

## Render 部署

專案已包含 `render.yaml`、`Procfile` 與精簡的 `requirements-render.txt`。完整變更與逐步部署說明請見 [RENDER_DEPLOYMENT.md](RENDER_DEPLOYMENT.md)。

## 題庫製作工具

既有工具仍保留：

```powershell
uv run python pdftojson.py "C:\path\exam.pdf" --autoitem
uv run python pdfgetimg.py "C:\path\exam.pdf"
uv run python check_and_fix_json_options.py "json" -o "fixed_json"
```

`app_old.py` 與 `quiz_web_old.py` 僅供歷史參考，不是啟動入口。
