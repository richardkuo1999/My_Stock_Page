from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReplyCall:
    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class EditCall:
    text: str
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeMessage:
    def __init__(self, text: str = "", message_thread_id: int | None = None) -> None:
        self.text = text
        self.message_thread_id = message_thread_id
        self.reply_text_calls: list[ReplyCall] = []

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        self.reply_text_calls.append(ReplyCall(text=text, kwargs=kwargs))

    async def reply_chat_action(self, action: Any, **kwargs: Any) -> None:
        pass

    async def reply_document(self, **kwargs: Any) -> None:
        pass

    async def reply_photo(self, **kwargs: Any) -> None:
        pass


class FakeCallbackQuery:
    def __init__(self, data: str) -> None:
        self.data = data
        self.answer_calls: int = 0
        self.edit_message_text_calls: list[EditCall] = []
        self.message: FakeMessage = FakeMessage()

    async def answer(self, **_kwargs: Any) -> None:
        self.answer_calls += 1

    async def edit_message_text(self, text: str, **kwargs: Any) -> None:
        self.edit_message_text_calls.append(EditCall(text=text, kwargs=kwargs))


class FakeChat:
    def __init__(self, chat_id: int) -> None:
        self.id = chat_id
        self.type = "private"
        self.title: str | None = None


class FakeUser:
    def __init__(self, user_id: int, full_name: str = "") -> None:
        self.id = user_id
        self.full_name = full_name


class FakeUpdate:
    def __init__(
        self,
        *,
        message: FakeMessage | None = None,
        callback_query: FakeCallbackQuery | None = None,
        chat_id: int = 123,
        user_id: int = 456,
        user_full_name: str = "",
    ) -> None:
        self.update_id = 0
        self.message = message
        self.callback_query = callback_query
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser(user_id, full_name=user_full_name)


class FakeContext:
    def __init__(
        self,
        *,
        bot_data: dict[str, Any] | None = None,
        args: list[str] | None = None,
    ) -> None:
        self.bot_data: dict[str, Any] = bot_data or {}
        self.args: list[str] = args or []
        self.user_data: dict[str, Any] = {}


class FakeNewsParser:
    """
    Minimal async API compatible with handlers' usage in analysis_bot/bot/handlers.py.
    All methods return pre-configured results from `results_by_key`.
    """

    def __init__(self, *, results_by_key: dict[str, list[dict[str, str]]] | None = None) -> None:
        self.results_by_key = results_by_key or {}
        self.calls: list[dict[str, Any]] = []

    def _get(self, key: str) -> list[dict[str, str]]:
        return list(self.results_by_key.get(key, []))

    async def fetch_news_list(self, url: str, news_number: int = 15) -> list[dict[str, str]]:
        self.calls.append({"method": "fetch_news_list", "url": url, "news_number": news_number})
        return self._get(url)

    async def get_moneydj_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_moneydj_report"})
        return self._get("moneydj")

    async def get_yahoo_tw_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_yahoo_tw_report"})
        return self._get("yahoo_tw")

    async def get_udn_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_udn_report"})
        return self._get("udn")

    async def get_uanalyze_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_uanalyze_report"})
        return self._get("uanalyze")

    async def get_macromicro_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_macromicro_report"})
        return self._get("macromicro")

    async def get_finguider_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_finguider_report"})
        return self._get("finguider")

    async def get_fintastic_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_fintastic_report"})
        return self._get("fintastic")

    async def get_forecastock_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_forecastock_report"})
        return self._get("forecastock")

    async def get_news_digest_ai_report(self) -> list[dict[str, str]]:
        self.calls.append({"method": "get_news_digest_ai_report"})
        return self._get("ndai")

    async def get_fugle_report(self, url: str) -> list[dict[str, str]]:
        self.calls.append({"method": "get_fugle_report", "url": url})
        return self._get("fugle")

    async def get_sinotrade_industry_report(self, limit: int = 20) -> list[dict[str, str]]:
        self.calls.append({"method": "get_sinotrade_industry_report", "limit": limit})
        return self._get("sinotrade_industry")

    async def get_pocket_school_report(self, limit: int = 20) -> list[dict[str, str]]:
        self.calls.append({"method": "get_pocket_school_report", "limit": limit})
        return self._get("pocket_report")

    async def get_vocus_articles(self, v_user: str) -> list[dict[str, str]]:
        self.calls.append({"method": "get_vocus_articles", "v_user": v_user})
        return self._get(f"vocus:{v_user}")

    async def fetch_news_content(self, url: str, ai_service: Any = None) -> str:
        self.calls.append({"method": "fetch_news_content", "url": url})
        # Try to find if we have a string result for this URL
        res = self.results_by_key.get(url)
        if isinstance(res, str):
            return res
        return ""

    async def close(self) -> None:
        pass
