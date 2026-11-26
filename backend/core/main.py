"""Understand Me — backend core API.

Caption queue + checksum engine for the Even G2 app.

Run:
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from captions import CaptionStore, ConnectionManager, now_iso
from checksum import SLOT_NAMES, compare, get_extractor, looks_japanese
from jev_judge import AGREEMENT_NO, INSTRUCTION_NO, INSTRUCTION_YES, get_judge

app = FastAPI(title="Understand Me — backend core")

# The Even Hub app runs in a WebView on the phone and fetches this API
# cross-origin; the Even app whitelist does not bypass CORS, so the API
# must send these headers itself. Local/demo scope: allow all origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = CaptionStore()
manager = ConnectionManager()
extractor = get_extractor()
# Optional Jev judgment layer; None unless TYPESAFE_API_KEY is set.
# Tests may replace this with a fake judge.
judge = get_judge()


def _env_int(name: str, default: int) -> int:
    """Positive int from the environment, falling back to `default`."""
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


# Retention bounds for in-memory state, overridable via env vars so a
# long-running demo does not surface yesterday's cards or writebacks.
CARD_TTL = timedelta(seconds=_env_int("UM_CARD_TTL_SECONDS", 30 * 60))
WRITEBACK_TTL = timedelta(seconds=_env_int("UM_WRITEBACK_TTL_SECONDS", 60 * 60))

# ---------------------------------------------------------------------------
# Checksum card state (what the glasses app polls)
# ---------------------------------------------------------------------------

SLOT_LABELS = {
    "deadline": "期限",
    "quantity": "数量",
    "task": "作業内容",
    "destination": "提出先",
    "content": "内容",
}

SLOT_LABELS_EN = {
    "deadline": "Deadline",
    "quantity": "Quantity",
    "task": "Task",
    "destination": "Destination",
    "content": "Content",
}

# The most recent instruction-like caption, per the auto-checksum flow:
# speaker A instructs -> speaker B paraphrases -> diff becomes a card.
last_instruction: dict | None = None
pending_card: dict | None = None
pending_card_created_at: datetime | None = None
card_responses: list[dict] = []

# Confirmed cards waiting to be written back to the chat the instruction
# came from (Discord voice-channel chat / Telegram chat). Each entry:
# {"id", "card_id", "final_text", "source", "origin", "created_at"}.
# Consumed via GET /writeback/pending + POST /writeback/ack.
writeback_events: list[dict] = []


def _set_card_from_diffs(
    diffs: list[dict],
    source_text: str = "",
    source: str | None = None,
    origin: str | None = None,
) -> dict | None:
    """Turn the first diff into the pending glasses card, if any.

    Card labels follow the language of the original instruction, so an
    English conversation produces an English card. `instruction` keeps the
    full original text so a confirmed card can be written back to chat;
    `source`/`origin` say which transport (discord/telegram) and where.
    """
    global pending_card, pending_card_created_at
    if not diffs:
        return None
    labels = SLOT_LABELS if looks_japanese(source_text) else SLOT_LABELS_EN
    first = diffs[0]
    pending_card_created_at = datetime.now(timezone.utc)
    pending_card = {
        "id": uuid.uuid4().hex[:12],
        "slot": labels.get(first["slot"], first["slot"]),
        "original": first["original"],
        "heard": first["paraphrase"],
        "diffs": diffs,
        "instruction": source_text,
        "source": source,
        "origin": origin,
    }
    return pending_card


def _expire_pending_card() -> None:
    """Drop the pending card once it outlives CARD_TTL, so a stale
    confirmation prompt is neither shown to the wearer nor answerable."""
    global pending_card, pending_card_created_at
    if (
        pending_card is not None
        and pending_card_created_at is not None
        and datetime.now(timezone.utc) - pending_card_created_at > CARD_TTL
    ):
        pending_card = None
        pending_card_created_at = None


def _writeback_expired(event: dict, now: datetime) -> bool:
    try:
        created = datetime.fromisoformat(event["created_at"])
    except (KeyError, TypeError, ValueError):
        return True  # no trustworthy timestamp -> treat as stale
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return now - created > WRITEBACK_TTL


def _prune_writeback_events() -> None:
    """Discard undelivered writeback events older than WRITEBACK_TTL."""
    global writeback_events
    now = datetime.now(timezone.utc)
    writeback_events = [
        e for e in writeback_events if not _writeback_expired(e, now)
    ]


def _is_instruction_like(text: str, slots: dict) -> bool:
    """Decide whether a caption counts as an instruction.

    The deterministic rule (any slot found) is the default. When the Jev
    judgment layer is enabled, its probability can overrule the rule at
    the extremes: below INSTRUCTION_NO the utterance is chit-chat even
    with slots, and at/above INSTRUCTION_YES it is an instruction even
    without any slot. In between — and on any Jev failure — the rule
    verdict stands (fail-open).
    """
    rule_verdict = any(slots.values())
    if judge is None:
        return rule_verdict
    probability = judge.is_instruction(text)
    if probability is None:
        return rule_verdict
    if probability < INSTRUCTION_NO:
        return False
    if probability >= INSTRUCTION_YES:
        return True
    return rule_verdict


def _auto_checksum(
    speaker: str, text: str, source: str | None = None, origin: str | None = None
) -> None:
    """Compare a new caption against the last instruction from another
    speaker; a mismatch becomes a pending checksum card."""
    global last_instruction
    slots = extractor.extract(text).as_dict()
    if not _is_instruction_like(text, slots):
        return  # not an instruction-like utterance
    if last_instruction is not None and speaker != last_instruction["speaker"]:
        prev = last_instruction["slots"]
        diffs = [
            {"slot": name, "original": prev[name], "paraphrase": slots[name]}
            for name in SLOT_NAMES
            if prev[name] != slots[name]
        ]
        if not diffs and judge is not None:
            # The slot diff sees no mismatch; ask Jev whether the two
            # utterances actually agree (catches pattern-less pairs).
            agreement = judge.agrees(last_instruction["text"], text)
            if agreement is not None and agreement < AGREEMENT_NO:
                diffs = [
                    {
                        "slot": "content",
                        "original": last_instruction["text"],
                        "paraphrase": text,
                    }
                ]
        if diffs:
            _set_card_from_diffs(
                diffs,
                last_instruction["text"],
                # The card lives where the conversation lives: prefer this
                # caption's transport, fall back to the instruction's.
                source or last_instruction.get("source"),
                origin or last_instruction.get("origin"),
            )
            # The mismatch is now owned by the card flow, so the instruction
            # is consumed: the next instruction-like utterance starts a fresh
            # comparison instead of being diffed against this stale one
            # (previously the paraphrasing speaker could never instruct).
            last_instruction = None
        return  # a paraphrase never replaces the instruction it refers to
    last_instruction = {
        "speaker": speaker,
        "text": text,
        "slots": slots,
        "source": source,
        "origin": origin,
    }


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------

class CaptionIn(BaseModel):
    speaker: str
    text: str
    # Optional transport tags ("discord" / "telegram") + where the caption
    # happened (channel id / chat id). They ride along to any checksum card
    # this utterance helps create so a confirmation can be written back.
    source: str | None = None
    origin: str | None = None


@app.post("/captions")
async def post_caption(body: CaptionIn) -> dict:
    """Append an utterance and push it to all WebSocket clients.

    Also runs the auto-checksum: an instruction-like caption from a
    different speaker than the last instruction is treated as its
    paraphrase, and any slot mismatch becomes a pending card.
    """
    caption = store.add(body.speaker, body.text)
    _auto_checksum(body.speaker, body.text, body.source, body.origin)
    await manager.broadcast(caption)
    return caption


@app.get("/captions")
async def get_captions() -> list[dict]:
    """Return every caption received so far, in order."""
    return store.all()


@app.websocket("/ws")
async def ws_captions(ws: WebSocket) -> None:
    """Live caption feed: each new caption is pushed as a JSON object
    {"speaker": str, "text": str, "ts": ISO string}."""
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # keep-alive; client messages ignored
    except WebSocketDisconnect:
        await manager.disconnect(ws)


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------

class ExtractIn(BaseModel):
    text: str


class CompareIn(BaseModel):
    original_text: str
    paraphrase_text: str
    source: str | None = None
    origin: str | None = None


@app.post("/checksum/extract")
async def post_extract(body: ExtractIn) -> dict:
    """Extract {deadline, quantity, task, destination} from an instruction."""
    return extractor.extract(body.text).as_dict()


@app.post("/checksum/compare")
async def post_compare(body: CompareIn) -> list[dict]:
    """Diff the slots of an original instruction vs. its paraphrase.

    Returns a JSON list of {"slot", "original", "paraphrase"} entries;
    an empty list means the understanding matches. A non-empty result
    also becomes the pending card served by GET /checksum/latest.
    """
    diffs = compare(body.original_text, body.paraphrase_text, extractor)
    _set_card_from_diffs(diffs, body.original_text, body.source, body.origin)
    return diffs


@app.get("/checksum/latest")
async def get_checksum_latest() -> dict | None:
    """The pending checksum card for the glasses app:
    {"id", "slot", "original", "heard", "diffs"} or null."""
    _expire_pending_card()
    return pending_card


class RespondIn(BaseModel):
    id: str
    action: Literal["confirm", "send_corrected"]


@app.post("/checksum/respond")
async def post_checksum_respond(body: RespondIn) -> dict:
    """Record the wearer's response to the pending card and clear it.

    A "confirm" also queues a writeback event: the agreed instruction is
    what the chat participants should act on, so the bots deliver it back
    to the channel the card came from. "send_corrected" carries no new
    text, so there is nothing agreed to write back yet.
    """
    global pending_card, pending_card_created_at
    _expire_pending_card()
    if pending_card is None or body.id != pending_card["id"]:
        return {"status": "ignored"}
    card_responses.append({"id": body.id, "action": body.action})
    if body.action == "confirm":
        _prune_writeback_events()
        writeback_events.append(
            {
                "id": uuid.uuid4().hex[:12],
                "card_id": pending_card["id"],
                # The agreed version is the original instruction text; fall
                # back to the card's slot value when the full text is unknown.
                "final_text": pending_card.get("instruction")
                or pending_card["original"],
                "source": pending_card.get("source"),
                "origin": pending_card.get("origin"),
                "created_at": now_iso(),
            }
        )
    pending_card = None
    pending_card_created_at = None
    return {"status": "ok", "action": body.action}


# ---------------------------------------------------------------------------
# Writeback delivery (chat bots poll these)
# ---------------------------------------------------------------------------


@app.get("/writeback/pending")
async def get_writeback_pending(source: str | None = None) -> list[dict]:
    """Undelivered writeback events, optionally filtered by source
    (?source=discord / telegram). Each bot polls only its own source.
    Events with no source are returned only by an unfiltered call."""
    _prune_writeback_events()
    if source is None:
        return list(writeback_events)
    return [e for e in writeback_events if e["source"] == source]


class WritebackAckIn(BaseModel):
    ids: list[str]


@app.post("/writeback/ack")
async def post_writeback_ack(body: WritebackAckIn) -> dict:
    """Drop acknowledged events. A bot acks only after the chat post
    succeeded, so a failed delivery stays pending and is retried."""
    global writeback_events
    done = set(body.ids)
    before = len(writeback_events)
    writeback_events = [e for e in writeback_events if e["id"] not in done]
    return {"status": "ok", "acked": before - len(writeback_events)}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
