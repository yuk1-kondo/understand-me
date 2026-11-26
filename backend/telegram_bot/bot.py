"""Understand Me — Telegram tier (guaranteed fallback line).

Flow (mirrors the Discord main line, but over Telegram voice notes):

  voice note / text instruction
    -> STT (stt_interface)                     [voice only]
    -> POST {BACKEND_URL}/captions             {speaker, text}
    -> POST {BACKEND_URL}/checksum/extract     {text}
    -> reply in Telegram with the extracted confirmation points
       and inline buttons [confirm] [enter correction]
    -> confirm: reply with the confirmed text
       correct: ask the user to send the corrected instruction,
                then run the checksum on it again

  Button and guidance text follow the language of the instruction:
  Japanese characters in the caption text -> Japanese, otherwise English.

  Separately, a background task polls
    GET  {BACKEND_URL}/writeback/pending?source=telegram
  for checksum cards the wearer confirmed on the glasses and sends the
  agreed instruction back to the chat it came from (event `origin`,
  falling back to the most recent confirmation chat), then acks via
    POST {BACKEND_URL}/writeback/ack     {"ids": [...]}

Configuration is via environment variables only (see .env.example):
  TELEGRAM_BOT_TOKEN  BotFather token. Required; never hardcode.
  BACKEND_URL         Core backend base URL (default http://localhost:8000)
  STT_PROVIDER        "fake" (default), "whisper" (local faster-whisper)
                      or "real" (stub) — see stt_interface.py

Run:  python bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
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

# How often the bot asks the backend for confirmed cards to write back.
WRITEBACK_POLL_SECONDS = float(os.environ.get("WRITEBACK_POLL_SECONDS", "5"))
TELEGRAM_MESSAGE_MAX = 4096

# Slot keys returned by /checksum/extract, with per-language labels used
# in the confirmation message. Order matters: deadline first.
SLOT_LABELS = {
    "ja": [
        ("deadline", "期限"),
        ("quantity", "数量"),
        ("task", "作業内容"),
        ("destination", "提出先"),
    ],
    "en": [
        ("deadline", "deadline"),
        ("quantity", "quantity"),
        ("task", "task"),
        ("destination", "destination"),
    ],
}

# Same kana/kanji test as backend/core/checksum.py:looks_japanese —
# the UI language follows the caption text, not a user setting.
_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")


def detect_lang(text: str) -> str:
    """Return 'ja' when the caption text contains Japanese, else 'en'."""
    return "ja" if _JAPANESE_RE.search(text or "") else "en"


STRINGS = {
    "ja": {
        "confirm_header": "📋 理解の確認ポイント",
        "confirm_question": "この理解で合っていますか？",
        "confirmed_header": "✅ 確定しました",
        "original_label": "原文",
        "checked_label": "確認済み",
        "btn_confirm": "この内容で確定",
        "btn_correct": "訂正文を入力",
        "extract_failed": "ごめんなさい、確認ポイントの抽出に失敗しました。もう一度送ってください。",
        "transcript_label": "文字起こし",
        "colon": "：",
        "no_points": "（確認ポイントは見つかりませんでした）",
        "start": (
            "Understand Me です。ボイスメモかテキストで指示を送ってください。"
            "文字起こしして、理解の確認ポイント（期限・数量・作業内容・提出先）を返します。"
        ),
        "stt_missing": "音声の文字起こしがまだ設定されていません（STT_PROVIDER を確認してください）。",
        "correction_received": "訂正版を受け取りました。再度確認します。",
        "stale_alert": "この確認は更新されました。最新の確認メッセージを見てください。",
        "correction_prompt": "直した箇所を含めて、指示の全文を送ってください。\n（元の指示：{original}）",
        "speaker_fallback": "話者",
        "writeback": "✅ 理解チェック確定: 「{text}」",
    },
    "en": {
        "confirm_header": "📋 Comprehension checkpoints",
        "confirm_question": "Is this understanding correct?",
        "confirmed_header": "✅ Confirmed",
        "original_label": "Original",
        "checked_label": "Checked",
        "btn_confirm": "Confirm as is",
        "btn_correct": "Enter correction",
        "extract_failed": "Sorry, checkpoint extraction failed. Please send it again.",
        "transcript_label": "Transcript",
        "colon": ": ",
        "no_points": "(no checkpoints found)",
        "start": (
            "This is Understand Me. Send an instruction as a voice note or text. "
            "I'll transcribe it and reply with comprehension checkpoints "
            "(deadline, quantity, task, destination)."
        ),
        "stt_missing": "Speech transcription is not configured yet (check STT_PROVIDER).",
        "correction_received": "Got the corrected version. Checking again.",
        "stale_alert": "This confirmation has been updated. Please see the latest confirmation message.",
        "correction_prompt": "Please resend the full instruction including your fix.\n(Original: {original})",
        "speaker_fallback": "Speaker",
        "writeback": '✅ Understanding confirmed: "{text}"',
    },
}

CB_CONFIRM = "checksum:confirm"
CB_CORRECT = "checksum:correct"


# ---------------------------------------------------------------------------
# Backend calls
# ---------------------------------------------------------------------------

async def post_caption(
    speaker: str, text: str, source: str | None = None, origin: str | None = None
) -> None:
    """Send a transcript line to the glasses caption queue.

    source/origin tag the caption so a checksum card it helps create can
    be routed back to this chat when the wearer confirms it.
    """
    payload = {"speaker": speaker, "text": text}
    if source:
        payload["source"] = source
    if origin:
        payload["origin"] = origin
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BACKEND_URL}/captions", json=payload)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Captions are best-effort: the checksum flow must not die
        # because the caption queue is down.
        logger.warning("caption post failed: %s", exc)


async def extract_slots(text: str) -> dict[str, Any]:
    """Ask the backend to extract checksum slots from an instruction.

    The backend returns the flat dict
      {"deadline": ..., "quantity": ..., "task": ..., "destination": ...}
    with nulls for unfound slots; an older {"slots": {...}} wrapper is
    also accepted. Missing/empty slots are dropped from the result.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{BACKEND_URL}/checksum/extract",
            json={"text": text},
        )
        resp.raise_for_status()
        data = resp.json()
    slots = data.get("slots") if isinstance(data.get("slots"), dict) else data
    return {k: v for k, v in slots.items() if v}


