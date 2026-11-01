"""Tests for SessionManager pure dict operations."""

import json
from unittest.mock import AsyncMock

import pytest

import ccbot.session as session_mod
from ccbot import session as session_module
from ccbot.codex_remote import make_codex_window_id
from ccbot.config import AGENT_CLAUDE, AGENT_CODEX
from ccbot.session import SessionManager, WindowState
from ccbot.tmux_manager import TmuxWindow


@pytest.fixture
def mgr(monkeypatch) -> SessionManager:
    monkeypatch.setattr(SessionManager, "_load_state", lambda self: None)
    monkeypatch.setattr(SessionManager, "_save_state", lambda self: None)
    return SessionManager()


class TestThreadBindings:
    def test_bind_and_get(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1")
        assert mgr.get_window_for_thread(100, 1) == "@1"

    def test_bind_unbind_get_returns_none(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1")
        mgr.unbind_thread(100, 1)
        assert mgr.get_window_for_thread(100, 1) is None

    def test_unbind_nonexistent_returns_none(self, mgr: SessionManager) -> None:
        assert mgr.unbind_thread(100, 999) is None

    def test_iter_thread_bindings(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1")
        mgr.bind_thread(100, 2, "@2")
        mgr.bind_thread(200, 3, "@3")
        result = set(mgr.iter_thread_bindings())
        assert result == {(100, 1, "@1"), (100, 2, "@2"), (200, 3, "@3")}


class TestGroupChatId:
    """Tests for group chat_id routing (supergroup forum topic support).

    IMPORTANT: These tests protect against regression. The group_chat_ids
    mapping is required for Telegram supergroup forum topics — without it,
    all outbound messages fail with "Message thread not found". This was
    erroneously removed once (26cb81f) and restored in PR #23. Do NOT
    delete these tests or the underlying functionality.
    """

    def test_resolve_with_stored_group_id(self, mgr: SessionManager) -> None:
        """resolve_chat_id returns stored group chat_id for known thread."""
        mgr.set_group_chat_id(100, 1, -1001234567890)
        assert mgr.resolve_chat_id(100, 1) == -1001234567890

    def test_resolve_without_group_id_falls_back_to_user_id(
        self, mgr: SessionManager
    ) -> None:
        """resolve_chat_id falls back to user_id when no group_id stored."""
        assert mgr.resolve_chat_id(100, 1) == 100

    def test_resolve_none_thread_id_falls_back_to_user_id(
        self, mgr: SessionManager
    ) -> None:
        """resolve_chat_id returns user_id when thread_id is None (private chat)."""
        mgr.set_group_chat_id(100, 1, -1001234567890)
        assert mgr.resolve_chat_id(100) == 100

    def test_set_group_chat_id_overwrites(self, mgr: SessionManager) -> None:
        """set_group_chat_id updates the stored value on change."""
        mgr.set_group_chat_id(100, 1, -999)
        mgr.set_group_chat_id(100, 1, -888)
        assert mgr.resolve_chat_id(100, 1) == -888

    def test_multiple_threads_independent(self, mgr: SessionManager) -> None:
        """Different threads for the same user store independent group chat_ids."""
        mgr.set_group_chat_id(100, 1, -111)
        mgr.set_group_chat_id(100, 2, -222)
        assert mgr.resolve_chat_id(100, 1) == -111
        assert mgr.resolve_chat_id(100, 2) == -222

    def test_multiple_users_independent(self, mgr: SessionManager) -> None:
        """Different users store independent group chat_ids."""
        mgr.set_group_chat_id(100, 1, -111)
        mgr.set_group_chat_id(200, 1, -222)
        assert mgr.resolve_chat_id(100, 1) == -111
        assert mgr.resolve_chat_id(200, 1) == -222

    def test_set_group_chat_id_with_none_thread(self, mgr: SessionManager) -> None:
        """set_group_chat_id handles None thread_id (mapped to 0)."""
        mgr.set_group_chat_id(100, None, -999)
        # thread_id=None in resolve falls back to user_id (by design)
        assert mgr.resolve_chat_id(100, None) == 100
        # The stored key is "100:0", only accessible with explicit thread_id=0
        assert mgr.group_chat_ids.get("100:0") == -999


class TestWindowState:
    def test_get_creates_new(self, mgr: SessionManager) -> None:
        state = mgr.get_window_state("@0")
        assert state.session_id == ""
        assert state.cwd == ""
        assert mgr.window_agent("@0") == AGENT_CLAUDE

    def test_get_returns_existing(self, mgr: SessionManager) -> None:
        state = mgr.get_window_state("@1")
        state.session_id = "abc"
        assert mgr.get_window_state("@1").session_id == "abc"

    def test_clear_window_session(self, mgr: SessionManager) -> None:
        state = mgr.get_window_state("@1")
        state.session_id = "abc"
        mgr.clear_window_session("@1")
        assert mgr.get_window_state("@1").session_id == ""

    def test_window_state_serializes_agent(self) -> None:
        state = WindowState(
            agent=AGENT_CODEX,
            session_id="sid",
            cwd="/tmp/project",
            window_name="project",
        )
        restored = WindowState.from_dict(state.to_dict(), window_id="@1")
        assert restored.agent == AGENT_CODEX

    def test_missing_agent_defaults_to_claude(self, mgr: SessionManager) -> None:
        state = WindowState.from_dict(
            {"session_id": "sid", "cwd": "/tmp/project"},
            window_id="@1",
        )
        assert state.agent == ""
        mgr.window_states["@1"] = state
        assert mgr.window_agent("@1") == AGENT_CLAUDE


class TestResolveWindowForThread:
    def test_none_thread_id_returns_none(self, mgr: SessionManager) -> None:
        assert mgr.resolve_window_for_thread(100, None) is None

    def test_unbound_thread_returns_none(self, mgr: SessionManager) -> None:
        assert mgr.resolve_window_for_thread(100, 42) is None

    def test_bound_thread_returns_window(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 42, "@3")
        assert mgr.resolve_window_for_thread(100, 42) == "@3"


class TestDisplayNames:
    def test_get_display_name_fallback(self, mgr: SessionManager) -> None:
        """get_display_name returns window_id when no display name is set."""
        assert mgr.get_display_name("@99") == "@99"

    def test_set_and_get_display_name(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1", window_name="myproject")
        assert mgr.get_display_name("@1") == "myproject"

    def test_set_display_name_update(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1", window_name="old-name")
        mgr.window_display_names["@1"] = "new-name"
        assert mgr.get_display_name("@1") == "new-name"

    def test_bind_thread_sets_display_name(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1", window_name="proj")
        assert mgr.get_display_name("@1") == "proj"

    def test_bind_thread_without_name_no_display(self, mgr: SessionManager) -> None:
        mgr.bind_thread(100, 1, "@1")
        # No display name set, fallback to window_id
        assert mgr.get_display_name("@1") == "@1"

    def test_bind_codex_thread_sets_state_and_display(
        self, mgr: SessionManager
    ) -> None:
        window_id = mgr.bind_codex_thread(
            100,
            1,
            "019e459d-c98d-7223-85b5-de7c290f859e",
            "/tmp/project",
            "project",
        )
        assert window_id == make_codex_window_id("019e459d-c98d-7223-85b5-de7c290f859e")
        assert mgr.get_window_for_thread(100, 1) == window_id
        assert mgr.get_display_name(window_id) == "project"
        assert mgr.get_window_state(window_id).cwd == "/tmp/project"
        assert mgr.get_window_state(window_id).agent == AGENT_CODEX


class TestWindowRebinding:
    def test_rebind_window_id_moves_all_persisted_state(
        self, mgr: SessionManager
    ) -> None:
        mgr.window_states["@1"] = WindowState(
            session_id="sid",
            cwd="/tmp/project",
            window_name="old",
        )
        mgr.window_display_names["@1"] = "old"
        mgr.thread_bindings[100] = {1: "@1", 2: "@2"}
        mgr.user_window_offsets[100] = {"@1": 25, "@2": 5}

        mgr.rebind_window_id("@1", "@9", "new")

        assert "@1" not in mgr.window_states
        assert mgr.window_states["@9"].session_id == "sid"
        assert mgr.window_states["@9"].cwd == "/tmp/project"
        assert mgr.window_states["@9"].window_name == "new"
        assert mgr.thread_bindings[100] == {1: "@9", 2: "@2"}
        assert mgr.user_window_offsets[100] == {"@9": 25, "@2": 5}
        assert mgr.window_display_names["@9"] == "new"

    async def test_resolve_stale_ids_preserves_missing_codex_remote_window(
        self, monkeypatch, mgr: SessionManager, tmp_path
    ) -> None:
        monkeypatch.setattr(
            session_module.tmux_manager,
            "list_windows",
            AsyncMock(return_value=[]),
        )
        monkeypatch.setattr(
            mgr,
            "_cleanup_stale_session_map_entries",
            AsyncMock(),
        )
        # Nonexistent session_map so the old-format migration step is a no-op
        monkeypatch.setattr(
            session_module.config, "session_map_file", tmp_path / "no_map.json"
        )
        mgr.window_states["@1"] = WindowState(
            agent=AGENT_CODEX,
            session_id="019e459d-c98d-7223-85b5-de7c290f859e",
            cwd="/tmp/project",
            window_name="project",
        )
        mgr.window_display_names["@1"] = "project"
        mgr.thread_bindings[100] = {1: "@1"}
        mgr.user_window_offsets[100] = {"@1": 25}

        await mgr.resolve_stale_ids()

        assert mgr.window_states["@1"].session_id == (
            "019e459d-c98d-7223-85b5-de7c290f859e"
        )
        assert mgr.thread_bindings[100] == {1: "@1"}
        assert mgr.user_window_offsets[100] == {"@1": 25}


class TestIsWindowId:
    def test_valid_ids(self, mgr: SessionManager) -> None:
        assert mgr._is_window_id("@0") is True
        assert mgr._is_window_id("@12") is True
        assert mgr._is_window_id("@999") is True

    def test_invalid_ids(self, mgr: SessionManager) -> None:
        assert mgr._is_window_id("myproject") is False
        assert mgr._is_window_id("@") is False
        assert mgr._is_window_id("") is False
        assert mgr._is_window_id("@abc") is False


class TestCodexHybridInput:
    """Codex windows type into the tmux TUI when it exists, else use app-server."""

    @pytest.fixture(autouse=True)
    def _subscription(self, monkeypatch):
        from ccbot import codex_remote

        self.ensure_subscribed = AsyncMock(return_value=False)
        monkeypatch.setattr(
            codex_remote.codex_remote_manager,
            "ensure_subscribed",
            self.ensure_subscribed,
        )

    def _codex_window(self, mgr: SessionManager, window_id: str = "@7") -> None:
        mgr.window_states[window_id] = WindowState(
            agent=AGENT_CODEX,
            session_id="019e459d-c98d-7223-85b5-de7c290f859e",
            cwd="/tmp/project",
            window_name="project",
        )

    async def test_prefers_tmux_when_window_exists(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = "node"
        find = AsyncMock(return_value=window)
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(session_module.tmux_manager, "find_window_by_id", find)
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, _ = await mgr.send_to_window("@7", "/model")

        assert ok
        send_keys.assert_awaited_once_with("@7", "/model")
        send_to_thread.assert_not_awaited()

    async def test_falls_back_to_app_server_when_window_missing(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, msg = await mgr.send_to_window("@7", "hello")

        assert (ok, msg) == (True, "api")
        send_keys.assert_not_awaited()
        send_to_thread.assert_awaited_once_with(
            "019e459d-c98d-7223-85b5-de7c290f859e", "hello"
        )

    async def test_falls_back_to_app_server_when_tmux_send_fails(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = "codex"
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=window),
        )
        monkeypatch.setattr(
            session_module.tmux_manager, "send_keys", AsyncMock(return_value=False)
        )
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, _ = await mgr.send_to_window("@7", "hello")

        assert ok
        send_to_thread.assert_awaited_once()

    async def test_legacy_pseudo_window_uses_app_server_directly(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        window_id = mgr.bind_codex_thread(
            100, 1, "019e459d-c98d-7223-85b5-de7c290f859e", "/tmp/project", "project"
        )
        find = AsyncMock(return_value=None)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(session_module.tmux_manager, "find_window_by_id", find)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, _ = await mgr.send_to_window(window_id, "hello")

        assert ok
        find.assert_not_awaited()
        send_to_thread.assert_awaited_once_with(
            "019e459d-c98d-7223-85b5-de7c290f859e", "hello"
        )

    @pytest.mark.parametrize("shell", ["zsh", "bash", "/bin/sh", ""])
    async def test_never_types_into_a_bare_shell(
        self, monkeypatch, mgr: SessionManager, shell: str
    ) -> None:
        """If the TUI exited, text must go to app-server, never to the shell."""
        self._codex_window(mgr)
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = shell
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=window),
        )
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, msg = await mgr.send_to_window("@7", "rm -rf /")

        assert (ok, msg) == (True, "api")
        send_keys.assert_not_awaited()
        send_to_thread.assert_awaited_once()

    async def test_pending_model_override_goes_via_app_server_then_clears(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        mgr.set_codex_model_override("@7", "gpt-5.5", "low")
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = "node"
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=window),
        )
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, _ = await mgr.send_to_window("@7", "hello")
        assert ok
        send_keys.assert_not_awaited()
        send_to_thread.assert_awaited_once_with(
            "019e459d-c98d-7223-85b5-de7c290f859e",
            "hello",
            model="gpt-5.5",
            effort="low",
        )
        # Override is consumed; the next message goes back to the TUI.
        assert mgr.get_window_state("@7").pending_model == ""
        assert mgr.get_window_state("@7").pending_effort == ""
        await mgr.send_to_window("@7", "again")
        send_keys.assert_awaited_once_with("@7", "again")

    def test_pending_override_round_trips_through_state(self) -> None:
        ws = WindowState(
            agent=AGENT_CODEX, session_id="t", pending_model="m", pending_effort="e"
        )
        assert WindowState.from_dict(ws.to_dict()) == ws
        plain = WindowState(agent=AGENT_CODEX, session_id="t")
        assert "pending_model" not in plain.to_dict()

    async def test_subscribes_before_typing_into_tui(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        order: list[str] = []
        self.ensure_subscribed.side_effect = lambda *a, **k: order.append("sub")
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = "node"

        async def send_keys(*_a, **_k):
            order.append("keys")
            return True

        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=window),
        )
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)

        ok, _ = await mgr.send_to_window("@7", "hello")

        assert ok
        assert order == ["sub", "keys"]
        self.ensure_subscribed.assert_awaited_once_with(
            "019e459d-c98d-7223-85b5-de7c290f859e", "/tmp/project"
        )

    async def test_subscription_failure_reports_and_sends_nothing(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        self._codex_window(mgr)
        self.ensure_subscribed.side_effect = RuntimeError("boom")
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        from ccbot import codex_remote

        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, msg = await mgr.send_to_window("@7", "hello")

        assert not ok
        assert "subscribe" in msg and "boom" in msg
        send_keys.assert_not_awaited()
        send_to_thread.assert_not_awaited()

    async def test_app_server_restart_during_send_uses_app_server(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        """TUIs are relaunching on the new server; don't type into them."""
        self._codex_window(mgr)
        from ccbot import codex_remote

        client = codex_remote.codex_remote_manager.client
        monkeypatch.setattr(client, "generation", 3)

        def restart(*_a, **_k):
            client.generation = 4

        self.ensure_subscribed.side_effect = restart
        window = AsyncMock()
        window.window_id = "@7"
        window.pane_current_command = "node"
        send_keys = AsyncMock(return_value=True)
        send_to_thread = AsyncMock(return_value=(True, "api"))
        monkeypatch.setattr(
            session_module.tmux_manager,
            "find_window_by_id",
            AsyncMock(return_value=window),
        )
        monkeypatch.setattr(session_module.tmux_manager, "send_keys", send_keys)
        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "send_to_thread", send_to_thread
        )

        ok, msg = await mgr.send_to_window("@7", "hello")

        assert (ok, msg) == (True, "api")
        send_keys.assert_not_awaited()


class TestMigrateOldFormatMap:
    """Pure-function tests for _migrate_old_format_map (session:name -> session:@id)."""

    def test_migrates_name_to_window_id(self, mgr: SessionManager) -> None:
        session_map = {
            "ccbot:ccmux": {"session_id": "sid-1", "cwd": "/proj"},
        }
        changed = mgr._migrate_old_format_map(session_map, {"ccmux": "@4"})
        assert changed is True
        assert "ccbot:ccmux" not in session_map
        assert session_map["ccbot:@4"] == {
            "session_id": "sid-1",
            "cwd": "/proj",
            "window_name": "ccmux",  # backfilled
        }

    def test_drops_orphan_without_live_window(self, mgr: SessionManager) -> None:
        session_map = {"ccbot:gone": {"session_id": "sid-2", "cwd": "/x"}}
        changed = mgr._migrate_old_format_map(session_map, {})
        assert changed is True
        assert session_map == {}

    def test_prefers_existing_window_id_key(self, mgr: SessionManager) -> None:
        session_map = {
            "ccbot:ccmux": {"session_id": "old-sid", "cwd": "/proj"},
            "ccbot:@4": {"session_id": "new-sid", "cwd": "/proj"},
        }
        changed = mgr._migrate_old_format_map(session_map, {"ccmux": "@4"})
        assert changed is True
        # @id entry wins; old-format key discarded
        assert session_map == {"ccbot:@4": {"session_id": "new-sid", "cwd": "/proj"}}

    def test_noop_for_window_id_keys(self, mgr: SessionManager) -> None:
        session_map = {"ccbot:@4": {"session_id": "sid", "cwd": "/proj"}}
        changed = mgr._migrate_old_format_map(session_map, {"ccmux": "@4"})
        assert changed is False
        assert session_map == {"ccbot:@4": {"session_id": "sid", "cwd": "/proj"}}

    def test_ignores_other_tmux_sessions(self, mgr: SessionManager) -> None:
        # Keys for other tmux sessions (different prefix) are left untouched.
        session_map = {"0:2.1.76": {"session_id": "sid", "cwd": "/other"}}
        changed = mgr._migrate_old_format_map(session_map, {"2.1.76": "@9"})
        assert changed is False
        assert session_map == {"0:2.1.76": {"session_id": "sid", "cwd": "/other"}}


class TestResolveStaleIds:
    """Regression tests for startup re-resolution after tmux server restart.

    IMPORTANT: window IDs reset when the tmux server restarts; thread
    bindings MUST survive by re-resolving through display names. A previous
    bug popped window_display_names entries while migrating window_states,
    so the thread_bindings loop could no longer resolve the same stale ID
    and silently dropped every topic binding.
    """

    def _setup(self, mgr: SessionManager, monkeypatch, tmp_path, live) -> None:
        async def fake_list_windows() -> list[TmuxWindow]:
            return live

        monkeypatch.setattr(session_mod.tmux_manager, "list_windows", fake_list_windows)
        # Point session_map at a nonexistent file so the trailing
        # session_map cleanup steps are no-ops
        monkeypatch.setattr(
            session_mod.config, "session_map_file", tmp_path / "no_map.json"
        )

    @pytest.mark.asyncio
    async def test_tmux_restart_remaps_bindings_and_offsets(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        """All state keyed by a stale window_id follows it to the new id."""
        state = mgr.get_window_state("@5")
        state.session_id = "sid-1"
        state.cwd = "/proj"
        state.window_name = "proj"
        mgr.window_display_names["@5"] = "proj"
        mgr.bind_thread(100, 42, "@5", window_name="proj")
        mgr.user_window_offsets = {100: {"@5": 123}}

        # tmux restarted: same window name, new id
        self._setup(mgr, monkeypatch, tmp_path, [TmuxWindow("@1", "proj", "/proj")])
        await mgr.resolve_stale_ids()

        assert mgr.get_window_for_thread(100, 42) == "@1"
        assert mgr.window_states["@1"].session_id == "sid-1"
        assert "@5" not in mgr.window_states
        assert mgr.user_window_offsets[100] == {"@1": 123}
        assert mgr.get_display_name("@1") == "proj"

    @pytest.mark.asyncio
    async def test_binding_without_window_state_still_remaps(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        """Bindings resolve via display names even with no window_state entry."""
        mgr.window_display_names["@7"] = "other"
        mgr.bind_thread(100, 9, "@7", window_name="other")

        self._setup(mgr, monkeypatch, tmp_path, [TmuxWindow("@2", "other", "/o")])
        await mgr.resolve_stale_ids()

        assert mgr.get_window_for_thread(100, 9) == "@2"

    @pytest.mark.asyncio
    async def test_unmatched_binding_dropped(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        """A stale binding with no live window of the same name is dropped."""
        mgr.window_display_names["@5"] = "gone"
        mgr.bind_thread(100, 42, "@5", window_name="gone")

        self._setup(mgr, monkeypatch, tmp_path, [TmuxWindow("@1", "unrelated", "/u")])
        await mgr.resolve_stale_ids()

        assert mgr.get_window_for_thread(100, 42) is None

    @pytest.mark.asyncio
    async def test_live_ids_untouched(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        """Bindings pointing at still-live window IDs are kept as-is."""
        mgr.window_display_names["@3"] = "keep"
        mgr.bind_thread(100, 7, "@3", window_name="keep")
        state = mgr.get_window_state("@3")
        state.session_id = "sid-keep"

        self._setup(mgr, monkeypatch, tmp_path, [TmuxWindow("@3", "keep", "/k")])
        await mgr.resolve_stale_ids()

        assert mgr.get_window_for_thread(100, 7) == "@3"
        assert mgr.window_states["@3"].session_id == "sid-keep"


class TestLoadSessionMapMigration:
    """load_session_map self-heals old-format keys at runtime and fills window_states."""

    def _mock_windows(self, monkeypatch, windows: list[TmuxWindow]) -> None:
        async def fake_list_windows() -> list[TmuxWindow]:
            return windows

        monkeypatch.setattr(session_mod.tmux_manager, "list_windows", fake_list_windows)

    @pytest.mark.asyncio
    async def test_old_format_key_populates_window_state(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        map_file = tmp_path / "session_map.json"
        map_file.write_text(
            json.dumps({"ccbot:ccmux": {"session_id": "sid-1", "cwd": "/proj"}})
        )
        monkeypatch.setattr(session_mod.config, "session_map_file", map_file)
        self._mock_windows(monkeypatch, [TmuxWindow("@4", "ccmux", "/proj")])

        await mgr.load_session_map()

        # Delivery path can now resolve @4 -> sid-1
        state = mgr.get_window_state("@4")
        assert state.session_id == "sid-1"
        assert state.cwd == "/proj"
        # File was rewritten to the @window_id form
        rewritten = json.loads(map_file.read_text())
        assert "ccbot:ccmux" not in rewritten
        assert rewritten["ccbot:@4"]["session_id"] == "sid-1"

    @pytest.mark.asyncio
    async def test_no_tmux_lookup_when_no_old_keys(
        self, mgr: SessionManager, monkeypatch, tmp_path
    ) -> None:
        map_file = tmp_path / "session_map.json"
        map_file.write_text(
            json.dumps({"ccbot:@4": {"session_id": "sid-1", "cwd": "/proj"}})
        )
        monkeypatch.setattr(session_mod.config, "session_map_file", map_file)

        async def boom() -> list[TmuxWindow]:
            raise AssertionError("list_windows should not be called without old keys")

        monkeypatch.setattr(session_mod.tmux_manager, "list_windows", boom)

        await mgr.load_session_map()
        assert mgr.get_window_state("@4").session_id == "sid-1"


class TestApplyCodexModel:
    """/model applies via thread/settings/update now, else waits for next message."""

    THREAD = "019e459d-c98d-7223-85b5-de7c290f859e"

    def _codex_window(self, mgr: SessionManager) -> None:
        mgr.window_states["@7"] = WindowState(
            agent=AGENT_CODEX, session_id=self.THREAD, cwd="/tmp/project"
        )

    async def test_applies_immediately(self, monkeypatch, mgr: SessionManager) -> None:
        from ccbot import codex_remote

        self._codex_window(mgr)
        mgr.set_codex_model_override("@7", "stale", "low")
        update = AsyncMock()
        monkeypatch.setattr(
            codex_remote.codex_remote_manager, "update_thread_settings", update
        )

        applied = await mgr.apply_codex_model("@7", "gpt-6-luna", "high")

        assert applied is True
        update.assert_awaited_once_with(
            self.THREAD, "/tmp/project", model="gpt-6-luna", effort="high"
        )
        # Nothing left to replay on the next message
        assert mgr.get_window_state("@7").pending_model == ""
        assert mgr.get_window_state("@7").pending_effort == ""

    async def test_falls_back_to_pending_on_failure(
        self, monkeypatch, mgr: SessionManager
    ) -> None:
        from ccbot import codex_remote

        self._codex_window(mgr)
        monkeypatch.setattr(
            codex_remote.codex_remote_manager,
            "update_thread_settings",
            AsyncMock(side_effect=RuntimeError("method not found")),
        )

        applied = await mgr.apply_codex_model("@7", "gpt-6-luna", "high")

        assert applied is False
        state = mgr.get_window_state("@7")
        assert (state.pending_model, state.pending_effort) == ("gpt-6-luna", "high")

    async def test_update_request_omits_empty_effort(self, monkeypatch) -> None:
        from ccbot import codex_remote

        mgr_ = codex_remote.codex_remote_manager
        monkeypatch.setattr(mgr_, "ensure_subscribed", AsyncMock(return_value=False))
        request = AsyncMock(return_value={})
        monkeypatch.setattr(mgr_.client, "request", request)

        await mgr_.update_thread_settings(self.THREAD, "", model="m", effort=None)

        request.assert_awaited_once_with(
            "thread/settings/update",
            {"threadId": self.THREAD, "model": "m"},
            timeout=30.0,
        )
