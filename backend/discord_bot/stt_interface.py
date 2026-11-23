"""Speech-to-text behind an interface.

The Discord receiver only knows this interface; the concrete provider
(real STT API, local Whisper, ...) can be swapped without touching the
receive pipeline. Two non-provider implementations ship here:

- ``FakeSpeechToText`` — deterministic canned Japanese phrases. Lets the
  whole caption pipeline run end-to-end with zero external accounts.
- ``StubSpeechToText`` — placeholder for the real provider. Raises until
  someone implements ``transcribe`` against an actual STT service.

Select with the STT_PROVIDER environment variable ("fake" by default).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class SpeechToText(ABC):
    """Transcribe one utterance of PCM audio to text."""

    @abstractmethod
    def transcribe(self, pcm: bytes, sample_rate: int, channels: int, speaker: str) -> str:
        """Return the transcript for a single segmented utterance.

        ``pcm`` is signed 16-bit little-endian PCM as delivered by
        discord-ext-voice-recv after DAVE decryption + Opus decoding
        (48 kHz stereo from Discord).
        """
        raise NotImplementedError


class FakeSpeechToText(SpeechToText):
    """Canned transcripts for development and demos without a real STT.

    Cycles through a fixed script of Japanese utterances so downstream
    components (caption queue, checksum slot extraction) see realistic
    text, including an instruction whose deadline is 木曜日.
    """

    SCRIPT = [
        "こんばんは、聞こえていますか。",
        "今週の資料なんだけど、木曜日までに3部、教務部へ提出をお願いできますか。",
        "金曜の夜はいつものゲーム、21時からだよ。",
        "提出先は教務部、部数は3部でお願いします。",
        "ありがとう、助かります。",
    ]

    def __init__(self) -> None:
        self._index = 0

    def transcribe(self, pcm: bytes, sample_rate: int, channels: int, speaker: str) -> str:
        text = self.SCRIPT[self._index % len(self.SCRIPT)]
        self._index += 1
        return text


class StubSpeechToText(SpeechToText):
    """Placeholder for the real STT provider — not yet implemented."""

    def transcribe(self, pcm: bytes, sample_rate: int, channels: int, speaker: str) -> str:
        raise NotImplementedError(
            "Real STT provider not wired up yet. "
            "Implement this method or set STT_PROVIDER=fake."
        )


def get_stt() -> SpeechToText:
    """Build the STT implementation selected by STT_PROVIDER."""
    provider = os.environ.get("STT_PROVIDER", "fake").lower()
    if provider == "fake":
        return FakeSpeechToText()
    if provider == "stub":
        return StubSpeechToText()
    raise ValueError(f"Unknown STT_PROVIDER: {provider!r} (expected 'fake' or 'stub')")
