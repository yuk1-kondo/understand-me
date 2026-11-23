"""Auto-checksum session-state tests.

Regression: last_instruction used to survive forever once set, so a
paraphrasing speaker could never become the instructor — every later
instruction-like utterance of theirs was diffed against the stale
original instead of starting a new comparison.
"""

from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)

INSTR_X = "木曜日までに資料を3部、教務部へ提出してください"
PARA_X = "金曜日までに資料を3部、教務部へ提出します"
INSTR_Y = "月曜日までに報告書を2部、総務部へ提出してください"
PARA_Y = "火曜日までに報告書を2部、総務部へ提出します"


def _reset_state() -> None:
    main.last_instruction = None
    main.pending_card = None


def test_paraphraser_can_instruct_after_mismatch_is_consumed():
    _reset_state()

    # A instructs, B paraphrases with the wrong day -> card appears.
    client.post("/captions", json={"speaker": "佐藤", "text": INSTR_X})
    client.post("/captions", json={"speaker": "田中", "text": PARA_X})
    card = client.get("/checksum/latest").json()
    assert card is not None and card["original"] == "木曜日"
    client.post("/checksum/respond", json={"id": card["id"], "action": "confirm"})

    # Now B issues her own instruction and A paraphrases it wrongly.
    # The new card must diff Y against Y' — not against A's stale X.
    client.post("/captions", json={"speaker": "田中", "text": INSTR_Y})
    client.post("/captions", json={"speaker": "佐藤", "text": PARA_Y})
    card = client.get("/checksum/latest").json()
    assert card is not None
    assert card["slot"] == "期限"
    assert card["original"] == "月曜日"
    assert card["heard"] == "火曜日"
