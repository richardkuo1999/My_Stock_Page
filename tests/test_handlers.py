"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import (
    ask_command,
    help_command,
    kchart_command,
    price_command,
    start_command,
    uanalyze_command,
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
                    parameters={"Command": "python tools/get_stock_price.py 2330"},
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
    assert "🔧 本次用了：" in reply
    assert "run_command" in reply


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
    assert "/p" in text and "/k" in text and "/ua" in text


@pytest.mark.asyncio
async def test_price_command_no_arg(context):
    update = _make_command_update("/p")
    await price_command(update, context)
    assert "用法" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_price_command_success(context):
    update = _make_command_update("/p 2330")
    fake = {"symbol": "2330", "name": "台積電", "price": 2410.0, "change": 35.0, "change_pct": 1.47, "volume": 0, "source": "fugle"}
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
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
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
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
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
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
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("tools.draw_intraday_chart.draw",
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
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)), \
         patch("tools.draw_intraday_chart.draw",
               new=AsyncMock(return_value={"error": "找不到股票代號 2330 的盤中資料"})):
        await price_command(update, context)
    # price text sent; no photo; the chart error is swallowed (not surfaced).
    assert any("台積電" in c.args[0] for c in update.message.reply_text.call_args_list)
    update.message.reply_photo.assert_not_awaited()
    assert not any("找不到" in c.args[0] for c in update.message.reply_text.call_args_list)


@pytest.mark.asyncio
async def test_price_command_error(context):
    update = _make_command_update("/p 9999")
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value={"error": "找不到股票代號 9999"})):
        await price_command(update, context)
    assert "找不到" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_kchart_command_sends_photo(context, tmp_path):
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n")
    update = _make_command_update("/k 2330 60")
    with patch("tools.draw_kchart.draw", new=AsyncMock(return_value={"image_path": str(img)})):
        await kchart_command(update, context)
    update.message.reply_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_kchart_command_error(context):
    update = _make_command_update("/k 9999")
    with patch("tools.draw_kchart.draw", new=AsyncMock(return_value={"error": "找不到股票代號 9999 的歷史資料"})):
        await kchart_command(update, context)
    # reply_text called with error (after the "正在繪製" message)
    assert any("找不到" in c.args[0] for c in update.message.reply_text.call_args_list)


