"""Tests for main.py application wiring (error handler registration)."""

from unittest.mock import MagicMock, patch

import pytest


@patch("main.setup_scheduler")
@patch("main.Application")
def test_error_handler_is_registered(mock_app_cls, mock_setup_scheduler, monkeypatch):
    """main() must register an application-level error handler so unhandled
    exceptions in handlers don't produce 'No error handlers are registered'."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")

    app = MagicMock()
    mock_app_cls.builder.return_value.token.return_value.build.return_value = app
    # run_polling must not actually block / connect
    app.run_polling = MagicMock()

    import main

    main.main()

    app.add_error_handler.assert_called_once()
    # The registered handler should be a coroutine function
    handler = app.add_error_handler.call_args[0][0]
    assert callable(handler)


@pytest.mark.asyncio
async def test_error_handler_replies_and_notifies():
    """The registered error handler should reply to the user and notify admin."""
    from unittest.mock import AsyncMock

    monkey_app = MagicMock()
    captured = {}

    def capture(h):
        captured["handler"] = h

    monkey_app.add_error_handler.side_effect = capture

    with patch("main.setup_scheduler"), patch("main.Application") as mock_app_cls, patch(
        "main.JobErrorNotifier"
    ) as mock_notifier_cls, patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "fake"}):
        mock_app_cls.builder.return_value.token.return_value.build.return_value = monkey_app
        monkey_app.run_polling = MagicMock()
        notifier = mock_notifier_cls.return_value
        notifier.notify_admin = AsyncMock()

        import main

        main.main()

    handler = captured["handler"]

    # Build a fake update + context with an error
    update = MagicMock()
    update.effective_message.reply_text = AsyncMock()
    context = MagicMock()
    context.error = RuntimeError("boom")

    await handler(update, context)

    update.effective_message.reply_text.assert_awaited_once()
    notifier.notify_admin.assert_awaited_once()
