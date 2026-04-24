from __future__ import annotations

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import FakeCallbackQuery, FakeContext, FakeMessage, FakeUpdate
from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode


def _callback_data_set(markup: InlineKeyboardMarkup) -> set[str]:
    return {btn.callback_data for row in markup.inline_keyboard for btn in row if btn.callback_data}


@pytest.mark.asyncio
async def test_help_command_shows_categories() -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext()

    await handlers.help_command(update, context)

    assert len(msg.reply_text_calls) == 1
    call = msg.reply_text_calls[0]
    assert "選擇分類" in call.text
    assert call.kwargs.get("parse_mode") == ParseMode.MARKDOWN
    markup = call.kwargs["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    cbs = _callback_data_set(markup)
    for _, cb_data in handlers._HELP_CATEGORIES:
        assert cb_data in cbs


@pytest.mark.asyncio
async def test_help_callback_opens_category_page() -> None:
    query = FakeCallbackQuery("help_query")
    update = FakeUpdate(callback_query=query)
    context = FakeContext()

    await handlers.help_callback_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1
    edit = query.edit_message_text_calls[0]
    assert "資訊查詢" in edit.text
    assert edit.kwargs.get("parse_mode") == ParseMode.MARKDOWN
    markup = edit.kwargs["reply_markup"]
    cbs = _callback_data_set(markup)
    assert "help_back" in cbs


@pytest.mark.asyncio
async def test_help_callback_back_returns_to_categories() -> None:
    query = FakeCallbackQuery("help_back")
    update = FakeUpdate(callback_query=query)
    context = FakeContext()

    await handlers.help_callback_handler(update, context)

    assert query.answer_calls == 1
    edit = query.edit_message_text_calls[0]
    assert "選擇分類" in edit.text
    markup = edit.kwargs["reply_markup"]
    cbs = _callback_data_set(markup)
    for _, cb_data in handlers._HELP_CATEGORIES:
        assert cb_data in cbs


@pytest.mark.asyncio
async def test_all_help_pages_have_back_button() -> None:
    for _, cb_data in handlers._HELP_CATEGORIES:
        query = FakeCallbackQuery(cb_data)
        update = FakeUpdate(callback_query=query)
        context = FakeContext()

        await handlers.help_callback_handler(update, context)

        assert query.answer_calls == 1
        edit = query.edit_message_text_calls[0]
        markup = edit.kwargs["reply_markup"]
        cbs = _callback_data_set(markup)
        assert "help_back" in cbs, f"Category {cb_data} missing back button"
