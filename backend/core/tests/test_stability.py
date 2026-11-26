"""Stability bounds for long-running demos.

The caption store keeps only the newest UM_CAPTION_MAX entries, an
unanswered checksum card expires after UM_CARD_TTL_SECONDS, and an
undelivered writeback event is discarded after UM_WRITEBACK_TTL_SECONDS —
so yesterday's captions, cards, and writebacks cannot leak into a demo.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import main
from captions import CaptionStore
from main import app

client = TestClient(app)

INSTRUCTION = "木曜日までに資料を3部、教務部へ提出してください"
PARAPHRASE = "金曜日までに資料を3部、教務部へ提出します"


@pytest.fixture(autouse=True)
def reset_state():
    main.last_instruction = None
    main.pending_card = None
    main.pending_card_created_at = None
    main.card_responses.clear()
    main.writeback_events.clear()
    yield


def _make_card() -> dict:
    """Run the caption -> card flow and return the pending card."""
    client.post("/captions", json={"speaker": "佐藤", "text": INSTRUCTION})
    client.post("/captions", json={"speaker": "田中", "text": PARAPHRASE})
    card = client.get("/checksum/latest").json()
    assert card is not None
    return card


def _age_pending_card() -> None:
    """Backdate the pending card past its TTL."""
    main.pending_card_created_at = (
        datetime.now(timezone.utc) - main.CARD_TTL - timedelta(seconds=1)
    )


def test_caption_store_drops_oldest_beyond_limit():
    store = CaptionStore(max_items=3)
    for i in range(5):
        store.add("A", f"caption-{i}")
    assert [c["text"] for c in store.all()] == [
        "caption-2",
        "caption-3",
        "caption-4",
    ]


def test_caption_max_from_env(monkeypatch):
    monkeypatch.setenv("UM_CAPTION_MAX", "2")
    store = CaptionStore()
    for i in range(4):
        store.add("A", f"caption-{i}")
    assert [c["text"] for c in store.all()] == ["caption-2", "caption-3"]


def test_expired_card_not_served_and_respond_ignored():
    card = _make_card()
    _age_pending_card()

    assert client.get("/checksum/latest").json() is None

    r = client.post(
        "/checksum/respond", json={"id": card["id"], "action": "confirm"}
    )
    assert r.json()["status"] == "ignored"
    assert client.get("/writeback/pending").json() == []


def test_fresh_card_still_served_and_answerable():
    card = _make_card()
    assert client.get("/checksum/latest").json()["id"] == card["id"]
    r = client.post(
        "/checksum/respond", json={"id": card["id"], "action": "confirm"}
    )
    assert r.json()["status"] == "ok"


def test_expired_writeback_event_is_discarded():
    card = _make_card()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    assert len(main.writeback_events) == 1
    main.writeback_events[0]["created_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()

    assert client.get("/writeback/pending").json() == []
    assert main.writeback_events == []


def test_fresh_writeback_event_still_pending():
    card = _make_card()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    assert len(client.get("/writeback/pending").json()) == 1
