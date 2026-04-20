# 腳本說明

## 元大投顧報告下載 (yuanta_report_downloader.py)

自動登入元大投顧網站並下載每日最新研究報告。

### 前置需求

1. 在專案根目錄 `.env` 設定：
   ```
   YT_ACCOUNT=你的帳號
   YT_PASSWORD=你的密碼
   ```

2. 安裝依賴：
   ```bash
   pip install -r scripts/requirements-yuanta.txt
   playwright install chromium
   brew install tesseract   # macOS，用於驗證碼 OCR
   ```

### 使用方式

```bash
# 有頭模式（可看到瀏覽器，方便除錯）
python scripts/yuanta_report_downloader.py

# 無頭模式（背景執行）
python scripts/yuanta_report_downloader.py --headless
```

### 輸出

報告會儲存於 `reports/yuanta/` 目錄，檔名格式：`YYYY-MM-DD_檔名.pdf`。

### 自訂設定（選填，寫入 .env）

| 變數 | 說明 |
|------|------|
| `YT_LOGIN_URL` | 登入頁網址 |
| `YT_REPORT_URL` | 報告列表頁網址 |
| `YT_REPORT_OUTPUT_DIR` | 報告儲存路徑 |

### 驗證碼

腳本會自動截圖驗證碼並用 Tesseract OCR 辨識。若辨識失敗，會暫停請您手動輸入。

### 注意事項

- 元大網站結構可能變更，若登入或下載失敗，請以有頭模式執行並觀察頁面，再回報需調整的選擇器。
