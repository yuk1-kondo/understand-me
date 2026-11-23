"""Checksum engine tests.

The canonical case: an instruction says 木曜日 (Thursday) but the wearer's
paraphrase says 金曜日 (Friday) — that mismatch must be caught.
"""

from checksum import RuleBasedExtractor, compare

ORIGINAL = "木曜日までに資料を3部、教務部へ提出してください"

extractor = RuleBasedExtractor()


def diffs_by_slot(original: str, paraphrase: str) -> dict:
    return {d["slot"]: d for d in compare(original, paraphrase, extractor)}


def test_extract_slots():
    slots = extractor.extract(ORIGINAL)
    assert slots.deadline == "木曜日"
    assert slots.quantity == "3部"
    assert slots.destination == "教務部"
    assert slots.task is not None and "提出" in slots.task


def test_weekday_mismatch_detected():
    paraphrase = "金曜日までに資料を3部、教務部へ提出します"
    diffs = diffs_by_slot(ORIGINAL, paraphrase)
    assert "deadline" in diffs
    assert diffs["deadline"]["original"] == "木曜日"
    assert diffs["deadline"]["paraphrase"] == "金曜日"


def test_quantity_mismatch_detected():
    paraphrase = "木曜日までに資料を2部、教務部へ提出します"
    diffs = diffs_by_slot(ORIGINAL, paraphrase)
    assert "quantity" in diffs
    assert diffs["quantity"]["original"] == "3部"
    assert diffs["quantity"]["paraphrase"] == "2部"


def test_kanji_quantity_matches_arabic():
    # 三部 and 3部 are the same quantity — no diff expected.
    paraphrase = "木曜日までに資料を三部、教務部へ提出します"
    assert diffs_by_slot(ORIGINAL, paraphrase) == {}


def test_identical_instructions_produce_zero_diffs():
    assert compare(ORIGINAL, ORIGINAL, extractor) == []


def test_equivalent_paraphrase_produces_zero_diffs():
    paraphrase = "木曜日までに資料を3部、教務部へ提出します"
    assert compare(ORIGINAL, paraphrase, extractor) == []
