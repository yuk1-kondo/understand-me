"""Speech-to-text interface.

The core service itself never touches audio — STT lives in the input
tiers (working faster-whisper providers are in backend/discord_bot and
backend/telegram_bot, selected with STT_PROVIDER=whisper). This module
keeps the shared interface plus the canned-text fake used by tests:

- `transcribe()` is the production entry point and raises
  NotImplementedError so a missing provider fails loudly, never silently.
- `FakeSTT` / `fake_transcribe()` return fixed text so the rest of the
  pipeline (captions -> checksum) can be built and tested today.
"""

from __future__ import annotations

import os
from typing import Protocol

DEFAULT_FAKE_TEXT = "木曜日までに資料を3部、教務部へ提出してください"


class SpeechToText(Protocol):
    """Interface every STT provider must implement."""

    def transcribe(self, audio_bytes: bytes) -> str:
        ...


class UnconfiguredSTT:
    """Placeholder provider used until a real STT backend is wired up."""

    def transcribe(self, audio_bytes: bytes) -> str:
        raise NotImplementedError(
            "No speech-to-text provider is configured yet. "
            "Set STT_PROVIDER=fake for development, or implement a real "
            "provider (see stt.py) and select it via STT_PROVIDER."
        )


class FakeSTT:
    """Returns a fixed sentence regardless of the audio — for testing."""

    def __init__(self, text: str = DEFAULT_FAKE_TEXT) -> None:
        self._text = text

    def transcribe(self, audio_bytes: bytes) -> str:
        if not audio_bytes:
            return ""
        return self._text


def get_stt() -> SpeechToText:
    """Return the STT provider selected by the STT_PROVIDER env var."""
    provider = os.environ.get("STT_PROVIDER", "").lower()
    if provider == "fake":
        return FakeSTT()
    if provider in ("", "stub"):
        return UnconfiguredSTT()
    raise ValueError(
        f"Unknown STT_PROVIDER: {provider!r} (expected 'fake' or 'stub'; "
        "the working 'whisper' providers live in backend/discord_bot "
        "and backend/telegram_bot)"
    )


def transcribe(audio_bytes: bytes) -> str:
    """Transcribe audio with the configured provider.

    Raises NotImplementedError until a provider is configured.
    """
    return get_stt().transcribe(audio_bytes)


def fake_transcribe(audio_bytes: bytes) -> str:
    """Always-available fake transcription for tests and demos."""
    return FakeSTT().transcribe(audio_bytes)
