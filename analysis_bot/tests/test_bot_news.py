from __future__ import annotations

from datetime import datetime

import pytest
from analysis_bot.bot import handlers
from analysis_bot.tests.bot_fakes import (
    FakeCallbackQuery,
    FakeContext,
    FakeMessage,
    FakeNewsParser,
    FakeUpdate,
)
from telegram import InlineKeyboardMarkup
from telegram.constants import ParseMode


def _callback_data_set(markup: InlineKeyboardMarkup) -> set[str]:
    cbs: set[str] = set()
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data:
                cbs.add(btn.callback_data)
    return cbs


def _first_button_callback(markup: InlineKeyboardMarkup) -> str:
    return markup.inline_keyboard[0][0].callback_data  # type: ignore[return-value]


class _FixedDateTime:
    @classmethod
    def now(cls) -> datetime:
        return datetime(2026, 1, 11, 12, 0, 0)


@pytest.mark.asyncio
async def test_news_command_builds_inline_keyboard_menu() -> None:
    msg = FakeMessage()
    update = FakeUpdate(message=msg)
    context = FakeContext(bot_data={"news_parser": FakeNewsParser()})

    await handlers.news_command(update, context)

    assert len(msg.reply_text_calls) == 1
    call = msg.reply_text_calls[0]
    assert call.text == "請選擇新聞來源："
    assert isinstance(call.kwargs.get("reply_markup"), InlineKeyboardMarkup)

    markup = call.kwargs["reply_markup"]
    cbs = _callback_data_set(markup)

    # High-signal sanity checks: make sure main categories exist.
    required = {
        "news_cnyes",
        "news_google",
        "news_moneydj",
        "news_yahoo",
        "news_udn",
        "news_uanalyze",
        "news_macromicro",
        "news_finguider",
        "news_fintastic",
        "news_forecastock",
        "news_vocus_menu",
        "news_ndai",
        "news_fugle",
        "news_sinotrade_industry",
        "news_pocket_report",
    }
    assert required.issubset(cbs)


@pytest.mark.asyncio
async def test_news_button_handler_main_menu_renders_menu() -> None:
    query = FakeCallbackQuery("news_main_menu")
    update = FakeUpdate(callback_query=query)
    context = FakeContext(bot_data={"news_parser": FakeNewsParser()})

    await handlers.news_button_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1
    edit = query.edit_message_text_calls[0]
    assert edit.text == "請選擇新聞來源："
    assert isinstance(edit.kwargs.get("reply_markup"), InlineKeyboardMarkup)
    assert "news_vocus_menu" in _callback_data_set(edit.kwargs["reply_markup"])


@pytest.mark.asyncio
async def test_news_button_handler_vocus_menu_renders_submenu_and_back_button() -> None:
    query = FakeCallbackQuery("news_vocus_menu")
    update = FakeUpdate(callback_query=query)
    context = FakeContext(bot_data={"news_parser": FakeNewsParser()})

    await handlers.news_button_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1
    edit = query.edit_message_text_calls[0]
    assert edit.text == "與 Vocus 相關的追蹤者："
    assert isinstance(edit.kwargs.get("reply_markup"), InlineKeyboardMarkup)
    cbs = _callback_data_set(edit.kwargs["reply_markup"])
    assert "news_main_menu" in cbs  # back to main menu


@pytest.mark.parametrize(
    "callback_data,seed_key,expected_back",
    [
        (
            "news_cnyes",
            "https://api.cnyes.com/media/api/v1/newslist/category/headline",
            "news_main_menu",
        ),
        (
            "news_google",
            "https://news.google.com/rss?hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
            "news_main_menu",
        ),
        ("news_moneydj", "moneydj", "news_main_menu"),
        ("news_yahoo", "yahoo_tw", "news_main_menu"),
        ("news_udn", "udn", "news_main_menu"),
        ("news_uanalyze", "uanalyze", "news_main_menu"),
        ("news_macromicro", "macromicro", "news_main_menu"),
        ("news_finguider", "finguider", "news_main_menu"),
        ("news_fintastic", "fintastic", "news_main_menu"),
        ("news_forecastock", "forecastock", "news_main_menu"),
        ("news_ndai", "ndai", "news_main_menu"),
        ("news_fugle", "fugle", "news_main_menu"),
        ("news_sinotrade_industry", "sinotrade_industry", "news_main_menu"),
        ("news_pocket_report", "pocket_report", "news_main_menu"),
        ("news_vocus_all", "vocus_all", "news_vocus_menu"),
    ],
)
@pytest.mark.asyncio
async def test_news_button_handler_fetches_and_renders_news(
    monkeypatch: pytest.MonkeyPatch,
    callback_data: str,
    seed_key: str,
    expected_back: str,
) -> None:
    monkeypatch.setattr(handlers, "datetime", _FixedDateTime)

    # Seed one item with brackets to validate markdown safety conversion [] -> ()
    item = {"title": "Hello [World]", "url": "https://example.com/x"}

    results_by_key = {}
    if callback_data == "news_vocus_all":
        # handlers loops through 3 Vocus users; we seed all to ensure list is non-empty.
        results_by_key = {
            "vocus:@ieobserve": [item],
            "vocus:@miula": [item],
            "vocus:65ab564cfd897800018a88cc": [item],
        }
    elif seed_key in (
        "moneydj",
        "yahoo_tw",
        "udn",
        "uanalyze",
        "macromicro",
        "finguider",
        "fintastic",
        "forecastock",
        "ndai",
        "fugle",
        "sinotrade_industry",
        "pocket_report",
    ):
        results_by_key = {seed_key: [item]}
    else:
        # fetch_news_list uses URL as key in FakeNewsParser
        results_by_key = {seed_key: [item]}

    parser = FakeNewsParser(results_by_key=results_by_key)
    query = FakeCallbackQuery(callback_data)
    update = FakeUpdate(callback_query=query)
    context = FakeContext(bot_data={"news_parser": parser})

    await handlers.news_button_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1

    edit = query.edit_message_text_calls[0]
    assert "(2026-01-11)" in edit.text
    assert "[Hello (World)](https://example.com/x)" in edit.text
    assert edit.kwargs.get("parse_mode") == ParseMode.MARKDOWN
    assert edit.kwargs.get("disable_web_page_preview") is True

    markup = edit.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    assert _first_button_callback(markup) == expected_back


@pytest.mark.asyncio
async def test_news_button_handler_empty_results_shows_back_to_main_menu() -> None:
    parser = FakeNewsParser(results_by_key={})
    query = FakeCallbackQuery("news_cnyes")
    update = FakeUpdate(callback_query=query)
    context = FakeContext(bot_data={"news_parser": parser})

    await handlers.news_button_handler(update, context)

    assert query.answer_calls == 1
    assert len(query.edit_message_text_calls) == 1
    edit = query.edit_message_text_calls[0]
    assert edit.text == "No news found or source not implemented yet."
    markup = edit.kwargs.get("reply_markup")
    assert isinstance(markup, InlineKeyboardMarkup)
    assert _first_button_callback(markup) == "news_main_menu"
