# Analysis Bot - 投資輔助系統

## Rule

- Use Fugle API to get the anything about stock price(TW stock)
- Use agent-browser cli for web search.
- All API key is located in `.env` file.


## WHY
整合 Telegram Bot 與 Web 儀表板的智慧投資助理，提供股票估值分析（樂活五線譜、均值回歸）、財經新聞聚合、Podcast 摘要與每日自動掃描。

## WHAT
- **後端**: FastAPI + SQLModel + SQLite
- **Bot**: python-telegram-bot (async)
- **排程**: APScheduler
- **AI**: Gemini / Ollama (可切換)
- **資料來源**: yfinance, FinMind, Anue (鎵智)
- **前端**: Jinja2 + Vanilla JS/CSS

### 目錄結構
```
analysis_bot/
├── api/          # FastAPI 路由 (web.py)
├── bot/          # Telegram Bot 邏輯
├── models/       # SQLModel 資料模型
├── services/     # 核心商業邏輯 (AI, 股票分析, 新聞)
├── main.py       # FastAPI 進入點
├── scheduler.py  # 每日分析排程
└── config.py     # Pydantic Settings
tests/            # pytest 測試
```

## HOW

### 啟動開發
```bash
pip install -r analysis_bot/requirements.txt
uvicorn analysis_bot.main:app --reload
```

### 執行測試
```bash
python -m pytest tests/ -v
python -m pytest tests/ -v --cov=analysis_bot --cov-report=html  # 覆蓋率
```

### 環境變數
- `TELEGRAM_TOKEN`: Bot 認證
- `GEMINI_API_KEY`: Gemini API 金鑰
- `AI_PROVIDER`: `gemini` 或 `ollama`
- `OLLAMA_BASE_URL`, `OLLAMA_MODEL`: Ollama 設定

## 開發規範

### 程式碼風格
- 使用 `async/await` 處理所有 I/O 操作
- 服務層 (`services/`) 封裝商業邏輯，Bot 與 Web 共用
- 日誌使用 `logging_conf.py` 配置，Telegram ID 需遮蔽

### 架構原則
- 新功能新增於 `services/`，由 `bot/handlers.py` 或 `api/web.py` 呼叫
- 資料模型定義於 `models/`
- 新聞來源新增於 `services/news_parser.py`

---

## Progressive Disclosure

根據任務類型，閱讀對應的詳細文件：

| 任務 | 文件 |
|------|------|
| 修改 Bot 指令 | [agent_docs/bot_commands.md](agent_docs/bot_commands.md) |
| 新增資料模型 | [agent_docs/data_models.md](agent_docs/data_models.md) |
| AI 相關功能 | [agent_docs/ai_service.md](agent_docs/ai_service.md) |
| 新聞聚合邏輯 | [agent_docs/news_sources.md](agent_docs/news_sources.md) |
| 股票分析演算法 | [agent_docs/stock_analysis.md](agent_docs/stock_analysis.md) |
| 服務架構互動 | [agent_docs/service_architecture.md](agent_docs/service_architecture.md) |

**重要**: 開始任務前，先閱讀相關文件了解現有架構與慣例。
