"""Understand Me — Telegram tier (guaranteed fallback line).

Flow (mirrors the Discord main line, but over Telegram voice notes):

  voice note / text instruction
    -> STT (stt_interface)                     [voice only]
    -> POST {BACKEND_URL}/captions             {speaker, text}
    -> POST {BACKEND_URL}/checksum/extract     {text}
    -> reply in Telegram with the extracted confirmation points
       and inline buttons [正しい] [直したい]
    -> confirm: reply with the confirmed text
       correct: ask the user to send the corrected instruction,
                then run the checksum on it again

Configuration is via environment variables only (see .env.example):
  TELEGRAM_BOT_TOKEN  BotFather token. Required; never hardcode.
  BACKEND_URL         Core backend base URL (default http://localhost:8000)
  STT_PROVIDER        "fake" (default) or "real" — see stt_interface.py

Run:  python bot.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from stt_interface import get_stt_provider

logging.basicConfig(
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("understand-me-telegram")

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

# Slot keys returned by /checksum/extract, with the Japanese labels used
# in the confirmation message. Order matters: deadline first.
SLOT_LABELS = [
    ("deadline", "期限"),
    ("quantity", "数量"),
    ("task", "作業内容"),
    ("destination", "提出先"),
]

CB_CONFIRM = "checksum:confirm"
CB_CORRECT = "checksum:correct"


# ---------------------------------------------------------------------------
# Backend calls
# ---------------------------------------------------------------------------

async def post_caption(speaker: str, text: str) -> None:
    """Send a transcript line to the glasses caption queue."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"{BACKEND_URL}/captions",
                json={"speaker": speaker, "text": text},
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Captions are best-effort: the checksum flow must not die
        # because the caption queue is down.
        logger.warning("caption post failed: %s", exc)


async def extract_slots(text: str) -> dict[str, Any]:
    """Ask the backend to extract checksum slots from an instruction.

    Expected response shape:
      {"slots": {"deadline": ..., "quantity": ..., "task": ...,
                 "destination": ...}}
    Missing/empty slots are simply absent from the dict.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BACKEND_URL}/checksum/extract",
            json={"text": text},
        )
        resp.raise_for_status()
        data = resp.json()
    return data.get("slots") or {}


# ---------------------------------------------------------------------------
# Checksum presentation
# ---------------------------------------------------------------------------

def format_confirmation(slots: dict[str, Any]) -> str:
    lines = ["📋 理解の確認ポイント"]
    for key, label in SLOT_LABELS:
        value = slots.get(key)
        if value:
            lines.append(f"・{label}：{value}")
    lines.append("")
    lines.append("この理解で合っていますか？")
    return "\n".join(lines)


def format_confirmed(original: str, slots: dict[str, Any]) -> str:
    points = "／".join(
        f"{label}：{slots[key]}" for key, label in SLOT_LABELS if slots.get(key)
    )
    return f"✅ 確定しました\n原文：{original}\n確認済み：{points}"


def confirmation_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("正しい", callback_data=CB_CONFIRM),
                InlineKeyboardButton("直したい", callback_data=CB_CORRECT),
            ]
        ]
    )


async def run_checksum(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    speaker: str,
    text: str,
) -> None:
    """Post the caption, extract slots, and present the confirmation."""
    await post_caption(speaker, text)

    try:
        slots = await extract_slots(text)
    except httpx.HTTPError as exc:
        logger.error("checksum extract failed: %s", exc)
        await update.effective_message.reply_text(
            "ごめんなさい、確認ポイントの抽出に失敗しました。もう一度送ってください。"
        )
        return

    if not slots:
        await update.effective_message.reply_text(
            f"文字起こし：{text}\n（確認ポイントは見つかりませんでした）"
        )
        return

    # Remember the pending checksum so the callback knows what is being
    # confirmed. Keyed by chat: one active instruction per chat is
    # enough for the hackathon scope.
    context.chat_data["pending"] = {"text": text, "slots": slots}
    context.chat_data["awaiting_correction"] = False

    await update.effective_message.reply_text(
        f"文字起こし：{text}\n\n" + format_confirmation(slots),
        reply_markup=confirmation_keyboard(),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Understand Me です。ボイスメモかテキストで指示を送ってください。"
        "文字起こしして、理解の確認ポイント（期限・数量・作業内容・提出先）を返します。"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    speaker = update.effective_user.full_name or "話者"

    voice_file = await context.bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await voice_file.download_to_drive(tmp_path)
        provider = get_stt_provider()
        text = await provider.transcribe(tmp_path)
    except NotImplementedError as exc:
        logger.error("STT not configured: %s", exc)
        await message.reply_text(
            "音声の文字起こしがまだ設定されていません（STT_PROVIDER を確認してください）。"
        )
        return
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    await run_checksum(update, context, speaker, text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    speaker = update.effective_user.full_name or "話者"
    text = message.text.strip()
    if not text:
        return

    if context.chat_data.get("awaiting_correction"):
        # This message is the corrected instruction: checksum it again.
        context.chat_data["awaiting_correction"] = False
        await message.reply_text("訂正版を受け取りました。再度確認します。")

    # Plain text is treated as an instruction to checksum, exactly like
    # a transcribed voice note.
    await run_checksum(update, context, speaker, text)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    pending = context.chat_data.get("pending")
    if not pending:
        await query.edit_message_text("確認中の指示がありません。新しい指示を送ってください。")
        return

    if query.data == CB_CONFIRM:
        context.chat_data["pending"] = None
        context.chat_data["awaiting_correction"] = False
        await query.edit_message_text(
            format_confirmed(pending["text"], pending["slots"])
        )
    elif query.data == CB_CORRECT:
        context.chat_data["awaiting_correction"] = True
        await query.edit_message_text(
            "直したい内容を、そのまま文章で送ってください。\n"
            f"（元の指示：{pending['text']}）"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather "
            "and export the token (see README.md); never hardcode it."
        )

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Understand Me Telegram bot starting (backend: %s)", BACKEND_URL)
    app.run_polling()


if __name__ == "__main__":
    main()
