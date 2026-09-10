"""Tests for the Telegram-native Codex model picker."""

from ccbot.codex_remote import CodexModel
from ccbot.handlers.codex_model_picker import (
    build_effort_picker,
    build_model_picker,
    parse_model_args,
)

MODELS = [
    CodexModel(
        "gpt-6-astra", "GPT-6-Astra", "best", True, ["low", "medium", "high"], "medium"
    ),
    CodexModel("gpt-5.5", "GPT-5.5", "older", False, [], ""),
]


def test_model_picker_buttons_and_callback_data():
    text, kb = build_model_picker(MODELS, current="gpt-5.5")
    rows = kb.inline_keyboard
    assert [b.callback_data for r in rows for b in r] == [
        "cm:sel:gpt-6-astra",
        "cm:sel:gpt-5.5",
        "cm:cancel",
    ]
    assert rows[1][0].text.startswith("● ")  # current model marked
    assert "(default)" in text and "next message" in text
    assert all(len(b.callback_data.encode()) <= 64 for r in rows for b in r)


def test_effort_picker_marks_default_and_wraps_rows():
    _, kb = build_effort_picker(MODELS[0])
    rows = kb.inline_keyboard
    assert [b.text for b in rows[0]] == ["low", "● medium", "high"]
    assert rows[-1][0].callback_data == "cm:cancel"


def test_parse_model_args():
    assert parse_model_args("", MODELS) == ("", "", "")
    assert parse_model_args("GPT-5.5", MODELS) == ("gpt-5.5", "", "")
    assert parse_model_args("gpt-6-astra HIGH", MODELS) == ("gpt-6-astra", "high", "")
    assert "Unknown model" in parse_model_args("gpt-9", MODELS)[2]
    assert "Unknown effort" in parse_model_args("gpt-6-astra ultra", MODELS)[2]
    # A model without an advertised effort list accepts any effort.
    assert parse_model_args("gpt-5.5 low", MODELS) == ("gpt-5.5", "low", "")
