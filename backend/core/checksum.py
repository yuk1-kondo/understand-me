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


# --------------------------------------------------------------------------
# Rule-based extractor (English)
# --------------------------------------------------------------------------

_WEEKDAY_EN_RE = re.compile(
    r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
    re.IGNORECASE,
)
_MONTH_EN = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_DATE_EN_RE = re.compile(
    rf"\b(?:{_MONTH_EN})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b", re.IGNORECASE
)
_TIME_EN_RE = re.compile(
    r"\b\d{1,2}(?::\d{2})?\s*(?:a\.m\.|p\.m\.|am|pm)\b", re.IGNORECASE
)
_RELATIVE_EN_RE = re.compile(
    r"\b(tomorrow|today|tonight|next week|this week|"
    r"end of (?:the )?(?:week|month))\b",
    re.IGNORECASE,
)

_NUMBER_WORDS_EN = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20,
}
_QUANTITY_EN_RE = re.compile(
    r"\b(\d+|" + "|".join(_NUMBER_WORDS_EN) + r")\s+"
    r"(copies|pages|items|sets|boxes|files|sheets|units|pcs)\b",
    re.IGNORECASE,
)

_DESTINATION_EN_RE = re.compile(
    r"\bto the ([\w' -]+? (?:office|department|room|team|desk|school|"
    r"library|reception)|front desk)\b",
    re.IGNORECASE,
)

# Leading politeness / pronoun filler stripped when isolating the task.
_TASK_FILLER_EN_RE = re.compile(
    r"^(please|okay|ok|so|well|i'll|i will|i|we|you|let's)\b[\s,]*",
    re.IGNORECASE,
)


class EnglishExtractor:
    """Regex-based slot extraction for English instruction sentences."""

    def extract(self, text: str) -> Slots:
        return Slots(
            deadline=self._deadline(text),
            quantity=self._quantity(text),
            task=self._task(text),
            destination=self._destination(text),
        )

    # -- individual slots -------------------------------------------------

    def _deadline(self, text: str) -> Optional[str]:
        parts = []
        m = _DATE_EN_RE.search(text)
        if m:
            parts.append(" ".join(m.group(0).split()).title())
        else:
            m = _WEEKDAY_EN_RE.search(text)
            if m:
                parts.append(m.group(1).capitalize())
            else:
                m = _RELATIVE_EN_RE.search(text)
                if m:
                    parts.append(" ".join(m.group(1).lower().split()))
        t = _TIME_EN_RE.search(text)
        if t:
            parts.append(re.sub(r"\.", "", t.group(0)).upper().replace(" ", ""))
        return " ".join(parts) or None

    def _quantity(self, text: str) -> Optional[str]:
        m = _QUANTITY_EN_RE.search(text)
        if not m:
            return None
        raw = m.group(1).lower()
        number = int(raw) if raw.isdigit() else _NUMBER_WORDS_EN[raw]
        return f"{number} {m.group(2).lower()}"

    def _destination(self, text: str) -> Optional[str]:
        m = _DESTINATION_EN_RE.search(text)
        if not m:
            return None
        return "the " + " ".join(m.group(1).lower().split())

    def _task(self, text: str) -> Optional[str]:
        """Whatever remains after removing the other slots is the task core.

        Both sides of a comparison go through the exact same stripping, so
        leftover words affect original and paraphrase identically.
        """
        rest = text
        for pattern in (
            _DATE_EN_RE,
            _WEEKDAY_EN_RE,
            _RELATIVE_EN_RE,
            _TIME_EN_RE,
            _QUANTITY_EN_RE,
            _DESTINATION_EN_RE,
        ):
            rest = pattern.sub("", rest, count=1)
        rest = re.sub(r"\b(by|on|at|before)\b", "", rest, flags=re.IGNORECASE)
        rest = rest.strip(" .,")
        for _ in range(2):  # e.g. "Okay, please ..." / "I'll ..."
            rest = _TASK_FILLER_EN_RE.sub("", rest)
        rest = re.sub(r"\s+", " ", rest).strip(" .,")
        return rest or None


# --------------------------------------------------------------------------
# Bilingual routing
# --------------------------------------------------------------------------

_JAPANESE_RE = re.compile(r"[぀-ヿ一-鿿]")


def looks_japanese(text: str) -> bool:
    """True when the text contains any kana or kanji."""
    return bool(_JAPANESE_RE.search(text))


class BilingualExtractor:
    """Routes each text to the Japanese or English rule-based extractor."""

    def __init__(self) -> None:
        self._ja = RuleBasedExtractor()
        self._en = EnglishExtractor()

    def extract(self, text: str) -> Slots:
        if looks_japanese(text):
            return self._ja.extract(text)
        return self._en.extract(text)


def get_extractor() -> SlotExtractor:
    """Return the configured slot extractor.

    Today this is the bilingual rule-based extractor, which needs no API
    key. A Claude-based extractor can be dropped in here later (selected
    when ANTHROPIC_API_KEY is set) without changing callers.
    """
    _ = os.environ.get("ANTHROPIC_API_KEY")  # reserved for the Claude extractor
    return BilingualExtractor()


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
