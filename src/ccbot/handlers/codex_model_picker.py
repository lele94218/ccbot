"""Telegram-native /model picker for Codex topics.

Codex's own /model is a terminal menu that ccbot cannot render, so Codex
topics get an inline-keyboard picker instead: list models from app-server
`model/list`, then reasoning efforts for the chosen model, and remember the
choice on the window state to apply on the next turn.

Key functions: build_model_picker, build_effort_picker, parse_model_args,
format_model_choice.  State keys: MODEL_PICK_MODELS_KEY, MODEL_PICK_MODEL_KEY.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from ..codex_remote import CodexModel
from .callback_data import (
    CB_CODEX_EFFORT_SELECT,
    CB_CODEX_MODEL_CANCEL,
    CB_CODEX_MODEL_SELECT,
)

# context.user_data keys
MODEL_PICK_MODELS_KEY = "_codex_model_pick_models"  # {model_id: CodexModel}
MODEL_PICK_MODEL_KEY = "_codex_model_pick_model"  # chosen model id


def build_model_picker(
    models: list[CodexModel], current: str = ""
) -> tuple[str, InlineKeyboardMarkup]:
    """Build the model selection message and keyboard."""
    lines = ["*Codex model*", ""]
    buttons: list[list[InlineKeyboardButton]] = []
    for m in models:
        marker = "● " if m.id == current else ""
        suffix = " (default)" if m.is_default else ""
        lines.append(f"{marker}*{m.display_name}*{suffix} — {m.description}")
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{marker}{m.display_name}",
                    callback_data=f"{CB_CODEX_MODEL_SELECT}{m.id}",
                )
            ]
        )
    lines.append("")
    lines.append("Applies from your next message in this topic.")
    buttons.append(
        [InlineKeyboardButton("Cancel", callback_data=CB_CODEX_MODEL_CANCEL)]
    )
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


def build_effort_picker(model: CodexModel) -> tuple[str, InlineKeyboardMarkup]:
    """Build the reasoning-effort keyboard for a chosen model."""
    text = f"*{model.display_name}* — choose reasoning effort"
    row: list[InlineKeyboardButton] = []
    rows: list[list[InlineKeyboardButton]] = []
    for effort in model.efforts:
        marker = "● " if effort == model.default_effort else ""
        row.append(
            InlineKeyboardButton(
                f"{marker}{effort}", callback_data=f"{CB_CODEX_EFFORT_SELECT}{effort}"
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("Cancel", callback_data=CB_CODEX_MODEL_CANCEL)])
    return text, InlineKeyboardMarkup(rows)


def parse_model_args(args: str, models: list[CodexModel]) -> tuple[str, str, str]:
    """Parse ``/model <model> [effort]`` typed directly.

    Returns (model_id, effort, error).  Matches model by id or display name,
    case-insensitively.  ``error`` is non-empty when the input is invalid.
    """
    parts = args.split()
    if not parts:
        return "", "", ""
    wanted = parts[0].lower()
    match = next(
        (m for m in models if wanted in (m.id.lower(), m.display_name.lower())),
        None,
    )
    if match is None:
        known = ", ".join(m.id for m in models)
        return "", "", f"Unknown model {parts[0]!r}. Known models: {known}"
    effort = parts[1].lower() if len(parts) > 1 else ""
    if effort and match.efforts and effort not in match.efforts:
        return (
            "",
            "",
            f"Unknown effort {parts[1]!r} for {match.id}. Choose from: "
            + ", ".join(match.efforts),
        )
    return match.id, effort, ""


def format_model_choice(model_id: str, effort: str) -> str:
    """Confirmation text after a choice is stored."""
    detail = f"{model_id} {effort}".strip()
    return f"✅ Codex model set to *{detail}*.\nApplies from your next message in this topic."
