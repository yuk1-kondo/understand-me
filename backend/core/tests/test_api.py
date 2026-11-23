"""API smoke tests: captions endpoints, checksum endpoints, WebSocket, STT."""

import pytest
from fastapi.testclient import TestClient

import stt
from main import app

client = TestClient(app)

ORIGINAL = "木曜日までに資料を3部、教務部へ提出してください"


def test_caption_post_and_get():
    res = client.post("/captions", json={"speaker": "先生", "text": ORIGINAL})
    assert res.status_code == 200
    caption = res.json()
    assert caption["speaker"] == "先生"
    assert caption["text"] == ORIGINAL
    assert "ts" in caption

    res = client.get("/captions")
    assert res.status_code == 200
    assert any(c["text"] == ORIGINAL for c in res.json())


def test_websocket_pushes_new_caption():
    with client.websocket_connect("/ws") as ws:
        client.post("/captions", json={"speaker": "A", "text": "こんにちは"})
        data = ws.receive_json()
        assert data["speaker"] == "A"
        assert data["text"] == "こんにちは"
        assert "ts" in data


def test_extract_endpoint():
    res = client.post("/checksum/extract", json={"text": ORIGINAL})
    assert res.status_code == 200
    slots = res.json()
    assert slots["deadline"] == "木曜日"
    assert slots["quantity"] == "3部"
    assert slots["destination"] == "教務部"


def test_compare_endpoint_detects_weekday_mismatch():
    res = client.post(
        "/checksum/compare",
        json={
            "original_text": ORIGINAL,
            "paraphrase_text": "金曜日までに資料を3部、教務部へ提出します",
        },
    )
    assert res.status_code == 200
    diffs = res.json()
    assert any(
        d["slot"] == "deadline"
        and d["original"] == "木曜日"
        and d["paraphrase"] == "金曜日"
        for d in diffs
    )


def test_stt_stub_raises_with_clear_message():
    with pytest.raises(NotImplementedError, match="speech-to-text"):
        stt.UnconfiguredSTT().transcribe(b"fake-audio")


def test_stt_fake_returns_fixed_text():
    assert stt.fake_transcribe(b"fake-audio") == stt.DEFAULT_FAKE_TEXT
    assert stt.FakeSTT("テスト").transcribe(b"x") == "テスト"
