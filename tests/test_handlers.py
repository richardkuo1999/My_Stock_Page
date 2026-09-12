"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import (
    ask_command,
    help_command,
    kchart_command,
    price_command,
    start_command,
)


@pytest.fixture
def context():
    """Create a mock context."""
    ctx = MagicMock()
    ctx.bot = MagicMock()
    ctx.bot.username = "test_bot"
    ctx.bot_data = {}
    return ctx


@pytest.fixture
def mock_bridge():
    """Create a mock AgentBridge."""
    from agent.bridge import AgentResult

    bridge = AsyncMock()
    bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="Agent 回覆內容")
    )
    return bridge


def _make_ask_update(text: str):
    """Helper to create an update for a /ask command message."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    update.effective_chat = MagicMock()
    update.effective_chat.id = 999
    return update


# --- /ask + Agent routing tests ---


@pytest.mark.asyncio
async def test_ask_routes_to_bridge(context, mock_bridge):
    """/ask handler routes text to bridge and replies with response."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 分析台積電")

    with patch("agent.conversation_log.log_conversation"):
        await ask_command(update, context)

    # The handler wraps the question with the system prompt before sending.
    mock_bridge.send_detailed.assert_called_once()
    sent_prompt = mock_bridge.send_detailed.call_args[0][0]
    assert "分析台積電" in sent_prompt
    assert "台股投資輔助助理" in sent_prompt  # system prompt is prepended
    # No tools used → reply is just the response (no tools line appended).
    update.message.reply_text.assert_called_once_with("Agent 回覆內容")


@pytest.mark.asyncio
async def test_ask_appends_tools_line(context, mock_bridge):
    """When the Agent used tools, the reply includes the tools-used line."""
    from agent.bridge import AgentResult, ToolCall

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(
            response="台積電 2410",
            tools=[
                ToolCall(
                    name="run_command",
                    parameters={"Command": "python tools/analysis/get_stock_price.py 2330"},
                )
            ],
        )
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "1"}
    ):
        await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "台積電 2410" in reply
    assert "🔧 本次用了（" in reply
    assert "run_command" in reply


@pytest.mark.asyncio
async def test_ask_appends_quota_line(context, mock_bridge):
    """回覆附上剩餘額度（bridge.fetch_usage_limits 的結果）。"""
    from agent.bridge import AgentResult

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="台積電 2410", usage={"total_tokens": 500})
    )
    mock_bridge.fetch_usage_limits = AsyncMock(
        return_value=[
            {"group": "Gemini", "window": "週", "remaining_pct": 98, "reset_at": ""},
        ]
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "1"}
    ):
        await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "🎟️ 額度（已用／剩餘）" in reply
    assert "Gemini：週 2%／98%" in reply
    assert "📊 Token：500" in reply


@pytest.mark.asyncio
async def test_ask_shows_quota_consumed_this_turn(context, mock_bridge):
    """呼叫前後各查一次額度，差值顯示為「本次 -N%」。"""
    from agent.bridge import AgentResult

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="台積電 2410")
    )
    # 第一次（呼叫前）98%，第二次（呼叫後）96% → 本次用掉 2%
    mock_bridge.fetch_usage_limits = AsyncMock(
        side_effect=[
            [{"group": "Gemini", "window": "週", "remaining_pct": 98, "reset_at": ""}],
            [{"group": "Gemini", "window": "週", "remaining_pct": 96, "reset_at": ""}],
        ]
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "1"}
    ):
        await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "Gemini：週 4%／96%（本次 -2%）" in reply
    assert mock_bridge.fetch_usage_limits.await_count == 2   # 前 + 後


