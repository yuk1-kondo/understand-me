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


def _stt_language() -> str | None:
    """Recognition language from UM_STT_LANGUAGE.

    'ja' (default), 'en', or 'auto'/'' for Whisper auto-detection (None).
    """
    lang = os.environ.get("UM_STT_LANGUAGE", "ja").strip().lower()
    return None if lang in ("auto", "") else lang


def _stt_prompt() -> str | None:
    """Domain-vocabulary prompt matching the recognition language.

    UM_STT_PROMPT always wins when set. Auto-detection gets no prompt so
    it cannot bias the language choice.
    """
    override = os.environ.get("UM_STT_PROMPT")
    if override:
        return override
    lang = _stt_language()
    if lang is None:
        return None
    if lang.startswith("en"):
        return (
            "A school staff meeting. Academic office, staff room, reports, "
            "copies, submit, deadline, Thursday, students, classes, events."
        )
    return (
        "学校の会議での会話です。教務部、職員室、資料、部数、提出、"
        "期限、木曜日、生徒、授業、行事。"
    )


class WhisperLocalSpeechToText(SpeechToText):
    """Real STT: faster-whisper running locally (CPU, int8).

    Model from WHISPER_MODEL (default ``large-v3-turbo``). PCM arrives as
    48 kHz stereo s16le (post-DAVE decode); it is downmixed and decimated to
    the 16 kHz mono float32 Whisper expects. The model loads lazily on first
    use so importing this module stays cheap.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or os.environ.get("WHISPER_MODEL", "large-v3-turbo")
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, pcm: bytes, sample_rate: int, channels: int, speaker: str) -> str:
        import numpy as np

        audio = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype=np.int16).astype(np.float32) / 32768.0
        if channels > 1:
            usable = len(audio) // channels * channels
            audio = audio[:usable].reshape(-1, channels).mean(axis=1)
        if sample_rate != 16000:
            factor = sample_rate // 16000
            n = (len(audio) // factor) * factor
            audio = audio[:n].reshape(-1, factor).mean(axis=1)
        segments, _info = self._load().transcribe(
            audio,
            language=_stt_language(),
            beam_size=1,
            vad_filter=True,
            no_speech_threshold=0.6,
            condition_on_previous_text=False,
            temperature=0.0,
            initial_prompt=_stt_prompt(),
            without_timestamps=True,
        )
        return "".join(
            seg.text for seg in segments if seg.no_speech_prob < 0.6
        ).strip()


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
    if provider == "whisper":
        return WhisperLocalSpeechToText()
    if provider == "stub":
        return StubSpeechToText()
    raise ValueError(f"Unknown STT_PROVIDER: {provider!r} (expected 'fake', 'whisper' or 'stub')")
