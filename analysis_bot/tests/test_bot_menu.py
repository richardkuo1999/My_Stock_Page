from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeCallbackQuery, FakeContext, FakeMessage, FakeUpdate
from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode


def _callback_data_set(markup: InlineKeyboardMarkup) -> set[str]:
    return {btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data}


@pytest.mark.asyncio
async def test_menu_command_shows_categories() -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext()

    await handlers.menu_command(update, context)

    assert len(msg.reply_text_calls) == 1
    call = msg.reply_text_calls[0]
    assert "選擇分類" in call.text
    assert call.kwargs.get("parse_mode") == ParseMode.MARKDOWN
    markup = call.kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    cbs = _callback_data_set(markup)
    # All 9 categories should be present
    for _, cb_data in handlers._MENU_CATEGORIES:
        assert cb_data in cbs


@pytest.mark.asyncio
async def test_menu_callback_opens_category_page() -> None:
    query = FakeCallbackQuery("menu_cat_query")
    update = FakeUpdate(callback_query=query)
    context = FakeContext()

    await handlers.menu_callback_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1
    edit = query.edit_message_text_calls[0]
    assert "資訊查詢" in edit.text
    markup = edit.kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    # Should have a back button
    cbs = _callback_data_set(markup)
    assert "menu_back" in cbs


@pytest.mark.asyncio
async def test_menu_callback_back_returns_to_main() -> None:
    query = FakeCallbackQuery("menu_back")
    update = FakeUpdate(callback_query=query)
    context = FakeContext()

    await handlers.menu_callback_handler(update, context)

    assert query.answer_calls == 1
    edit = query.edit_message_text_calls[0]
    assert "選擇分類" in edit.text
    markup = edit.kwargs["reply_markup"]
    cbs = _callback_data_set(markup)
    for _, cb_data in handlers._MENU_CATEGORIES:
        assert cb_data in cbs


@pytest.mark.asyncio
async def test_menu_exec_hint_for_slash_commands() -> None:
    """menu_exec! with /cmd format should reply with usage hint."""
    query = FakeCallbackQuery("menu_exec!/p ")
    msg = FakeMessage()
    query.message = msg
    update = FakeUpdate(callback_query=query)
    context = FakeContext()

    await handlers.menu_callback_handler(update, context)

    assert query.answer_calls == 1
    assert len(msg.reply_text_calls) == 1
    assert "請輸入" in msg.reply_text_calls[0].text


@pytest.mark.asyncio
async def test_menu_exec_direct_command() -> None:
    """menu_exec!chatid should execute chatid_command."""
    query = FakeCallbackQuery("menu_exec!chatid")
    msg = FakeMessage()
    query.message = msg
    update = FakeUpdate(callback_query=query, chat_id=999)
    context = FakeContext()

    await handlers.menu_callback_handler(update, context)

    assert query.answer_calls == 1
    assert any("999" in c.text for c in msg.reply_text_calls)


@pytest.mark.asyncio
async def test_all_category_pages_have_back_button() -> None:
    """Every category page should include a 🔙 返回選單 button."""
    for _, cb_data in handlers._MENU_CATEGORIES:
        query = FakeCallbackQuery(cb_data)
        update = FakeUpdate(callback_query=query)
        context = FakeContext()

        await handlers.menu_callback_handler(update, context)

        assert query.answer_calls == 1
        edit = query.edit_message_text_calls[0]
        markup = edit.kwargs["reply_markup"]
        cbs = _callback_data_set(markup)
        assert "menu_back" in cbs, f"Category {cb_data} missing back button"
