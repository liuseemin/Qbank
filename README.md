# 線上出題機 Qbank

這是一個以 Flask 製作的中文題庫練習工具。使用者可以選擇一個或多個 JSON 題庫，使用依序、隨機或錯題模式練習，並查看錯題、標記題目與 Gemini AI 詳解。

## 功能

- 多題庫載入：可在啟動參數中指定一個或多個 JSON 檔案或資料夾。
- 三種出題模式：依序、隨機、錯題。
- 題號跳轉與答題進度顯示。
- 支援單選題與題別為 `複` 的多選題。
- 錯題記錄、題目標記、進度儲存與題庫搜尋。
- Gemini AI 詳解，支援一般、詳細、選項說明與串流顯示。
- PDF 表格轉 JSON、PDF 圖片擷取、題庫選項格式修正工具。

## 快速安裝

在一般 Windows 11 電腦上，不需要先下載整個專案。先下載 GitHub 上的安裝腳本，再執行它：

```powershell
$installer = Join-Path $env:TEMP ("qbank-install-" + [guid]::NewGuid().ToString("N") + ".ps1")
$installerUrl = "https://raw.githubusercontent.com/liuseemin/Qbank/main/install_windows.ps1?v=" + [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Invoke-WebRequest $installerUrl -UseBasicParsing -OutFile $installer
powershell -ExecutionPolicy Bypass -File $installer
Remove-Item $installer -Force
```

腳本會自動：

1. 找到現有的 Git，或透過 `winget` 安裝 Git for Windows。
2. 從 `https://github.com/liuseemin/Qbank` clone 專案到指定位置，預設為 `%USERPROFILE%\Qbank`。
3. 找到現有的 Python，或透過 `winget`/官方安裝程式安裝 Python 3.13。
4. 建立 clone 後專案內的 `.venv` 虛擬環境。
5. 升級 pip 並安裝 `requirements.txt` 的所有套件。
6. 建立 `json` 題庫資料夾。
7. 詢問是否要設定 `GEMINI_API_KEY`；留白仍可使用無 AI 模式。

安裝完成後，腳本會詢問 PDF 檔案或資料夾位置。若有提供，會自動執行 `pdftojson.py`、`check_and_fix_json_options.py` 與 `pdfgetimg.py`，將 JSON 題庫及 `<PDF檔名>_images` 圖片資料夾整理到 clone 專案的 `json` 資料夾。最後會在 Windows 桌面建立 `Qbank.lnk`，直接啟動正式入口並使用 `--open`。

安裝需要網路連線。若電腦沒有 `winget`，Git 必須先手動安裝；Python 則會嘗試使用 `curl.exe` 下載官方安裝程式。腳本不會刪除既有資料夾：若目標是同一個 Git repo 會更新，若是非空資料夾則會停止。

也可以直接傳入安裝位置，跳過位置詢問：

```powershell
powershell -ExecutionPolicy Bypass -File $installer -InstallPath "D:\Apps\Qbank"
```

若 PowerShell 顯示執行原則錯誤，使用上面的 `-ExecutionPolicy Bypass` 只會套用於這次執行，不會修改系統的永久設定。

若已經 clone 專案，也可以在專案根目錄執行 `install_windows.ps1`；它會使用目前專案的 Git 目錄更新並完成環境設定。`install_windows.cmd` 則適合在已經取得專案檔案後使用。

## 準備題庫

每個題庫檔案必須是 JSON 陣列。題庫可以放在專案的 `json` 資料夾，也可以放在其他資料夾，啟動時用路徑指定。例如：

```json
[
  {
    "題別": "單選題",
    "題號": "1",
    "題目": "以下哪一個是 Python 的關鍵字？",
    "選項": [
      "A. list",
      "B. class",
      "C. dict",
      "D. tuple"
    ],
    "答案": "B",
    "出處": "Python 基礎"
  }
]
```

主要欄位如下：

| 欄位 | 說明 |
| --- | --- |
| `題別` | 題型；值為 `複` 時前端會以多選題處理 |
| `題號` | 題目識別碼，建議在同一題庫內唯一 |
| `題目` | 題幹文字 |
| `選項` | 選項陣列，通常以 `A.`、`B.` 等字母開頭 |
| `答案` | 正確答案，例如 `A` 或多選答案 `AC` |
| `出處` | 可選，顯示題目來源 |
| `圖片` | 可選，使用圖片 data URL；PDF 圖片工具會產生對應資料 |

程式會在啟動時讀取指定的題庫；新增或修改 JSON 後需要重新啟動程式。

## 啟動應用程式

`quiz_web.py` 是目前正式入口。在專案根目錄開啟新的 CMD 或 PowerShell，指定題庫檔案或資料夾：

```cmd
.venv\Scripts\python.exe quiz_web.py "C:\path\to\question_banks" --open
```

`--open` 會自動開啟瀏覽器；不使用時，請手動開啟 http://127.0.0.1:5000。

也可以指定多個題庫來源：

```cmd
.venv\Scripts\python.exe quiz_web.py "C:\path\first.json" "C:\path\more_banks" --open
```