@pytest.mark.asyncio
async def test_ask_appends_quota_estimate_from_ledger(context, mock_bridge, tmp_path):
    """有校準資料時，回覆附上「本次 ≈ 額度幾 %」估算。"""
    from agent import quota_ledger
    from agent.bridge import AgentResult

    ledger = tmp_path / "ledger.jsonl"
    # 先造出校準資料：200k tokens 對應 1 個百分點
    quota_ledger.record(100_000, [{"group": "Gemini", "window": "週", "remaining_pct": 98}], path=ledger)
    quota_ledger.record(100_000, [{"group": "Gemini", "window": "週", "remaining_pct": 97}], path=ledger)

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="台積電 2410", usage={"total_tokens": 100_000})
    )
    mock_bridge.fetch_usage_limits = AsyncMock(
        return_value=[{"group": "Gemini", "window": "週", "remaining_pct": 97, "reset_at": ""}]
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.object(
        quota_ledger, "DEFAULT_PATH", ledger
    ), patch.dict("os.environ", {"SHOW_AGENT_TOOLS": "1"}):
        await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "本次 ≈ Gemini 週額度 0.50%" in reply    # 100k / 200k
    assert "約可再跑 194 次" in reply               # 97 / 0.5


@pytest.mark.asyncio
async def test_ask_survives_quota_lookup_failure(context, mock_bridge):
    """額度查詢失敗時照常回覆，只是不顯示額度。"""
    from agent.bridge import AgentResult

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="台積電 2410")
    )
    mock_bridge.fetch_usage_limits = AsyncMock(side_effect=RuntimeError("boom"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "1"}
    ):
        await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "台積電 2410" in reply
    assert "🎟️" not in reply


@pytest.mark.asyncio
async def test_ask_tools_line_hidden_when_disabled(context, mock_bridge):
    """SHOW_AGENT_TOOLS=0 suppresses the tools-used line."""
    from agent.bridge import AgentResult, ToolCall

    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(
            response="台積電 2410",
            tools=[ToolCall(name="run_command", parameters={})],
        )
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電股價")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    update.message.reply_text.assert_called_once_with("台積電 2410")


@pytest.mark.asyncio
async def test_ask_logs_conversation(context, mock_bridge):
    """Every /ask exchange is persisted via log_conversation."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 分析台積電")

    with patch("agent.conversation_log.log_conversation") as mock_log:
        await ask_command(update, context)

    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs["question"] == "分析台積電"
    assert kwargs["result"].response == "Agent 回覆內容"


@pytest.mark.asyncio
async def test_ask_timeout_error(context, mock_bridge):
    """/ask handler replies with timeout message on TimeoutError."""
    mock_bridge.send_detailed = AsyncMock(side_effect=TimeoutError("timed out"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 很慢的問題")

    await ask_command(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 暫時無法回應，請稍後再試")


@pytest.mark.asyncio
async def test_ask_runtime_error(context, mock_bridge):
    """/ask handler replies with error message on RuntimeError."""
    mock_bridge.send_detailed = AsyncMock(
        side_effect=RuntimeError("Agent error (code 1): fail")
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 壞掉的指令")

    await ask_command(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 發生錯誤，請稍後再試")


@pytest.mark.asyncio
async def test_ask_empty_text(context, mock_bridge):
    """/ask with no question replies usage hint and does not call the Agent."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask")

    await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "用法" in reply
    mock_bridge.send_detailed.assert_not_called()