async def fetch_pending_writebacks() -> list[dict]:
    """Undelivered writeback events for this bot (source=telegram only)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{BACKEND_URL}/writeback/pending", params={"source": "telegram"}
        )
        resp.raise_for_status()
        return resp.json()


async def ack_writebacks(ids: list[str]) -> None:
    """Tell the backend these events were delivered."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BACKEND_URL}/writeback/ack", json={"ids": ids})
        resp.raise_for_status()


def format_writeback(final_text: str) -> str:
    """Chat message announcing the wearer's confirmed understanding."""
    text = (final_text or "").strip()
    message = STRINGS[detect_lang(text)]["writeback"].format(text=text)
    if len(message) > TELEGRAM_MESSAGE_MAX:
        message = message[: TELEGRAM_MESSAGE_MAX - 1] + "…"
    return message


async def writeback_loop(application: Application) -> None:
    """Poll the backend for confirmed cards and send them to the chat.

    The target chat is the event's `origin` (the chat id the caption was
    posted from); when the event has no origin, fall back to the chat of
    the most recent confirmation card this bot handled. Delivery is
    at-least-once: only successfully sent events are acked.
    """
    while True:
        await asyncio.sleep(WRITEBACK_POLL_SECONDS)
        try:
            events = await fetch_pending_writebacks()
        except httpx.HTTPError as exc:
            logger.warning("writeback poll failed: %s", exc)
            continue
        delivered: list[str] = []
        for event in events:
            chat_id = event.get("origin") or application.bot_data.get(
                "last_confirmation_chat_id"
            )
            if not chat_id:
                logger.warning(
                    "writeback event %s has no chat to deliver to; leaving pending",
                    event.get("id"),
                )
                continue
            try:
                await application.bot.send_message(
                    chat_id=int(chat_id), text=format_writeback(event.get("final_text"))
                )
                delivered.append(event["id"])
                logger.info(
                    "writeback sent to chat %s: card %s", chat_id, event.get("card_id")
                )
            except Exception:
                # Not acked -> stays pending and is retried next poll.
                logger.exception(
                    "writeback send failed for event %s; will retry", event.get("id")
                )
        if delivered:
            try:
                await ack_writebacks(delivered)
            except httpx.HTTPError as exc:
                logger.warning("writeback ack failed: %s", exc)


async def post_init(application: Application) -> None:
    application.create_task(writeback_loop(application))


# ---------------------------------------------------------------------------
# Checksum presentation
# ---------------------------------------------------------------------------

def format_confirmation(slots: dict[str, Any], lang: str) -> str:
    s = STRINGS[lang]
    lines = [s["confirm_header"]]
    for key, label in SLOT_LABELS[lang]:
        value = slots.get(key)
        if value:
            lines.append(f"・{label}{s['colon']}{value}")
    lines.append("")
    lines.append(s["confirm_question"])
    return "\n".join(lines)