常用參數：

- `--host 0.0.0.0`：允許區域網路連線。
- `--port 5000`：修改服務埠號。
- `--wrong wrong.json` 或 `-w wrong.json`：載入錯題檔案。
- `--save progress.json` 或 `-s progress.json`：載入已儲存的進度。
- `--open` 或 `-o`：啟動後自動開啟瀏覽器。

例如讓區域網路上的其他裝置連線：

```cmd
.venv\Scripts\python.exe quiz_web.py "C:\path\to\question_banks" --host 0.0.0.0 --port 5000 --open
```

這種模式請同時注意 Windows 防火牆與不要將服務直接暴露到公網。

## 環境變數

| 變數 | 必要性 | 用途 |
| --- | --- | --- |
| `GEMINI_API_KEY` | 可選 | Gemini AI 詳解；未設定或留白時使用無 AI 模式 |

手動設定範例：

```powershell
$env:GEMINI_API_KEY = "your-gemini-api-key"
```

使用 `setx` 設定的變數只會套用到新開啟的終端機；設定後請重新開啟 CMD 或 PowerShell。

## 題庫工具

### PDF 轉 JSON

`pdftojson.py` 會讀取 PDF 表格。它預期題別、題號、題目、答案、出處位於固定欄位，若 PDF 格式不同可能需要修改欄位索引。

```powershell
.venv\Scripts\python.exe pdftojson.py "C:\path\exam.pdf"
.venv\Scripts\python.exe pdftojson.py "C:\path\pdfs" -o "json" --autoitem
```

`--autoitem` 會嘗試從題目欄位拆出 A 到 E 選項。單一 PDF 預設輸出到同目錄；資料夾輸入預設輸出到該資料夾。

### PDF 圖片擷取

`pdfgetimg.py` 會從 PDF 擷取圖片，依題號輸出到 `<PDF檔名>_images` 資料夾。這個圖片資料夾必須和對應的題庫 JSON 檔案放在同一個資料夾，題庫機啟動載入 JSON 時才能找到並讀取圖片。

```powershell
.venv\Scripts\python.exe pdfgetimg.py "C:\path\exam.pdf"
.venv\Scripts\python.exe pdfgetimg.py "C:\path\pdfs"
```

例如，`exam.json` 與圖片資料夾應保持以下結構：

```text
question_banks/
|-- exam.json
`-- exam_images/
  |-- exam_1.png
  `-- exam_2.png
```

啟動題庫機時，將 `question_banks` 資料夾作為題庫來源：

```cmd
.venv\Scripts\python.exe quiz_web.py "C:\path\to\question_banks" --open
```

### 修正選項格式

`check_and_fix_json_options.py` 會將全形 `Ａ` 到 `Ｅ` 轉成半形，並把修正後的檔案輸出到指定資料夾：

```powershell
.venv\Scripts\python.exe check_and_fix_json_options.py "json" -o "fixed_json"
```

## 專案結構

```text
Qbank/
|-- quiz_web.py                    # 目前正式入口：命令列載入題庫並啟動 Flask
|-- install_windows.cmd            # Windows 一鍵安裝腳本
|-- install_windows.ps1            # PowerShell 一鍵安裝腳本
|-- requirements.txt               # Python 套件版本
|-- json/                          # 題庫資料夾，不納入 Git
|-- pdftojson.py                   # PDF 表格轉 JSON
|-- pdfgetimg.py                   # PDF 圖片擷取
|-- check_and_fix_json_options.py  # 題庫選項格式修正
|-- templates/                     # Jinja2 HTML 頁面
|-- static/                        # CSS 與前端靜態檔案
|-- app.py                         # 舊版/另一個 Flask 實作
|-- app_old.py                     # 舊版 app.py，僅供參考
|-- quiz_web_old.py                # 舊版 quiz_web.py，僅供參考
`-- Procfile                       # 部署用設定：gunicorn app:app
```

## 常見問題

### 題庫選擇頁沒有檔案

確認啟動指令傳入正確的檔案或資料夾路徑，副檔名是 `.json`，且檔案最外層是陣列 `[...]`。檢查 JSON 語法後重新啟動應用程式。

### AI 詳解無法使用

確認 `GEMINI_API_KEY` 有效，並確認網路可連線。AI 請求會產生 Google Gemini API 使用量，相關費用與限制請以 Google 官方帳戶設定為準。

### PDF 轉換結果不完整

PDF 轉換器只支援符合程式預期表格欄位的 PDF。請先檢查 PDF 是否包含可擷取的表格文字，而不是掃描影像；必要時使用 `--autoitem` 或調整 `pdftojson.py` 的欄位設定。

## 部署提示

`Procfile` 目前仍使用 `gunicorn app:app`，這是舊版 `app.py` 的部署設定。正式入口 `quiz_web.py` 使用命令列參數載入題庫並啟動 Flask；部署時請自行設定 `GEMINI_API_KEY`，並使用平台的安全 secret 管理功能，不要把 API Key 提交到 Git。
