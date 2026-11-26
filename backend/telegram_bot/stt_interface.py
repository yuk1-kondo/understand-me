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


class WhisperFileSTTProvider:
    """Real STT: faster-whisper (local, CPU int8) on the audio file.

    Telegram voice notes arrive as .ogg/Opus files; faster-whisper decodes
    them via PyAV, so no format conversion is needed. Model from
    WHISPER_MODEL (default ``large-v3-turbo``), loaded lazily once and
    reused. The blocking transcribe runs in a worker thread.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or os.environ.get("WHISPER_MODEL", "large-v3-turbo")
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
        return self._model

    def _transcribe_sync(self, audio_path: str) -> str:
        # UM_STT_LANGUAGE: 'ja' (default), 'en', or 'auto' (Whisper detects).
        lang = os.environ.get("UM_STT_LANGUAGE", "ja").strip().lower()
        language = None if lang in ("auto", "") else lang
        segments, _info = self._load().transcribe(
            audio_path, language=language, beam_size=1
        )
        return "".join(seg.text for seg in segments).strip()

    async def transcribe(self, audio_path: str) -> str:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio_path)


class UnconfiguredSTTProvider:
    """Placeholder for the real provider. Fails loudly instead of
    silently returning wrong text."""

    async def transcribe(self, audio_path: str) -> str:
        raise NotImplementedError(
            "No STT provider configured. Set STT_PROVIDER=fake for "
            "testing, or implement a real provider in stt_interface.py."
        )


# Providers are cached per name: get_stt_provider() is called on every
# voice note, and WhisperFileSTTProvider holds a multi-GB model that must
# not reload per message.
_PROVIDERS: dict[str, STTProvider] = {}


def get_stt_provider() -> STTProvider:
    name = os.environ.get("STT_PROVIDER", "fake").lower()
    if name not in _PROVIDERS:
        if name == "fake":
            _PROVIDERS[name] = FakeSTTProvider()
        elif name == "whisper":
            _PROVIDERS[name] = WhisperFileSTTProvider()
        elif name == "real":
            _PROVIDERS[name] = UnconfiguredSTTProvider()
        else:
            raise ValueError(f"Unknown STT_PROVIDER: {name!r} (expected 'fake', 'whisper' or 'real')")
    return _PROVIDERS[name]
