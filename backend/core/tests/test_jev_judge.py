"""Jev judgment layer tests.

Two levels:
  - JevJudge client: response parsing and fail-open behavior, using an
    httpx MockTransport (no network, no API key).
  - Auto-checksum integration: a fake judge monkeypatched into main
    shows the three ways Jev changes the flow — chit-chat suppression,
    pattern-less agreement alarm, and fail-open to the rule behavior.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from jev_judge import JevJudge
from main import app

client = TestClient(app)

INSTR = "木曜日までに資料を3部、教務部へ提出してください"
PARA_DIFF = "金曜日までに資料を3部、教務部へ提出します"


# ---------------------------------------------------------------------------
# JevJudge client
# ---------------------------------------------------------------------------


def _judge_with_transport(handler) -> JevJudge:
    transport = httpx.MockTransport(handler)
    return JevJudge("test-key", client=httpx.Client(transport=transport))


def test_is_instruction_parses_noul_probability():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        import json

        body = json.loads(request.content)
        seen["type"] = body["questions"]["q"]["type"]
        return httpx.Response(
            200,
            json={
                "model": "jev-1.14.0",
                "answers": {"q": {"type": "noul", "noul": 0.97}},
                "usage": {"input_tokens": 42, "output_tokens": 2},
            },
        )

    judge = _judge_with_transport(handler)
    assert judge.is_instruction(INSTR) == pytest.approx(0.97)
    assert seen["auth"] == "Bearer test-key"
    assert seen["type"] == "noul"


def test_judge_returns_none_on_http_error():
    judge = _judge_with_transport(lambda req: httpx.Response(500, text="boom"))
    assert judge.is_instruction(INSTR) is None
    assert judge.agrees(INSTR, PARA_DIFF) is None


def test_judge_returns_none_on_malformed_response():
    judge = _judge_with_transport(lambda req: httpx.Response(200, json={"nope": 1}))
    assert judge.is_instruction(INSTR) is None


# ---------------------------------------------------------------------------
# Auto-checksum integration with a fake judge
# ---------------------------------------------------------------------------


class FakeJudge:
    def __init__(self, instruction_p=None, agreement_p=None):
        self.instruction_p = instruction_p
        self.agreement_p = agreement_p

    def is_instruction(self, text):
        return self.instruction_p

    def agrees(self, instruction_text, paraphrase_text):
        return self.agreement_p


def _reset_state() -> None:
    main.last_instruction = None
    main.pending_card = None


def test_chitchat_suppressed_when_jev_confident(monkeypatch):
    _reset_state()
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=0.1))
    client.post("/captions", json={"speaker": "佐藤", "text": INSTR})
    client.post("/captions", json={"speaker": "田中", "text": PARA_DIFF})
    assert main.pending_card is None
    assert main.last_instruction is None


def test_agreement_alarm_creates_content_card(monkeypatch):
    _reset_state()
    # Identical texts: the slot diff sees no mismatch, but Jev says the
    # paraphrase does not agree -> a 内容 card with the full texts.
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=0.9, agreement_p=0.1))
    client.post("/captions", json={"speaker": "佐藤", "text": INSTR})
    client.post("/captions", json={"speaker": "田中", "text": INSTR})
    assert main.pending_card is not None
    assert main.pending_card["slot"] == "内容"
    assert main.pending_card["original"] == INSTR
    assert main.pending_card["heard"] == INSTR


def test_no_card_when_jev_agrees(monkeypatch):
    _reset_state()
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=0.9, agreement_p=0.95))
    client.post("/captions", json={"speaker": "佐藤", "text": INSTR})
    client.post("/captions", json={"speaker": "田中", "text": INSTR})
    assert main.pending_card is None


def test_fail_open_to_rules_when_jev_unavailable(monkeypatch):
    _reset_state()
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=None, agreement_p=None))
    client.post("/captions", json={"speaker": "佐藤", "text": INSTR})
    client.post("/captions", json={"speaker": "田中", "text": PARA_DIFF})
    assert main.pending_card is not None
    assert main.pending_card["slot"] == "期限"
    assert main.pending_card["original"] == "木曜日"
    assert main.pending_card["heard"] == "金曜日"


def test_is_instruction_like_thresholds(monkeypatch):
    empty = {"deadline": None, "quantity": None, "task": None, "destination": None}
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=0.95))
    assert main._is_instruction_like("お願いします", empty) is True
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=0.5))
    assert main._is_instruction_like("お願いします", empty) is False
    monkeypatch.setattr(main, "judge", FakeJudge(instruction_p=None))
    assert main._is_instruction_like("お願いします", empty) is False
