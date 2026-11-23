"""Understand Me — backend core API.

Caption queue + checksum engine for the Even G2 app.

Run:
    uvicorn main:app --reload --port 8000
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from captions import CaptionStore, ConnectionManager
from checksum import SLOT_NAMES, compare, get_extractor

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

# ---------------------------------------------------------------------------
# Checksum card state (what the glasses app polls)
# ---------------------------------------------------------------------------

SLOT_LABELS = {
    "deadline": "期限",
    "quantity": "数量",
    "task": "作業内容",
    "destination": "提出先",
}

# The most recent instruction-like caption, per the auto-checksum flow:
# speaker A instructs -> speaker B paraphrases -> diff becomes a card.
last_instruction: dict | None = None
pending_card: dict | None = None
card_responses: list[dict] = []


def _set_card_from_diffs(diffs: list[dict]) -> dict | None:
    """Turn the first diff into the pending glasses card, if any."""
    global pending_card
    if not diffs:
        return None
    first = diffs[0]
    pending_card = {
        "id": uuid.uuid4().hex[:12],
        "slot": SLOT_LABELS.get(first["slot"], first["slot"]),
        "original": first["original"],
        "heard": first["paraphrase"],
        "diffs": diffs,
    }
    return pending_card


def _auto_checksum(speaker: str, text: str) -> None:
    """Compare a new caption against the last instruction from another
    speaker; a mismatch becomes a pending checksum card."""
    global last_instruction
    slots = extractor.extract(text).as_dict()
    if not any(slots.values()):
        return  # not an instruction-like utterance
    if last_instruction is not None and speaker != last_instruction["speaker"]:
        prev = last_instruction["slots"]
        diffs = [
            {"slot": name, "original": prev[name], "paraphrase": slots[name]}
            for name in SLOT_NAMES
            if prev[name] != slots[name]
        ]
        if diffs:
            _set_card_from_diffs(diffs)
            # The mismatch is now owned by the card flow, so the instruction
            # is consumed: the next instruction-like utterance starts a fresh
            # comparison instead of being diffed against this stale one
            # (previously the paraphrasing speaker could never instruct).
            last_instruction = None
        return  # a paraphrase never replaces the instruction it refers to
    last_instruction = {"speaker": speaker, "text": text, "slots": slots}


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------

class CaptionIn(BaseModel):
    speaker: str
    text: str


@app.post("/captions")
async def post_caption(body: CaptionIn) -> dict:
    """Append an utterance and push it to all WebSocket clients.

    Also runs the auto-checksum: an instruction-like caption from a
    different speaker than the last instruction is treated as its
    paraphrase, and any slot mismatch becomes a pending card.
    """
    caption = store.add(body.speaker, body.text)
    _auto_checksum(body.speaker, body.text)
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
    _set_card_from_diffs(diffs)
    return diffs


@app.get("/checksum/latest")
async def get_checksum_latest() -> dict | None:
    """The pending checksum card for the glasses app:
    {"id", "slot", "original", "heard", "diffs"} or null."""
    return pending_card


class RespondIn(BaseModel):
    id: str
    action: Literal["confirm", "send_corrected"]


@app.post("/checksum/respond")
async def post_checksum_respond(body: RespondIn) -> dict:
    """Record the wearer's response to the pending card and clear it."""
    global pending_card
    if pending_card is None or body.id != pending_card["id"]:
        return {"status": "ignored"}
    card_responses.append({"id": body.id, "action": body.action})
    pending_card = None
    return {"status": "ok", "action": body.action}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
