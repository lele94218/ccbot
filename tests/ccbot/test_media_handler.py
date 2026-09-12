"""Tests for media_handler — videos, video notes, animations, and files."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest


def _attachment(file_size: int = 1024, file_name: str | None = "clip.mp4"):
    obj = MagicMock()
    obj.file_size = file_size
    obj.file_unique_id = "uniq1"
    obj.file_name = file_name
    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock()
    obj.get_file = AsyncMock(return_value=tg_file)
    return obj, tg_file


def _update(kind: str, obj, caption: str | None = None) -> MagicMock:
    update = MagicMock()
    update.effective_user.id = 1
    msg = update.message
    for attr in ("video", "video_note", "animation", "document"):
        setattr(msg, attr, None)
    setattr(msg, kind, obj)
    msg.caption = caption
    msg.message_thread_id = 42
    msg.chat.type = "supergroup"
    msg.chat.id = 100
    msg.chat.send_action = AsyncMock()
    return update


@pytest.fixture
def env(tmp_path: Path):
    with (
        patch("ccbot.bot.is_user_allowed", return_value=True),
        patch("ccbot.bot._get_thread_id", return_value=42),
        patch("ccbot.bot._is_codex_bound_window", return_value=False),
        patch("ccbot.bot._MEDIA_DIR", tmp_path),
        patch("ccbot.bot.clear_status_msg_info"),
        patch("ccbot.bot.session_manager") as sm,
        patch("ccbot.bot.tmux_manager") as tmux,
        patch("ccbot.bot.safe_reply", new_callable=AsyncMock) as reply,
    ):
        sm.get_window_for_thread.return_value = "@5"
        sm.send_to_window = AsyncMock(return_value=(True, "ok"))
        tmux.find_window_by_id = AsyncMock(return_value=MagicMock())
        yield sm, reply, tmp_path


@pytest.mark.asyncio
async def test_video_is_downloaded_and_path_forwarded(env):
    sm, reply, media_dir = env
    obj, tg_file = _attachment()
    from ccbot.bot import media_handler

    await media_handler(
        _update("video", obj, caption="what happens here?"), MagicMock()
    )

    saved = tg_file.download_to_drive.call_args.args[0]
    assert Path(saved).parent == media_dir and str(saved).endswith("_uniq1_clip.mp4")
    sent = sm.send_to_window.call_args.args[1]
    assert sent.startswith("what happens here?\n\n(video attached: ")
    assert str(saved) in sent and "ffmpeg" in sent
    assert "Video sent to Claude Code" in reply.call_args.args[1]


@pytest.mark.asyncio
async def test_document_without_name_and_unsafe_name(env):
    sm, _, _ = env
    from ccbot.bot import media_handler

    obj, tg_file = _attachment(file_name="../../etc/pass wd?.pdf")
    await media_handler(_update("document", obj), MagicMock())
    name = Path(tg_file.download_to_drive.call_args.args[0]).name
    assert "/" not in name and ".." not in name and name.endswith("pass_wd_.pdf")
    assert "(file attached: " in sm.send_to_window.call_args.args[1]
    assert "ffmpeg" not in sm.send_to_window.call_args.args[1]

    obj2, tg_file2 = _attachment(file_name=None)
    await media_handler(_update("video_note", obj2), MagicMock())
    assert Path(tg_file2.download_to_drive.call_args.args[0]).name.endswith(
        "video_note.mp4"
    )


@pytest.mark.asyncio
async def test_over_20mb_is_rejected_before_download(env):
    sm, reply, _ = env
    obj, _ = _attachment(file_size=35 * 1024 * 1024)
    from ccbot.bot import media_handler

    await media_handler(_update("video", obj), MagicMock())

    obj.get_file.assert_not_called()
    sm.send_to_window.assert_not_called()
    text = reply.call_args.args[1]
    assert "35.0 MB" in text and "20.0 MB" in text


@pytest.mark.asyncio
async def test_file_is_too_big_error_from_telegram(env):
    sm, reply, _ = env
    obj, _ = _attachment(file_size=0)
    obj.get_file = AsyncMock(side_effect=BadRequest("File is too big"))
    from ccbot.bot import media_handler

    await media_handler(_update("document", obj), MagicMock())

    sm.send_to_window.assert_not_called()
    assert "too large" in reply.call_args.args[1]


@pytest.mark.asyncio
async def test_unbound_topic_replies_and_skips_download(env):
    sm, reply, _ = env
    sm.get_window_for_thread.return_value = None
    obj, _ = _attachment()
    from ccbot.bot import media_handler

    await media_handler(_update("video", obj), MagicMock())

    obj.get_file.assert_not_called()
    assert "No session bound" in reply.call_args.args[1]


@pytest.mark.asyncio
async def test_photo_handler_still_forwards_after_refactor(env, tmp_path):
    sm, reply, _ = env
    photo = MagicMock()
    photo.file_unique_id = "p1"
    tg_file = MagicMock()
    tg_file.download_to_drive = AsyncMock()
    photo.get_file = AsyncMock(return_value=tg_file)
    update = _update("video", None)
    update.message.photo = [MagicMock(), photo]
    from ccbot.bot import photo_handler

    with patch("ccbot.bot._IMAGES_DIR", tmp_path):
        await photo_handler(update, MagicMock())

    assert "(image attached: " in sm.send_to_window.call_args.args[1]
    assert "Image sent to Claude Code" in reply.call_args.args[1]
