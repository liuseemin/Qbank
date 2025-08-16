# 線上出題機

這是一個基於 Flask 的線上測驗應用程式，可以幫助你複習題庫。它提供了多種測驗模式（隨機、順序、錯題練習），並整合了 AI 詳解功能，提供更完整的學習體驗。

![](qbank_full.png)

-----

## 主要功能

  * **多樣化的測驗模式**：
      * `隨機出題`：從題庫中隨機挑選題目。
      * `順序出題`：依照題號順序出題。
      * `錯題練習`：只練習你答錯過的題目。
  * **即時回饋**：提交答案後，會立即顯示對錯，並標示正確答案。
  * **AI 詳解**：點擊按鈕即可透過 Google Gemini AI 取得詳細的題目解釋，幫助你理解概念。
  * **錯題與標記追蹤**：
      * 系統會自動記錄你答錯的題目，方便日後進行錯題複習。
      * 你可以手動標記特別需要關注的題目。
  * **題號跳轉**：支援手動輸入題號，快速跳轉至特定題目。
  * **視覺化介面**：美觀且直觀的使用者介面，提供良好的測驗體驗。

-----

## 如何安裝與執行

### 前置條件

1.  **Python 3.x**：確保你的系統已安裝 Python。
2.  **pip**：Python 的套件管理工具。
3.  **Gemini API Key**：你需要從 [Google AI Studio](https://aistudio.google.com/app/apikey) 取得一個免費的 Gemini API Key。

### 設定步驟

1.  **複製專案**：

    ```bash
    git clone https://github.com/liuseemin/Qbank.git
    cd 線上出題機
    ```

2.  **建立虛擬環境並安裝所需套件**：

    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # macOS / Linux
    source venv/bin/activate

    pip install Flask google-generativeai
    ```

3.  **設定環境變數**：
    為了安全地使用你的 Gemini API Key，請將其設為環境變數。

    **macOS / Linux**
    在終端機中執行：

    ```bash
    export GEMINI_API_KEY="你的API金鑰"
    ```

    **Windows (PowerShell)**
    在 PowerShell 中執行：

    ```powershell
    $env:GEMINI_API_KEY = "你的API金鑰"
    ```

4.  **準備題庫 (`data.json`)**：
    在專案根目錄下建立一個名為 `data.json` 的檔案，其格式如下：

    ```json
    [
      {
        "題號": "1",
        "題目": "以下哪一個是 Python 的關鍵字？",
        "選項": ["A. list", "B. class", "C. dict", "D. tuple"],
        "答案": "B"
      },
      {
        "題號": "2",
        "題目": "HTTP 協定的預設 Port 是？",
        "選項": ["A. 80", "B. 443", "C. 21", "D. 22"],
        "答案": "A"
      }
    ]
    ```

5.  **啟動應用程式**：
    在專案根目錄下執行：

    ```bash
    python quiz_web.py "data.json"
    ```

    然後打開你的瀏覽器，前往 `http://127.0.0.1:5000` 即可開始使用。

-----

## 專案結構

```
線上出題機/
├── quiz_web.py                # 核心應用程式：處理路由、出題邏輯、AI 詳解生成
├── data.json                  # 題庫檔案：儲存所有題目、選項與答案
├── pdftojson.json             # 用pdf產生題庫檔案：抓取pdf中表格產生json(抓取欄位需自行設定)
├── templates/
│   ├── index.html             # 前端介面：應用程式的主要使用者介面
│   ├── review.html            # 錯題記錄：自動記錄所有答錯的題目
│   └── review_marked.html     # 標記題目：儲存使用者手動標記的題目
└── README.md                  # 專案說明：介紹專案功能、安裝與使用方法
```

-----

## PDF 轉 JSON 題庫工具 (pdftojson.py)

這個 Python 腳本可以將特定格式的 PDF 表格自動轉換為 JSON 格式的題庫，方便用於線上測驗或其他應用程式。

### 功能

  * **自動化轉換**：將 PDF 中的表格內容解析為結構化的 JSON 資料。
  * **支援單一檔案與資料夾**：可以處理單個 PDF 檔案，也可以批次處理整個資料夾中的所有 PDF。
  * **自動拆分選項**：可選擇自動從題目內容中辨識並拆分出選項（A, B, C, ...），讓匯出資料更完整。

### 使用方法

首先，請確認你已安裝必要的函式庫：

```bash
pip install pdfplumber
```

-----

#### 轉換單一 PDF 檔案

你可以直接指定一個 PDF 檔案路徑。腳本會將轉換後的 JSON 檔案儲存在相同目錄下，並以 `.json` 作為副檔名。

```bash
python pdf_to_json.py your_file.pdf
```

**自訂輸出路徑**

使用 `-o` 或 `--output` 參數來指定 JSON 檔案的輸出路徑。

```bash
python pdf_to_json.py your_file.pdf -o output_directory/result.json
```

-----

#### 批次轉換整個資料夾

如果你指定一個資料夾路徑，腳本會自動轉換該資料夾內所有的 PDF 檔案。

```bash
python pdf_to_json.py your_folder/
```

**自訂輸出資料夾**

你可以使用 `-o` 或 `--output` 參數來指定 JSON 檔案的輸出資料夾。

```bash
python pdf_to_json.py your_folder/ -o output_folder/
```

-----

#### 自動拆分選項

如果你的 PDF 格式是題目和選項都在同一個欄位，可以使用 `--autoitem` 參數讓腳本嘗試自動拆分。

```bash
python pdf_to_json.py your_file.pdf --autoitem
```

### 轉換後的 JSON 格式範例

腳本會生成一個包含題目資訊的 JSON 陣列，格式如下：

```json
[
  {
    "題別": "單選題",
    "題號": "1",
    "題目": "太陽系中，哪一個行星是離太陽最近的？",
    "選項": [
      "A. 水星",
      "B. 金星",
      "C. 地球",
      "D. 火星"
    ],
    "答案": "A",
    "出處": "天文學"
  },
  ...
]
```