@pytest.mark.asyncio
async def test_ask_only_whitespace(context, mock_bridge):
    """/ask followed by only whitespace is treated as empty."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask    ")

    await ask_command(update, context)

    reply = update.message.reply_text.call_args[0][0]
    assert "用法" in reply
    mock_bridge.send_detailed.assert_not_called()


@pytest.mark.asyncio
async def test_ask_no_bridge(context):
    """/ask replies with setup message when bridge not configured."""
    # bot_data has no "agent_bridge" key
    update = _make_ask_update("/ask 問題")

    await ask_command(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 未設定")


# --- /start, /help and quick command tests ---


def _make_command_update(text: str):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_photo = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_start_command_greets(context):
    update = _make_command_update("/start")
    await start_command(update, context)
    update.message.reply_text.assert_awaited_once()
    assert "台股" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_help_command_lists_commands(context):
    update = _make_command_update("/help")
    await help_command(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "/p" in text and "/k" in text and "/ask" in text


@pytest.mark.asyncio
async def test_price_command_no_arg(context):
    update = _make_command_update("/p")
    await price_command(update, context)
    assert "用法" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_price_command_success(context):
    update = _make_command_update("/p 2330")
    fake = {"symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0, "change_pct": 1.47, "volume": 0, "source": "fugle"}
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("bot.handlers._send_intraday_chart", new=AsyncMock()):
        await price_command(update, context)
    # last reply carries the price info
    text = update.message.reply_text.call_args[0][0]
    assert "台積電" in text and "2410" in text


@pytest.mark.asyncio
async def test_price_command_with_fundamentals(context):
    """有 fundamentals 時，/p 除價量外多列基本面欄位。"""
    update = _make_command_update("/p 2330")
    fake = {
        "symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0,
        "change_pct": 1.47, "volume": 0, "source": "fugle",
        "fundamentals": {"本益比": 27.9, "最新財報": "2026年Q2"},
    }
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("bot.handlers._send_intraday_chart", new=AsyncMock()):
        await price_command(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "台積電" in text and "2410" in text
    assert "基本面" in text
    assert "本益比" in text and "27.9" in text
    assert "最新財報" in text


@pytest.mark.asyncio
async def test_price_command_no_fundamentals_plain(context):
    """UAnalyze 失敗（無 fundamentals）時，/p 只列價量，不出現基本面段落。"""
    update = _make_command_update("/p 2330")
    fake = {
        "symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0,
        "change_pct": 1.47, "volume": 0, "source": "fugle",
    }
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("bot.handlers._send_intraday_chart", new=AsyncMock()):
        await price_command(update, context)
    text = update.message.reply_text.call_args[0][0]
    assert "台積電" in text and "2410" in text
    assert "基本面" not in text
    assert "本益比" not in text


@pytest.mark.asyncio
async def test_price_command_sends_intraday_chart(context, tmp_path):
    """/p 在回價量後，best-effort 再附上盤中分時走勢圖 photo。"""
    img = tmp_path / "intraday.png"
    img.write_bytes(b"\x89PNG\r\n")
    update = _make_command_update("/p 2330")
    fake = {"symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0,
            "change_pct": 1.47, "volume": 0, "source": "fugle"}
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("tools.analysis.draw_intraday_chart.draw",
               new=AsyncMock(return_value={"image_path": str(img)})):
        await price_command(update, context)
    # price text still sent, and the intraday chart photo is attached.
    assert any("台積電" in c.args[0] for c in update.message.reply_text.call_args_list)
    update.message.reply_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_price_command_chart_failure_is_silent(context):
    """盤中圖失敗（無資料）時，/p 價量照常回，不丟例外、不多發錯誤訊息。"""
    update = _make_command_update("/p 2330")
    fake = {"symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0,
            "change_pct": 1.47, "volume": 0, "source": "fugle"}
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("tools.analysis.draw_intraday_chart.draw",
               new=AsyncMock(return_value={"error": "找不到股票代號 2330 的盤中資料"})):
        await price_command(update, context)
    # price text sent; no photo; the chart error is swallowed (not surfaced).
    assert any("台積電" in c.args[0] for c in update.message.reply_text.call_args_list)
    update.message.reply_photo.assert_not_awaited()
    assert not any("找不到" in c.args[0] for c in update.message.reply_text.call_args_list)


@pytest.mark.asyncio
async def test_price_command_error(context):
    update = _make_command_update("/p 9999")
    with patch("tools.analysis.get_stock_price.fetch_price", new=AsyncMock(return_value={"error": "找不到股票代號 9999"})):
        await price_command(update, context)
    assert "找不到" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_kchart_command_sends_photo(context, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n")
    update = _make_command_update("/k 2330 60")
    with patch("tools.analysis.draw_kchart.draw", new=AsyncMock(return_value={"image_path": str(img)})):
        await kchart_command(update, context)
    update.message.reply_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_kchart_command_error(context):
    update = _make_command_update("/k 9999")
    with patch("tools.analysis.draw_kchart.draw", new=AsyncMock(return_value={"error": "找不到股票代號 9999 的歷史資料"})):
        await kchart_command(update, context)
    # reply_text called with error (after the "正在繪製" message)
    assert any("找不到" in c.args[0] for c in update.message.reply_text.call_args_list)


@pytest.mark.asyncio
async def test_ask_html_reply_sends_html_document(context):
    """Agent 用 FORMAT: html 時，handler 送出 .html 檔案附件（非訊息）。"""
    from agent.bridge import AgentResult

    mock_bridge = AsyncMock()
    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(
            response="FORMAT: html\n<h1>台積電</h1><table><tr><td>x</td></tr></table>"
        )
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    # 走 reply_document（附件），不是 reply_text。
    update.message.reply_document.assert_called_once()
    kwargs = update.message.reply_document.call_args.kwargs
    assert kwargs["filename"].endswith(".html")
    # 附件內容被包成完整 HTML 文件（含 CSS/樣式），且含 Agent 正文。
    doc = kwargs["document"]
    content = doc.getvalue().decode("utf-8")
    assert "<!DOCTYPE html>" in content
    assert "<style>" in content
    assert "<h1>台積電</h1>" in content
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_ask_markdown_reply_sends_md_document(context):
    """Agent 用 FORMAT: markdown 時，handler 送出 .md 檔案附件。"""
    from agent.bridge import AgentResult

    mock_bridge = AsyncMock()
    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(
            response="FORMAT: markdown\n# 台積電\n\n| 指標 | 值 |\n|---|---|\n| EPS | 45 |"
        )
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    update.message.reply_document.assert_called_once()
    kwargs = update.message.reply_document.call_args.kwargs
    assert kwargs["filename"].endswith(".md")
    content = kwargs["document"].getvalue().decode("utf-8")
    assert "# 台積電" in content
    assert "| EPS | 45 |" in content
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_ask_document_falls_back_to_text_on_error(context):
    """檔案送出失敗時，自動退回純文字訊息重送，確保收得到內容。"""
    from agent.bridge import AgentResult

    mock_bridge = AsyncMock()
    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="FORMAT: html\n<h1>台積電</h1>")
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電")
    update.message.reply_document = AsyncMock(side_effect=Exception("upload failed"))

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    # 退回純文字：reply_text 被呼叫，內容為切掉標記後的正文。
    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "<h1>台積電</h1>" in text


@pytest.mark.asyncio
async def test_ask_plain_text_reply_no_parse_mode(context):
    """無 FORMAT 標記（純文字）時，用 reply_text 送、不帶 parse_mode、不送檔案。"""
    from agent.bridge import AgentResult

    mock_bridge = AsyncMock()
    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response="台積電今天收盤 1000 元")
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 台積電")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    args, kwargs = update.message.reply_text.call_args
    assert args[0] == "台積電今天收盤 1000 元"
    assert "parse_mode" not in kwargs
    update.message.reply_document.assert_not_called()


@pytest.mark.asyncio
async def test_ask_long_text_reply_is_split(context):
    """純文字超過 4096 上限時，分段多則送出（不丟內容、不炸 too long）。"""
    from agent.bridge import AgentResult

    long_body = "\n".join(f"第{i}行內容" for i in range(2000))  # 遠超 4096 字元
    mock_bridge = AsyncMock()
    mock_bridge.send_detailed = AsyncMock(
        return_value=AgentResult(response=long_body)
    )
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_ask_update("/ask 很長的分析")

    with patch("agent.conversation_log.log_conversation"), patch.dict(
        "os.environ", {"SHOW_AGENT_TOOLS": "0"}
    ):
        await ask_command(update, context)

    # 分成多則，且每則都在上限內。
    assert update.message.reply_text.call_count >= 2
    for call in update.message.reply_text.call_args_list:
        assert len(call[0][0]) <= 4096