def format_confirmed(original: str, slots: dict[str, Any], lang: str) -> str:
    s = STRINGS[lang]
    points = "／".join(
        f"{label}{s['colon']}{slots[key]}"
        for key, label in SLOT_LABELS[lang]
        if slots.get(key)
    )
    return (
        f"{s['confirmed_header']}\n"
        f"{s['original_label']}{s['colon']}{original}\n"
        f"{s['checked_label']}{s['colon']}{points}"
    )


def confirmation_keyboard(card_id: str, lang: str) -> InlineKeyboardMarkup:
    # H-05: the card id travels in callback_data so a stale button can be
    # told apart from the current pending card. M-06: stacked vertically
    # and labelled by outcome, not by the wearer's judgement.
    s = STRINGS[lang]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(s["btn_confirm"], callback_data=f"{CB_CONFIRM}:{card_id}")],
            [InlineKeyboardButton(s["btn_correct"], callback_data=f"{CB_CORRECT}:{card_id}")],
        ]
    )


async def run_checksum(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    speaker: str,
    text: str,
) -> None:
    """Post the caption, extract slots, and present the confirmation."""
    chat_id = update.effective_chat.id if update.effective_chat else None
    await post_caption(
        speaker,
        text,
        source="telegram",
        origin=str(chat_id) if chat_id is not None else None,
    )
    lang = detect_lang(text)
    s = STRINGS[lang]

    try:
        slots = await extract_slots(text)
    except httpx.HTTPError as exc:
        logger.error("checksum extract failed: %s", exc)
        await update.effective_message.reply_text(s["extract_failed"])
        return

    if not slots:
        await update.effective_message.reply_text(
            f"{s['transcript_label']}{s['colon']}{text}\n{s['no_points']}"
        )
        return

    # Remember the pending checksum so the callback knows what is being
    # confirmed. Keyed by chat: one active instruction per chat is
    # enough for the hackathon scope. The message id doubles as the
    # card id embedded in the buttons (H-05).
    card_id = str(update.effective_message.message_id)
    context.chat_data["pending"] = {
        "id": card_id, "text": text, "slots": slots, "lang": lang,
    }
    context.chat_data["awaiting_correction"] = False
    # Fallback writeback target for events that carry no origin.
    context.bot_data["last_confirmation_chat_id"] = update.effective_chat.id

    await update.effective_message.reply_text(
        f"{s['transcript_label']}{s['colon']}{text}\n\n"
        + format_confirmation(slots, lang),
        reply_markup=confirmation_keyboard(card_id, lang),
    )


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # No caption text yet, so the intro stays on the default language.
    await update.effective_message.reply_text(STRINGS["en"]["start"])


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    voice_file = await context.bot.get_file(message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        await voice_file.download_to_drive(tmp_path)
        provider = get_stt_provider()
        text = await provider.transcribe(tmp_path)
    except NotImplementedError as exc:
        logger.error("STT not configured: %s", exc)
        await message.reply_text(STRINGS["en"]["stt_missing"])
        return
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    speaker = (
        update.effective_user.full_name or STRINGS[detect_lang(text)]["speaker_fallback"]
    )
    await run_checksum(update, context, speaker, text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    text = message.text.strip()
    if not text:
        return
    lang = detect_lang(text)
    speaker = update.effective_user.full_name or STRINGS[lang]["speaker_fallback"]

    if context.chat_data.get("awaiting_correction"):
        # This message is the corrected instruction: checksum it again.
        context.chat_data["awaiting_correction"] = False
        await message.reply_text(STRINGS[lang]["correction_received"])

    # Plain text is treated as an instruction to checksum, exactly like
    # a transcribed voice note.
    await run_checksum(update, context, speaker, text)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    action, sep, card_id = data.rpartition(":")

    # H-05: act only when the button's card id matches the pending card.
    # A stale button (older card, no pending card, or a pre-id button)
    # must not touch the current card — it only gets a notice.
    pending = context.chat_data.get("pending")
    lang = pending.get("lang", "en") if pending else "en"
    if (
        not sep
        or action not in (CB_CONFIRM, CB_CORRECT)
        or not pending
        or pending.get("id") != card_id
    ):
        await query.answer(STRINGS[lang]["stale_alert"], show_alert=True)
        return

    await query.answer()
    if action == CB_CONFIRM:
        context.chat_data["pending"] = None
        context.chat_data["awaiting_correction"] = False
        await query.edit_message_text(
            format_confirmed(pending["text"], pending["slots"], lang)
        )
    else:
        context.chat_data["awaiting_correction"] = True
        await query.edit_message_text(
            # M-06: a slot-only reply would lose the other slots, so the
            # whole instruction must be sent again with the fix inside.
            STRINGS[lang]["correction_prompt"].format(original=pending["text"])
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

    app = Application.builder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Understand Me Telegram bot starting (backend: %s)", BACKEND_URL)
    app.run_polling()


if __name__ == "__main__":
    main()
