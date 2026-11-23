"""Speech-to-text interface for the Telegram tier.

The bot never talks to an STT provider directly; it goes through this
module so the provider can be swapped without touching bot.py.

Providers:
- FakeSTTProvider: returns a fixed Japanese instruction. Used for local
  testing and the simulator demo, where no microphone audio exists.
- UnconfiguredSTTProvider: the production stub. Raises until a real
  provider (Whisper API, Gemini, local whisper, ...) is wired in.

Select with the STT_PROVIDER env var: "fake" (default) or "real".
"""

from __future__ import annotations

import os
from typing import Protocol


# Fixed sample used by the fake provider. It intentionally contains the
# four checksum slots (deadline / quantity / task / destination) and is
# the canonical test case for the checksum flow:
# a Thursday-vs-Friday style misunderstanding can be rehearsed by
# replying with a corrected version of this sentence.
FAKE_TRANSCRIPT = "木曜日までに資料を3部、教務部へ提出してください"


class STTProvider(Protocol):
    """Anything that turns an audio file into Japanese text."""

    async def transcribe(self, audio_path: str) -> str:
        ...


class FakeSTTProvider:
    """Returns FAKE_TRANSCRIPT regardless of the audio content."""

    async def transcribe(self, audio_path: str) -> str:
        return FAKE_TRANSCRIPT


class UnconfiguredSTTProvider:
    """Placeholder for the real provider. Fails loudly instead of
    silently returning wrong text."""

    async def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError(
            "No STT provider configured. Set STT_PROVIDER=fake for "
            "testing, or implement a real provider in stt_interface.py."
        )


def get_stt_provider() -> STTProvider:
    name = os.environ.get("STT_PROVIDER", "fake").lower()
    if name == "fake":
        return FakeSTTProvider()
    if name == "real":
        return UnconfiguredSTTProvider()
    raise ValueError(f"Unknown STT_PROVIDER: {name!r} (expected 'fake' or 'real')")