@pytest.mark.asyncio
async def test_uanalyze_command_shows_menu(context):
    """/ua <代號> replies with an inline keyboard menu, not a direct analysis."""
    update = _make_command_update("/ua 2330")
    await uanalyze_command(update, context)
    kwargs = update.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs  # menu shown
    assert "2330" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_uanalyze_command_no_arg(context):
    update = _make_command_update("/ua")
    await uanalyze_command(update, context)
    assert "用法" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_uanalyze_callback_runs_selected_prompt(context):
    """Pressing a menu button runs analyze() with the chosen prompt."""
    from bot.handlers import UA_PROMPTS, uanalyze_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "ua:2330:0"  # first prompt
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    with patch("tools.uanalyze.analyze", new=AsyncMock(return_value={"analysis": "近況分析內容"})) as mock_analyze:
        await uanalyze_callback(update, context)

    # analyze called with the selected prompt's FULL text (tuple element [1])
    mock_analyze.assert_awaited_once_with("2330", UA_PROMPTS[0][1])
    # final edit shows the result
    assert any("近況分析內容" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_uanalyze_callback_sends_full_long_prompt(context):
    """A long-prompt entry sends the complete prompt text, not the short label."""
    from bot.handlers import UA_PROMPTS, uanalyze_callback

    # Find a long-prompt entry (label != prompt)
    idx = next(i for i, (label, prompt) in enumerate(UA_PROMPTS) if label != prompt)
    long_label, long_prompt = UA_PROMPTS[idx]
    assert len(long_prompt) > len(long_label)  # sanity: full prompt is longer

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = f"ua:2330:{idx}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    with patch("tools.uanalyze.analyze", new=AsyncMock(return_value={"analysis": "x"})) as mock_analyze:
        await uanalyze_callback(update, context)

    mock_analyze.assert_awaited_once_with("2330", long_prompt)


@pytest.mark.asyncio
async def test_uanalyze_result_has_back_button(context):
    """The analysis result carries a '返回' button to reopen the menu."""
    from bot.handlers import uanalyze_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "ua:2330:0"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    with patch("tools.uanalyze.analyze", new=AsyncMock(return_value={"analysis": "內容"})):
        await uanalyze_callback(update, context)

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    # back button callback_data returns to this symbol's menu
    kb = kwargs["reply_markup"].inline_keyboard
    assert kb[0][0].callback_data == "ua:back:2330"


@pytest.mark.asyncio
async def test_uanalyze_back_reopens_menu(context):
    """Pressing 返回 re-shows the面向 menu for that symbol."""
    from bot.handlers import uanalyze_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "ua:back:2330"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await uanalyze_callback(update, context)

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs  # menu shown again
    assert "2330" in update.callback_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_uanalyze_callback_invalid_data(context):
    from bot.handlers import uanalyze_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "ua:2330:999"  # out-of-range index
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await uanalyze_callback(update, context)
    assert "無效" in update.callback_query.edit_message_text.call_args[0][0]


# --- /data command + callback tests (Ticket 04) ---


@pytest.mark.asyncio
async def test_data_command_shows_menu(context):
    """/data <代號> replies with an inline keyboard menu."""
    from bot.handlers import data_command

    update = _make_command_update("/data 2330")
    await data_command(update, context)
    kwargs = update.message.reply_text.call_args.kwargs
    assert "reply_markup" in kwargs
    assert "2330" in update.message.reply_text.call_args[0][0]


@pytest.mark.asyncio
async def test_data_command_no_arg(context):
    from bot.handlers import data_command

    update = _make_command_update("/data")
    await data_command(update, context)
    assert "用法" in update.message.reply_text.call_args[0][0]


def test_data_menu_keyboard_options():
    """Menu keyboard has all fifteen data buttons with data: callbacks."""
    from bot.handlers import _data_menu_keyboard

    kb = _data_menu_keyboard("2330").inline_keyboard
    flat = [btn for row in kb for btn in row]
    callbacks = {btn.callback_data for btn in flat}
    assert "data:2330:consensus" in callbacks
    assert "data:2330:pershare" in callbacks
    assert "data:2330:supply" in callbacks
    assert "data:2330:order" in callbacks
    assert "data:2330:dcf" in callbacks
    assert "data:2330:valuation" in callbacks
    assert "data:2330:chips" in callbacks
    assert "data:2330:margins" in callbacks
    assert "data:2330:cashflow" in callbacks
    assert "data:2330:dividend" in callbacks
    assert "data:2330:peers" in callbacks
    assert "data:2330:margin" in callbacks
    assert "data:2330:holders" in callbacks
    assert "data:2330:smart_estimate" in callbacks
    assert "data:2330:forecast_route" in callbacks
    assert len(flat) == 15


@pytest.mark.asyncio
async def test_data_callback_consensus(context):
    """Pressing 法人共識 calls fetch_eps_consensus and renders text."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:consensus"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "eps": {"實際EPS": [{"period": "2026Q1", "value": 22.08}]},
        "revenue": {"法人共識估計月營收": [{"month": "12", "value": 5421984179}]},
    }
    with patch("tools.uanalyze.fetch_eps_consensus", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    assert any("法人共識" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)
    assert any("22.08" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_pershare(context):
    """Pressing 財務指標 calls fetch_per_share_metrics and renders text."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:pershare"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "metrics": [{"name": "每股EPS(元)", "values": {"2025": 66.26, "2024": 45.25}}],
    }
    with patch("tools.uanalyze.fetch_per_share_metrics", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    assert any("每股EPS" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)
    assert any("66.26" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_dcf(context):
    """Pressing DCF 估值 calls fetch_dcf_valuation and renders key numbers."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:dcf"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "每股合理內在價值": 3101.0,
        "1年後前瞻合理價值": 3363.54,
        "當前時間加權基期": 91.57,
        "營收動能": "+0.1%",
        "2025實際獲利": 66.26,
        "2026E": 109.58,
        "最遠預估年份及獲利": "2030E:293.74元",
        "信心度": "高 (法人完全直連 N=5)",
    }
    with patch("tools.uanalyze.fetch_dcf_valuation", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    assert any("DCF" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)
    assert any("3101.0" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_dcf_eps_insufficient(context):
    """EPS-insufficient error dict → friendly '資料不足' prompt via error branch."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:dcf"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {"error": "2330 EPS 資料不足，無法計算 DCF"}
    with patch("tools.uanalyze.fetch_dcf_valuation", new=AsyncMock(return_value=fake)):
        await data_callback(update, context)

    assert any(
        "資料不足" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list
    )


@pytest.mark.asyncio
async def test_data_callback_has_back_button(context):
    """The result carries a back button returning to the menu."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:consensus"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {"symbol": "2330", "eps": {"實際EPS": [{"period": "2026Q1", "value": 22.08}]}}
    with patch("tools.uanalyze.fetch_eps_consensus", new=AsyncMock(return_value=fake)):
        await data_callback(update, context)

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    kb = kwargs["reply_markup"].inline_keyboard
    assert kb[0][0].callback_data == "data:back:2330"


@pytest.mark.asyncio
async def test_data_back_reopens_menu(context):
    """Pressing back re-shows the data menu for that symbol."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:back:2330"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await data_callback(update, context)

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert "reply_markup" in kwargs
    assert "2330" in update.callback_query.edit_message_text.call_args[0][0]


@pytest.mark.asyncio
async def test_data_callback_error_dict(context):
    """An error dict from the fetch → friendly message, no back button."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:9999:consensus"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    with patch("tools.uanalyze.fetch_eps_consensus", new=AsyncMock(return_value={"error": "查無 9999 的法人共識資料"})):
        await data_callback(update, context)

    assert any("查無" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_supply(context):
    """Pressing 供應鏈 calls fetch_supply_chain and lists peer codes."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:supply"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {"symbol": "2330", "peers": ["2303", "5347", "6770"], "stock_name": "台積電"}
    with patch("tools.uanalyze.fetch_supply_chain", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    assert any("供應鏈" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)
    assert any("2303" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_valuation(context):
    """Pressing PE/PB 估值 calls fetch_valuation_bands and renders PE/PB + peer median."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:valuation"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "pe": {"latest_month": "202509", "latest": 30.0, "avg_10y": 17.8,
               "percentile_in_history": 75.0, "std_bands": {"本益比(+1標準差)": 29.8},
               "peer_median": 15.2},
        "pb": {"latest_month": "202509", "latest": 1.2, "avg_10y": 1.2,
               "percentile_in_history": 66.7},
    }
    with patch("tools.uanalyze.fetch_valuation_bands", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("PE/PB" in c.args[0] for c in calls)
    assert any("15.2" in c.args[0] for c in calls)  # 同業中位數


@pytest.mark.asyncio
async def test_data_callback_chips(context):
    """Pressing 三大法人 calls fetch_institutional_chips and renders buy/sell + sum."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:chips"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "unit": "張",
        "recent_days": [
            {"date": 20260911, "外資": 1000.0, "投信": 200.0, "自營商": 50.0, "合計": 1250.0},
        ],
        "sum_recent": {"天數": 1, "外資": 1000.0, "投信": 200.0, "自營商": 50.0, "合計": 1250.0},
    }
    with patch("tools.uanalyze.fetch_institutional_chips", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("三大法人" in c.args[0] for c in calls)
    assert any("1,000" in c.args[0] for c in calls)  # 外資買超千位分隔


@pytest.mark.asyncio
async def test_data_callback_margins(context):
    """Pressing 三率趨勢 calls fetch_profit_margins and renders the 三率 table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:margins"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "unit": "%",
        "margins": {
            "毛利率": [{"period": "2026Q1", "value": 58.8}, {"period": "2026Q2", "value": 58.6}],
            "營業利益率": [{"period": "2026Q1", "value": 48.5}, {"period": "2026Q2", "value": 49.6}],
            "稅後淨利率": [{"period": "2026Q1", "value": 42.9}, {"period": "2026Q2", "value": 42.7}],
        },
        "latest": {"period": "2026Q2", "毛利率": 58.6, "營業利益率": 49.6, "稅後淨利率": 42.7},
    }
    with patch("tools.uanalyze.fetch_profit_margins", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("三率" in c.args[0] for c in calls)
    assert any("毛利率" in c.args[0] for c in calls)
    assert any("58.6" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_cashflow(context):
    """Pressing 現金流 calls fetch_cash_flow_trend and renders the flows table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:cashflow"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "unit": "千元",
        "flows": {
            "營業活動現金流": [{"period": "2026Q1", "value": 110.0}, {"period": "2026Q2", "value": 130.0}],
            "自由現金流": [{"period": "2026Q1", "value": 40.0}, {"period": "2026Q2", "value": 45.0}],
        },
        "latest": {"period": "2026Q2", "營業活動現金流": 130.0, "自由現金流": 45.0},
    }
    with patch("tools.uanalyze.fetch_cash_flow_trend", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("現金流" in c.args[0] for c in calls)
    assert any("自由" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_dividend(context):
    """Pressing 股利政策 calls fetch_dividend_policy and renders the dividend table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:dividend"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "dividends": [
            {"year": "2024", "現金股息": 13.5, "發放率(%)": 29.8},
            {"year": "2025", "現金股息": 16.0, "發放率(%)": 24.2},
        ],
        "latest": {"year": "2025", "現金股息": 16.0, "發放率(%)": 24.2},
    }
    with patch("tools.uanalyze.fetch_dividend_policy", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("股利" in c.args[0] for c in calls)
    assert any("16.0" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_peers(context):
    """Pressing 同業比較 calls fetch_peers_comparison and renders the comparison table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:peers"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "peers_compared": ["2330", "2303"],
        "rows": [
            {"stock": "2330", "本益比": 20.0, "股價淨值比": 3.0, "毛利率": 50.0},
            {"stock": "2303", "本益比": 12.0, "股價淨值比": 1.5, "毛利率": 25.0},
        ],
    }
    with patch("tools.uanalyze.fetch_peers_comparison", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("同業" in c.args[0] for c in calls)
    assert any("2303" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_margin(context):
    """Pressing 融資融券 calls fetch_margin_trading and renders the credit table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:margin"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "recent_days": [
            {"date": "20260911", "融資餘額": 36728.0, "融資使用率(%)": 1.95,
             "融券餘額": 50.0, "融券使用率(%)": 0.0},
        ],
        "latest": {"date": "20260911", "融資餘額": 36728.0},
    }
    with patch("tools.uanalyze.fetch_margin_trading", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("信用交易" in c.args[0] for c in calls)
    assert any("36,728" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_holders(context):
    """Pressing 籌碼結構 calls fetch_holder_structure and renders holdings + shareholders."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:holders"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "stock_name": "台積電",
        "holdings": [{"period": 202609, "外資持股比率": 13.22, "400張以上持股比率": 55.47}],
        "shareholders": [{"period": 202609, "總股東人數(人)": 510517,
                          "平均持有張數/人": 14.74, "400張以上持股比率(%)": 55.47,
                          "1000張以上持股比率(%)": 51.55}],
        "latest": {"holdings": {"外資持股比率": 13.22}, "shareholders": {"總股東人數(人)": 510517}},
    }
    with patch("tools.uanalyze.fetch_holder_structure", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("籌碼結構" in c.args[0] for c in calls)
    assert any("13.22" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_smart_estimate(context):
    """Pressing 法人預估 calls fetch_smart_estimate and renders the estimates table."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:smart_estimate"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "unit_note": "營收為千元…",
        "estimates": {"EPS": [{"year": "2028(f)", "平均": 181.38, "最低": 149.76, "最高": 210.6}]},
    }
    with patch("tools.uanalyze.fetch_smart_estimate", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("前瞻預估" in c.args[0] for c in calls)
    assert any("181.38" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_forecast_route(context):
    """Pressing 預估路徑 calls fetch_forecast_route and renders route + rating."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:forecast_route"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {
        "symbol": "2330",
        "route": {"未來五季EPS預估路徑": [{"period": "2027Q3(f)", "value": 38.01}]},
        "rating_trend": [{"month": "202609", "樂觀": 88.18, "中立": 11.82, "悲觀": 0.0, "收盤價": 2410.0}],
    }
    with patch("tools.uanalyze.fetch_forecast_route", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    calls = update.callback_query.edit_message_text.call_args_list
    assert any("預估路徑" in c.args[0] for c in calls)
    assert any("88.18" in c.args[0] for c in calls)


@pytest.mark.asyncio
async def test_data_callback_order(context):
    """Pressing 訂單能見度 calls fetch_order_visibility and renders text."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:3661:order"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    fake = {"symbol": "3661", "order_visibility": [{"month": "2026Q1", "visibility": "6 個月"}]}
    with patch("tools.uanalyze.fetch_order_visibility", new=AsyncMock(return_value=fake)) as mock_fn:
        await data_callback(update, context)

    mock_fn.assert_awaited_once_with("3661")
    assert any("訂單能見度" in c.args[0] for c in update.callback_query.edit_message_text.call_args_list)


@pytest.mark.asyncio
async def test_data_callback_order_no_data(context):
    """A8 sparse: error dict → friendly 查無訂單能見度 message (not blank)."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:order"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    err = {"error": "查無 2330 的訂單能見度資料"}
    with patch("tools.uanalyze.fetch_order_visibility", new=AsyncMock(return_value=err)):
        await data_callback(update, context)

    msgs = [c.args[0] for c in update.callback_query.edit_message_text.call_args_list]
    assert any("查無" in m and "訂單能見度" in m for m in msgs)


@pytest.mark.asyncio
async def test_data_callback_invalid_key(context):
    """Unknown key → invalid option message."""
    from bot.handlers import data_callback

    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = "data:2330:bogus"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await data_callback(update, context)
    assert "無效" in update.callback_query.edit_message_text.call_args[0][0]


# --- 法說會逐字稿 /ua 選單 + 分頁快取 tests (Ticket 07) ---


def _tx_update(callback_data: str):
    update = MagicMock()
    update.callback_query = MagicMock()
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


def test_ua_menu_has_transcript_button():
    """/ua 選單末列有「法說會逐字稿」入口，callback 用 tx:list: prefix。"""
    from bot.handlers import _ua_menu_keyboard

    kb = _ua_menu_keyboard("2330").inline_keyboard
    flat = [btn for row in kb for btn in row]
    callbacks = {btn.callback_data for btn in flat}
    assert "tx:list:2330" in callbacks


@pytest.mark.asyncio
async def test_transcript_list_shows_dates(context):
    """tx:list lists each transcript date as a tx:show:{id}:0 button."""
    from bot.handlers import transcript_callback

    update = _tx_update("tx:list:2330")
    fake = {
        "symbol": "2330",
        "transcripts": [
            {"date": "2026/07/16", "id": "202607162330"},
            {"date": "2026/04/16", "id": "202604162330"},
        ],
    }
    with patch(
        "tools.uanalyze.fetch_transcript_list", new=AsyncMock(return_value=fake)
    ) as mock_fn:
        await transcript_callback(update, context)

    mock_fn.assert_awaited_once_with("2330")
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    kb = kwargs["reply_markup"].inline_keyboard
    flat = [btn for row in kb for btn in row]
    callbacks = {btn.callback_data for btn in flat}
    assert "tx:show:202607162330:0" in callbacks
    assert "tx:show:202604162330:0" in callbacks


@pytest.mark.asyncio
async def test_transcript_show_first_page(context):
    """tx:show first page renders text and has NO 上一頁 button (page 0)."""
    from bot.handlers import _transcript_cache, transcript_callback

    _transcript_cache.clear()
    long_text = "甲" * 8000  # 3 頁 @ 3500/頁
    update = _tx_update("tx:show:202607162330:0")
    with patch(
        "tools.uanalyze.fetch_transcript_detail",
        new=AsyncMock(return_value={"id": "202607162330", "title": "T", "date": "20260716", "stock": "2330", "transcript": long_text}),
    ):
        await transcript_callback(update, context)

    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    kb = kwargs["reply_markup"].inline_keyboard
    flat = [btn for row in kb for btn in row]
    texts = [btn.text for btn in flat]
    # 第一頁：無「上一頁」，有「下一頁」
    assert not any("上一頁" in t for t in texts)
    assert any("下一頁" in t for t in texts)
    # 頁碼提示
    body = update.callback_query.edit_message_text.call_args[0][0]
    assert "第 1/3 頁" in body


@pytest.mark.asyncio
async def test_transcript_paging_does_not_refetch(context):
    """翻頁不重打 API：連續翻兩頁，fetch_transcript_detail 只被呼叫一次（快取）。"""
    from bot.handlers import _transcript_cache, transcript_callback

    _transcript_cache.clear()
    long_text = "乙" * 8000  # 3 頁
    detail = {"id": "202607162330", "title": "T", "date": "20260716", "stock": "2330", "transcript": long_text}

    with patch(
        "tools.uanalyze.fetch_transcript_detail", new=AsyncMock(return_value=detail)
    ) as mock_fn:
        # 頁 0 → 打一次 API 存快取
        await transcript_callback(_tx_update("tx:show:202607162330:0"), context)
        # 頁 1、頁 2 → 讀快取，不再打 API
        await transcript_callback(_tx_update("tx:show:202607162330:1"), context)
        await transcript_callback(_tx_update("tx:show:202607162330:2"), context)

    assert mock_fn.call_count == 1


@pytest.mark.asyncio
async def test_transcript_show_error(context):
    """detail 回 error → 顯示錯誤訊息，不崩。"""
    from bot.handlers import _transcript_cache, transcript_callback

    _transcript_cache.clear()
    update = _tx_update("tx:show:202607162330:0")
    with patch(
        "tools.uanalyze.fetch_transcript_detail",
        new=AsyncMock(return_value={"error": "無法取得逐字稿全文"}),
    ):
        await transcript_callback(update, context)

    assert "無法取得逐字稿全文" in update.callback_query.edit_message_text.call_args[0][0]


# --- Agent reply format routing (text / HTML self-selected by Agent) ---


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
