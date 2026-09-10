"""Tests for forward_command_handler — command forwarding to Claude Code."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_update(text: str, user_id: int = 1, thread_id: int = 42) -> MagicMock:
    """Build a minimal mock Update with message text in a forum topic."""
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    update.message = MagicMock()
    update.message.text = text
    update.message.message_thread_id = thread_id
    update.message.chat = MagicMock()
    update.message.chat.send_action = AsyncMock()
    update.effective_chat = MagicMock()
    update.effective_chat.type = "supergroup"
    update.effective_chat.id = 100
    return update


def _make_context() -> MagicMock:
    """Build a minimal mock context."""
    context = MagicMock()
    context.bot = AsyncMock()
    context.user_data = {}
    return context


class TestForwardCommand:
    @pytest.mark.asyncio
    async def test_model_sends_command_to_tmux(self):
        """/model → send_to_window called with "/model"."""
        update = _make_update("/model")
        context = _make_context()

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.tmux_manager") as mock_tmux,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock),
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.get_display_name.return_value = "project"
            mock_tmux.find_window_by_id = AsyncMock(return_value=MagicMock())
            mock_sm.send_to_window = AsyncMock(return_value=(True, "ok"))

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.send_to_window.assert_called_once_with("@5", "/model")

    @pytest.mark.asyncio
    async def test_cost_sends_command_to_tmux(self):
        """/cost → send_to_window called with "/cost"."""
        update = _make_update("/cost")
        context = _make_context()

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.tmux_manager") as mock_tmux,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock),
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.get_display_name.return_value = "project"
            mock_tmux.find_window_by_id = AsyncMock(return_value=MagicMock())
            mock_sm.send_to_window = AsyncMock(return_value=(True, "ok"))

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.send_to_window.assert_called_once_with("@5", "/cost")

    @pytest.mark.asyncio
    async def test_clear_clears_session(self):
        """/clear → send_to_window + clear_window_session."""
        update = _make_update("/clear")
        context = _make_context()

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.tmux_manager") as mock_tmux,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock),
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.get_display_name.return_value = "project"
            mock_tmux.find_window_by_id = AsyncMock(return_value=MagicMock())
            mock_sm.send_to_window = AsyncMock(return_value=(True, "ok"))

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.send_to_window.assert_called_once_with("@5", "/clear")
            mock_sm.clear_window_session.assert_called_once_with("@5")


class TestForwardCommandCodex:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd", ["/new", "/clear", "/NEW", "/clear@mybot", "/new foo"]
    )
    async def test_thread_replacing_commands_are_rejected(self, cmd):
        """/new and /clear would desync the tracked Codex thread → reject."""
        update = _make_update(cmd)
        context = _make_context()

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot._is_codex_bound_window", return_value=True),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.send_to_window = AsyncMock(return_value=(True, "ok"))

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.send_to_window.assert_not_called()
            mock_sm.clear_window_session.assert_not_called()
            assert "new topic" in mock_reply.call_args.args[1].lower()

    @pytest.mark.asyncio
    async def test_other_commands_forward_without_tmux_precheck(self):
        """/status on a Codex topic → forwarded; missing tmux window is not fatal."""
        update = _make_update("/status")
        context = _make_context()

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot._is_codex_bound_window", return_value=True),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.tmux_manager") as mock_tmux,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock),
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.get_display_name.return_value = "project"
            mock_tmux.find_window_by_id = AsyncMock(return_value=None)
            mock_sm.send_to_window = AsyncMock(return_value=(True, "ok"))

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.send_to_window.assert_called_once_with("@5", "/status")

    @pytest.mark.asyncio
    async def test_model_direct_args_sets_override(self):
        """/model gpt-5.5 low on a Codex topic → override stored, nothing typed."""
        from ccbot.codex_remote import CodexModel

        update = _make_update("/model gpt-5.5 low")
        context = _make_context()
        models = [
            CodexModel(
                "gpt-6-astra", "GPT-6-Astra", "", True, ["low", "medium"], "medium"
            ),
            CodexModel("gpt-5.5", "GPT-5.5", "", False, ["low", "high"], "high"),
        ]

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot._is_codex_bound_window", return_value=True),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.codex_remote_manager") as mock_codex,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_sm.send_to_window = AsyncMock()
            mock_codex.list_models = AsyncMock(return_value=models)

            from ccbot.bot import forward_command_handler

            await forward_command_handler(update, context)

            mock_sm.set_codex_model_override.assert_called_once_with(
                "@5", "gpt-5.5", "low"
            )
            mock_sm.send_to_window.assert_not_called()
            assert "gpt-5.5 low" in mock_reply.call_args.args[1]

    @pytest.mark.asyncio
    async def test_model_without_args_shows_picker(self):
        """/model on a Codex topic → inline keyboard with one button per model."""
        from ccbot.codex_remote import CodexModel

        update = _make_update("/model")
        context = _make_context()
        models = [
            CodexModel("gpt-6-astra", "GPT-6-Astra", "best", True, ["low"], "low"),
            CodexModel("gpt-5.5", "GPT-5.5", "older", False, ["low"], "low"),
        ]

        with (
            patch("ccbot.bot.is_user_allowed", return_value=True),
            patch("ccbot.bot._get_thread_id", return_value=42),
            patch("ccbot.bot._is_codex_bound_window", return_value=True),
            patch("ccbot.bot.session_manager") as mock_sm,
            patch("ccbot.bot.codex_remote_manager") as mock_codex,
            patch("ccbot.bot.safe_reply", new_callable=AsyncMock) as mock_reply,
        ):
            mock_sm.resolve_window_for_thread.return_value = "@5"
            mock_codex.list_models = AsyncMock(return_value=models)

            from ccbot.bot import forward_command_handler
            from ccbot.handlers.codex_model_picker import MODEL_PICK_MODELS_KEY

            await forward_command_handler(update, context)

            keyboard = mock_reply.call_args.kwargs["reply_markup"]
            labels = [b.text for row in keyboard.inline_keyboard for b in row]
            assert labels == ["GPT-6-Astra", "GPT-5.5", "Cancel"]
            assert set(context.user_data[MODEL_PICK_MODELS_KEY]) == {
                "gpt-6-astra",
                "gpt-5.5",
            }
            mock_sm.set_codex_model_override.assert_not_called()
