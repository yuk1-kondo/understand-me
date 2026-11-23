"""Tests for the glasses-facing checksum card endpoints.

Flow: an instruction caption from speaker A, then a paraphrase caption
from speaker B with a different deadline -> a pending card appears at
GET /checksum/latest -> POST /checksum/respond clears it.
"""

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_instruction_paraphrase_creates_card_and_respond_clears_it():
    r = client.post(
        "/captions",
        json={
            "speaker": "佐藤",
            "text": "木曜日までに資料を3部、教務部へ提出してください",
        },
    )
    assert r.status_code == 200

    r = client.post(
        "/captions",
        json={
            "speaker": "田中",
            "text": "金曜日までに資料を3部、教務部へ提出します",
        },
    )
    assert r.status_code == 200

    r = client.get("/checksum/latest")
    assert r.status_code == 200
    card = r.json()
    assert card is not None
    assert card["slot"] == "期限"
    assert card["original"] == "木曜日"
    assert card["heard"] == "金曜日"

    r = client.post(
        "/checksum/respond", json={"id": card["id"], "action": "confirm"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    r = client.get("/checksum/latest")
    assert r.json() is None


def test_respond_with_wrong_id_is_ignored():
    r = client.post(
        "/checksum/respond", json={"id": "does-not-exist", "action": "confirm"}
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ignored"
