"""Optional Jev (TypeSafe AI System One) judgment layer for the checksum flow.

The rule-based extractor pulls slot VALUES (deadline / quantity /
destination / task) deterministically. Rules are bad at two judgments,
and those are exactly what Jev is for:

  1. ``is_instruction`` — is this utterance an instruction/request with a
     commitment, or chit-chat? Rules currently guess "any slot found",
     which misses pattern-less instructions ("金曜の朝イチで例の資料
     よろしく") and misfires on slot-ful small talk ("明日、映画を
     2本観た").
  2. ``agrees`` — do an instruction and its paraphrase agree on every
     commitment they mention? Catches mismatches the slot diff cannot
     see (e.g. both sides pattern-less).

The layer is OFF unless ``TYPESAFE_API_KEY`` is set. Every failure
(network, timeout, malformed response) returns ``None`` and callers fall
back to the pure rule-based behavior — fail-open by design, so the
pipeline never depends on the API being up.

Thresholds follow TypeSafe's own starting guidance for Noul questions:
act at >= 0.7, reject at < 0.3, and defer to the deterministic rules in
between.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx

# Probability thresholds (see module docstring).
INSTRUCTION_YES = 0.7  # at/above: treat as an instruction even without slots
INSTRUCTION_NO = 0.3  # below: treat as chit-chat even with slots
AGREEMENT_NO = 0.3  # below: the paraphrase disagrees with the instruction

_INSTRUCTION_QUESTION = {
    "type": "noul",
    "instructions": (
        "Does this Japanese utterance give an instruction, request, or "
        "assignment that includes a commitment such as a deadline, a "
        "quantity, a destination, or a task to complete?"
    ),
    "criteria": {
        "true": (
            "Assigns a task with at least one concrete commitment "
            "(when, how many, where to, or what to do)"
        ),
        "false": (
            "Casual conversation, a report of past events, a greeting, "
            "or small talk that assigns no task"
        ),
    },
}

_AGREEMENT_QUESTION = {
    "type": "noul",
    "instructions": (
        "Do the instruction and the paraphrase agree on every commitment "
        "they mention (deadline, quantity, destination, and task)?"
    ),
    "criteria": {
        "true": "Every mentioned commitment matches; nothing is changed, added, or dropped",
        "false": "At least one commitment differs, is missing, or is added",
    },
}


class JevJudge:
    """Thin client for the Jev System One API (Noul questions only)."""

    def __init__(self, api_key: str, client: Optional[httpx.Client] = None) -> None:
        self._api_key = api_key
        self._base = os.environ.get("TYPESAFE_API_BASE", "https://api.typesafe.ai/v1")
        self._model = os.environ.get("JEV_MODEL", "jev-latest")
        timeout = float(os.environ.get("JEV_TIMEOUT_SECONDS", "2.5"))
        self._client = client or httpx.Client(timeout=timeout)

    def _noul(self, state: str, question: dict) -> Optional[float]:
        """Ask one Noul question; return the Yes probability or None."""
        try:
            resp = self._client.post(
                f"{self._base}/systemone",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "state": state,
                    "questions": {"q": question},
                },
            )
            resp.raise_for_status()
            value = resp.json()["answers"]["q"]["noul"]
            return float(value)
        except Exception:
            return None

    def is_instruction(self, text: str) -> Optional[float]:
        """Probability that ``text`` is an instruction with a commitment."""
        return self._noul(text, _INSTRUCTION_QUESTION)

    def agrees(self, instruction_text: str, paraphrase_text: str) -> Optional[float]:
        """Probability that the paraphrase fully agrees with the instruction."""
        state = f"Instruction: {instruction_text}\nParaphrase: {paraphrase_text}"
        return self._noul(state, _AGREEMENT_QUESTION)


def get_judge() -> Optional[JevJudge]:
    """Return a JevJudge when TYPESAFE_API_KEY is set, else None (layer off)."""
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        return None
    return JevJudge(api_key)
