FROM python:3.11-slim

# 安裝系統依賴 + Node.js (for Claude Code CLI)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安裝 Python 依賴
COPY analysis_bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 安裝 playwright browsers
RUN playwright install chromium --with-deps

# 不 COPY 程式碼，用 volume mount 掛入（開發模式）

EXPOSE 8000

CMD ["uvicorn", "analysis_bot.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
