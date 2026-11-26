"""Tests for the chat writeback flow.

A confirmed checksum card must travel back to the chat the instruction
came from: /checksum/respond queues an event, GET /writeback/pending
serves it to the right bot (?source=...), and POST /writeback/ack drops
it once the chat post succeeded.
"""

import pytest
from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)

INSTRUCTION = "木曜日までに資料を3部、教務部へ提出してください"
PARAPHRASE = "金曜日までに資料を3部、教務部へ提出します"


@pytest.fixture(autouse=True)
def reset_state():
    main.last_instruction = None
    main.pending_card = None
    main.card_responses.clear()
    main.writeback_events.clear()
    yield


def _make_card(source="discord", origin="142") -> dict:
    """Run the caption -> card flow and return the pending card."""
    client.post(
        "/captions",
        json={"speaker": "佐藤", "text": INSTRUCTION, "source": source, "origin": origin},
    )
    client.post(
        "/captions",
        json={"speaker": "田中", "text": PARAPHRASE, "source": source, "origin": origin},
    )
    card = client.get("/checksum/latest").json()
    assert card is not None
    return card


def test_confirm_queues_writeback_event():
    card = _make_card(source="discord", origin="142")
    r = client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    assert r.json()["status"] == "ok"

    events = client.get("/writeback/pending").json()
    assert len(events) == 1
    event = events[0]
    assert event["id"]
    assert event["card_id"] == card["id"]
    # The agreed version is the original instruction, not the paraphrase.
    assert event["final_text"] == INSTRUCTION
    assert event["source"] == "discord"
    assert event["origin"] == "142"
    assert event["created_at"]


def test_pending_filters_by_source():
    card = _make_card(source="telegram", origin="9001")
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})

    assert client.get("/writeback/pending?source=telegram").json()[0]["card_id"] == card["id"]
    assert client.get("/writeback/pending?source=discord").json() == []


def test_ack_removes_events():
    card = _make_card()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    event_id = client.get("/writeback/pending").json()[0]["id"]

    r = client.post("/writeback/ack", json={"ids": [event_id, "unknown-id"]})
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "acked": 1}
    assert client.get("/writeback/pending").json() == []


def test_failed_delivery_stays_pending_until_ack():
    card = _make_card()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    # No ack: the event must still be served on the next poll.
    assert len(client.get("/writeback/pending").json()) == 1


def test_send_corrected_does_not_queue_writeback():
    card = _make_card()
    r = client.post(
        "/checksum/respond", json={"id": card["id"], "action": "send_corrected"}
    )
    assert r.json()["status"] == "ok"
    assert client.get("/writeback/pending").json() == []


def test_wrong_id_queues_nothing():
    _make_card()
    r = client.post(
        "/checksum/respond", json={"id": "does-not-exist", "action": "confirm"}
    )
    assert r.json()["status"] == "ignored"
    assert client.get("/writeback/pending").json() == []


def test_compare_endpoint_can_tag_source_and_origin():
    r = client.post(
        "/checksum/compare",
        json={
            "original_text": INSTRUCTION,
            "paraphrase_text": PARAPHRASE,
            "source": "telegram",
            "origin": "777",
        },
    )
    assert r.status_code == 200 and r.json()  # non-empty diff list

    card = client.get("/checksum/latest").json()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})
    event = client.get("/writeback/pending?source=telegram").json()[0]
    assert event["final_text"] == INSTRUCTION
    assert event["origin"] == "777"


def test_event_without_source_only_in_unfiltered_list():
    r = client.post(
        "/checksum/compare",
        json={"original_text": INSTRUCTION, "paraphrase_text": PARAPHRASE},
    )
    assert r.json()  # a card was produced
    card = client.get("/checksum/latest").json()
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})

    assert client.get("/writeback/pending?source=discord").json() == []
    events = client.get("/writeback/pending").json()
    assert len(events) == 1 and events[0]["source"] is None
