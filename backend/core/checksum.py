"""Checksum engine: extract the key slots of an instruction and diff them.

Slots: deadline / quantity / task / destination.

The extractor sits behind a small interface (`SlotExtractor`) so the
rule-based implementation below can later be swapped for a Claude-based
one without touching the API layer. The rule-based extractor works fully
offline — no API key required.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional, Protocol

SLOT_NAMES = ("deadline", "quantity", "task", "destination")


@dataclass
class Slots:
    deadline: Optional[str] = None
    quantity: Optional[str] = None
    task: Optional[str] = None
    destination: Optional[str] = None

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in SLOT_NAMES}


class SlotExtractor(Protocol):
    """Interface every slot extractor must implement."""

    def extract(self, text: str) -> Slots:
        ...


# --------------------------------------------------------------------------
# Rule-based extractor (Japanese)
# --------------------------------------------------------------------------

_WEEKDAY_CHARS = "月火水木金土日"

_KANJI_NUMBERS = {
    "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

# Order matters: specific patterns first.
_DEADLINE_PATTERNS = [
    re.compile(r"\d{1,2}月\d{1,2}日"),                       # 11月24日
    re.compile(rf"([{_WEEKDAY_CHARS}])曜日"),                # 木曜日
    re.compile(rf"([{_WEEKDAY_CHARS}])曜(?!日)"),            # 木曜
    re.compile(r"(明後日|あさって|明日|今日|今週|来週|月末|週末)"),
]

# Units: セット is multi-char, the rest are single-char counters.
_QUANTITY_RE = re.compile(
    r"(\d+|[一二三四五六七八九十]+)\s*(セット|[部個枚本件冊人名箱台回])"
)

# Destinations: "<org-like noun>へ" (教務部へ), or "<noun>へ提出/届け…".
_DESTINATION_RES = [
    re.compile(r"([一-龯ァ-ヶA-Za-z0-9]+(?:部|課|室|係|科|局|店|社|校|館|センター|窓口))へ"),
    re.compile(r"([一-龯ァ-ヶA-Za-z0-9]+)へ(?=提出|届け|持っ|送|渡)"),
]

# Polite / sentence-ending filler stripped when isolating the task phrase.
_TASK_FILLER_RE = re.compile(
    r"(してください|して下さい|お願いします|お願いいたします|ください|下さい|します|する|です|。|、|\s)+$"
)


def _normalize_number(raw: str) -> str:
    """'3' -> '3', '三' -> '3', '十二' -> '12', '二十' -> '20'."""
    if raw.isdigit():
        return str(int(raw))
    if "十" in raw:
        left, _, right = raw.partition("十")
        tens = _KANJI_NUMBERS.get(left, 1) if left else 1
        ones = _KANJI_NUMBERS.get(right, 0) if right else 0
        return str(tens * 10 + ones)
    return str(_KANJI_NUMBERS.get(raw, raw))


class RuleBasedExtractor:
    """Regex-based slot extraction for Japanese instruction sentences."""

    def extract(self, text: str) -> Slots:
        return Slots(
            deadline=self._deadline(text),
            quantity=self._quantity(text),
            task=self._task(text),
            destination=self._destination(text),
        )

    # -- individual slots -------------------------------------------------

    def _deadline(self, text: str) -> Optional[str]:
        for pattern in _DEADLINE_PATTERNS:
            m = pattern.search(text)
            if m:
                if m.lastindex:  # weekday char captured -> normalize to 木曜日 form
                    return f"{m.group(1)}曜日"
                return m.group(0)
        return None

    def _quantity(self, text: str) -> Optional[str]:
        m = _QUANTITY_RE.search(text)
        if not m:
            return None
        return f"{_normalize_number(m.group(1))}{m.group(2)}"

    def _destination(self, text: str) -> Optional[str]:
        for pattern in _DESTINATION_RES:
            m = pattern.search(text)
            if m:
                return m.group(1)
        return None

    def _task(self, text: str) -> Optional[str]:
        """Whatever remains after removing the other slots is the task core.

        Both sides of a comparison go through the exact same stripping, so
        leftover particles affect original and paraphrase identically.
        """
        rest = text
        # Remove the deadline token (the first pattern that matches, exactly
        # as _deadline() picks it). Both destination patterns also consume
        # the trailing へ, so a plain sub removes the whole span.
        for pattern in _DEADLINE_PATTERNS:
            if pattern.search(rest):
                rest = pattern.sub("", rest, count=1)
                break
        rest = _QUANTITY_RE.sub("", rest, count=1)
        for pattern in _DESTINATION_RES:
            if pattern.search(rest):
                rest = pattern.sub("", rest, count=1)
                break
        rest = re.sub(r"(までに|まで|に|、|。)", "", rest)
        rest = _TASK_FILLER_RE.sub("", rest.strip())
        rest = re.sub(r"\s+", "", rest).strip(" 、。")
        return rest or None


def get_extractor() -> SlotExtractor:
    """Return the configured slot extractor.

    Today this is always the rule-based extractor, which needs no API key.
    A Claude-based extractor can be dropped in here later (selected when
    ANTHROPIC_API_KEY is set) without changing callers.
    """
    _ = os.environ.get("ANTHROPIC_API_KEY")  # reserved for the Claude extractor
    return RuleBasedExtractor()


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def compare(
    original_text: str,
    paraphrase_text: str,
    extractor: Optional[SlotExtractor] = None,
) -> list[dict]:
    """Extract slots from both texts and return a list of differences.

    Each diff is {"slot": name, "original": value, "paraphrase": value}.
    An empty list means the paraphrase matches the original on every slot.
    """
    extractor = extractor or get_extractor()
    original = extractor.extract(original_text).as_dict()
    paraphrase = extractor.extract(paraphrase_text).as_dict()
    diffs = []
    for name in SLOT_NAMES:
        if original[name] != paraphrase[name]:
            diffs.append(
                {
                    "slot": name,
                    "original": original[name],
                    "paraphrase": paraphrase[name],
                }
            )
    return diffs
