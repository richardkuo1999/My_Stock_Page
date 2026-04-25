#!/usr/bin/env python3
"""快速檢查 Analysis Bot 狀態：Token、連線、指令註冊"""
import os
import sys
from pathlib import Path

# 載入 .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

def main():
    token = os.getenv("TELEGRAM_TOKEN", "").strip().strip('"')

    print("=== Analysis Bot 診斷 ===\n")

    # 1. Token
    if not token:
        print("❌ TELEGRAM_TOKEN 未設定（.env 或環境變數）")
        return 1
    print(f"✅ TELEGRAM_TOKEN 已設定（長度 {len(token)}）")

    # 2. 測試 Bot API
    try:
        import asyncio
        from telegram import Bot

        async def test():
            bot = Bot(token=token)
            me = await bot.get_me()
            print(f"✅ Bot 連線成功：@{me.username} (id={me.id})")
            return me.username

        username = asyncio.run(test())
        print(f"\n👉 請在 Telegram 搜尋 @{username}，對「這個」Bot 發送指令")
        print("   例：/p 2330（股價）、/spike（爆量）、/hold981（持股變化）")
        print("   （若你用的是 cc-connect 的 Bot，不會有反應）\n")

    except Exception as e:
        print(f"❌ Bot API 連線失敗：{e}")
        if "Timed out" in str(e) or "timeout" in str(e).lower():
            print("\n可能原因：網路無法連到 api.telegram.org（防火牆、代理、地區限制）")
            print("請檢查 uvicorn 終端：若出現「Telegram bot failed to start」，")
            print("代表 Bot 沒啟動 → /spike 不會有反應（因為沒有 Bot 在收訊息）")
        return 1

    print("若指令仍無反應，請確認：")
    print(f"  1. 是對 @{username} 發送，不是對 cc-connect 的 Bot")
    print("  2. uvicorn 已啟動且終端有印出「Bot started.」")
    print("  3. 發送指令時，觀察 uvicorn 終端是否有錯誤或 price_command received 日誌")
    return 0

if __name__ == "__main__":
    sys.exit(main())
