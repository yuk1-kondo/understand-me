"""English extraction + bilingual routing tests.

The hackathon jury is international, so the checksum engine must work on
English instructions too: the bilingual extractor routes by script, and
card labels follow the language of the original instruction.
"""

from fastapi.testclient import TestClient

import main
from checksum import EnglishExtractor, compare, get_extractor, looks_japanese
from main import app

client = TestClient(app)

INSTR_EN = "Please submit 3 copies of the report to the academic office by Thursday."
PARA_EN = "I'll submit 3 copies of the report to the academic office by Friday."


def test_english_slots():
    slots = EnglishExtractor().extract(INSTR_EN)
    assert slots.deadline == "Thursday"
    assert slots.quantity == "3 copies"
    assert slots.destination == "the academic office"
    assert slots.task is not None and "report" in slots.task


def test_english_number_words_and_time():
    slots = EnglishExtractor().extract("Print twenty pages by Friday at 3 PM.")
    assert slots.quantity == "20 pages"
    assert slots.deadline == "Friday 3PM"


def test_english_date_and_front_desk():
    slots = EnglishExtractor().extract(
        "Send the files to the front desk by November 28."
    )
    assert slots.deadline == "November 28"
    assert slots.destination == "the front desk"


def test_english_compare_only_deadline_differs():
    diffs = compare(INSTR_EN, PARA_EN, extractor=EnglishExtractor())
    assert diffs == [
        {"slot": "deadline", "original": "Thursday", "paraphrase": "Friday"}
    ]


def test_bilingual_routing():
    assert looks_japanese("木曜日までに提出してください")
    assert not looks_japanese("Submit it by Thursday.")
    extractor = get_extractor()
    ja = extractor.extract("木曜日までに資料を3部、教務部へ提出してください")
    assert ja.deadline == "木曜日" and ja.quantity == "3部"
    en = extractor.extract(INSTR_EN)
    assert en.deadline == "Thursday" and en.quantity == "3 copies"


def _reset_state() -> None:
    main.last_instruction = None
    main.pending_card = None


def test_english_auto_checksum_card_uses_english_label():
    _reset_state()
    client.post("/captions", json={"speaker": "Smith", "text": INSTR_EN})
    client.post("/captions", json={"speaker": "Jones", "text": PARA_EN})
    card = client.get("/checksum/latest").json()
    assert card is not None
    assert card["slot"] == "Deadline"
    assert card["original"] == "Thursday"
    assert card["heard"] == "Friday"
