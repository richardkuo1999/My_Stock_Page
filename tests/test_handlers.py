"""Tests for bot/handlers.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.handlers import (
    help_command,
    kchart_command,
    mention,
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
    bridge = AsyncMock()
    bridge.send = AsyncMock(return_value="Agent 回覆內容")
    return bridge


def _make_mention_update(text: str, bot_name: str = "test_bot"):
    """Helper to create an update with a mention entity."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    mention_str = f"@{bot_name}"
    offset = text.find(mention_str)
    entity = MagicMock()
    entity.type = "mention"
    entity.offset = offset
    entity.length = len(mention_str)
    update.message.entities = [entity]
    return update


# --- Mention + Agent routing tests ---


@pytest.mark.asyncio
async def test_mention_routes_to_bridge(context, mock_bridge):
    """Mention handler routes text to bridge and replies with response."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 分析台積電")

    await mention(update, context)

    # The handler wraps the question with the system prompt before sending.
    mock_bridge.send.assert_called_once()
    sent_prompt = mock_bridge.send.call_args[0][0]
    assert "分析台積電" in sent_prompt
    assert "台股投資輔助助理" in sent_prompt  # system prompt is prepended
    update.message.reply_text.assert_called_once_with("Agent 回覆內容")


@pytest.mark.asyncio
async def test_mention_timeout_error(context, mock_bridge):
    """Mention handler replies with timeout message on TimeoutError."""
    mock_bridge.send = AsyncMock(side_effect=TimeoutError("timed out"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 很慢的問題")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 暫時無法回應，請稍後再試")


@pytest.mark.asyncio
async def test_mention_runtime_error(context, mock_bridge):
    """Mention handler replies with error message on RuntimeError."""
    mock_bridge.send = AsyncMock(side_effect=RuntimeError("Agent error (code 1): fail"))
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot 壞掉的指令")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 發生錯誤，請稍後再試")


@pytest.mark.asyncio
async def test_mention_empty_text(context, mock_bridge):
    """Mention handler prompts user when no text follows the mention."""
    context.bot_data["agent_bridge"] = mock_bridge
    update = _make_mention_update("@test_bot")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("請在 @mention 後加上您的問題")
    mock_bridge.send.assert_not_called()


@pytest.mark.asyncio
async def test_mention_no_bridge(context):
    """Mention handler replies with setup message when bridge not configured."""
    # bot_data has no "agent_bridge" key
    update = _make_mention_update("@test_bot 問題")

    await mention(update, context)

    update.message.reply_text.assert_called_once_with("⚠️ Agent 未設定")


@pytest.mark.asyncio
async def test_mention_ignores_other_users(context):
    """Mention handler should ignore mentions of other users."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = "@other_user hello"
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345

    entity = MagicMock()
    entity.type = "mention"
    entity.offset = 0
    entity.length = 11  # len("@other_user")
    update.message.entities = [entity]

    await mention(update, context)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_mention_no_entities(context):
    """Mention handler should handle no entities gracefully."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.entities = None
    await mention(update, context)  # Should not raise


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
    with patch("tools.get_stock_price.fetch_price", new=AsyncMock(return_value=fake)):
        await price_command(update, context)
    # last reply carries the price info
    text = update.message.reply_text.call_args[0][0]
    assert "台積電" in text and "2410" in text


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
    """Menu keyboard has all five data buttons with data: callbacks."""
    from bot.handlers import _data_menu_keyboard

    kb = _data_menu_keyboard("2330").inline_keyboard
    flat = [btn for row in kb for btn in row]
    callbacks = {btn.callback_data for btn in flat}
    assert "data:2330:consensus" in callbacks
    assert "data:2330:pershare" in callbacks
    assert "data:2330:supply" in callbacks
    assert "data:2330:order" in callbacks
    assert "data:2330:dcf" in callbacks
    assert len(flat) == 5


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
