"""Understand Me — Discord voice receiver.

Joins a Discord voice channel as a bot, receives other speakers' audio
(DAVE-decrypted PCM via discord-ext-voice-recv), segments it per speaker
on silence, transcribes each utterance through the STT interface, and
posts captions to the backend caption queue:

    POST {BACKEND_URL}/captions   {"speaker": "...", "text": "..."}

The bot token is TOKEN-PLUGGABLE: it is read from the DISCORD_BOT_TOKEN
environment variable at startup and never appears in code. Everything
downstream of the audio sink can be developed and demoed without a token
via mock_receiver.py.

Known pitfalls this file is written around (see docs/DISCORD_SPIKE.md):
  * A deafened bot receives NO audio packets — connect with
    self_deaf=False. (The default self_deaf=True silently starves you.)
  * Do not start listening before the DAVE handshake completes; packets
    that arrive before the session is ready cannot be decrypted.
  * The sink must take PCM (wants_opus() -> False) so the library does
    DAVE decryption + Opus decoding internally. Raw Opus frames are
    still DAVE-encrypted and fail to decode 100% of the time.
  * A single bad packet must never kill the packet loop: every callback
    here is wrapped defensively and skips bad packets.

Run from this directory:
    DISCORD_BOT_TOKEN=... DISCORD_CHANNEL_ID=... python receiver.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from typing import Callable, Dict, Optional

import aiohttp
import discord
from discord.ext import voice_recv

# discord.py does not auto-find libopus on Apple Silicon Homebrew installs;
# without it every received packet dies with OpusNotLoaded. Load it explicitly
# from the standard locations before any decoder is created.
if not discord.opus.is_loaded():
    for _opus_path in ("/opt/homebrew/lib/libopus.0.dylib", "/usr/local/lib/libopus.0.dylib", "libopus.0.dylib"):
        try:
            discord.opus.load_opus(_opus_path)
            break
        except Exception:
            continue

from stt_interface import SpeechToText, get_stt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("understand-me.receiver")

# PCM format delivered by voice_recv after decoding: 48 kHz, stereo, s16le.
SAMPLE_RATE = 48000
CHANNELS = 2
BYTES_PER_SECOND = SAMPLE_RATE * CHANNELS * 2

# An utterance ends after this much silence, and is only transcribed if
# it carries at least MIN_UTTERANCE_SECONDS of audio (drops coughs/clicks).
SILENCE_GAP_SECONDS = 0.8
MIN_UTTERANCE_SECONDS = 0.4


class CaptionPoster:
    """Posts transcribed utterances to the backend caption queue.

    A dead backend must never take the receiver down with it: failures
    are logged and the caption is dropped.
    """

    def __init__(self, backend_url: str) -> None:
        self._url = backend_url.rstrip("/") + "/captions"
        self._session: Optional[aiohttp.ClientSession] = None

    async def post(self, speaker: str, text: str) -> None:
        try:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            async with self._session.post(self._url, json={"speaker": speaker, "text": text}) as resp:
                if resp.status >= 300:
                    log.warning("Caption POST %s -> HTTP %s", self._url, resp.status)
                else:
                    log.info("Caption posted: %s: %s", speaker, text)
        except Exception:
            log.exception("Caption POST failed (backend unreachable?); caption dropped")

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


class SpeakerSegmenter:
    """Accumulates PCM per speaker and flushes utterances on silence.

    feed() runs on the voice_recv packet thread while flush_idle() runs on
    the bot's event loop, so the shared buffers are guarded by a lock. The
    (slow) utterance callback always runs outside the lock.
    """

    def __init__(self, on_utterance: Callable[[str, bytes], None]) -> None:
        self._buffers: Dict[str, bytearray] = {}
        self._last_seen: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._on_utterance = on_utterance

    def feed(self, speaker: str, pcm: bytes) -> None:
        with self._lock:
            buf = self._buffers.setdefault(speaker, bytearray())
            buf.extend(pcm)
            self._last_seen[speaker] = time.monotonic()

    def flush_idle(self, now: Optional[float] = None) -> None:
        """Flush every speaker who has been silent past the gap."""
        now = time.monotonic() if now is None else now
        with self._lock:
            idle = [s for s, last in self._last_seen.items() if now - last >= SILENCE_GAP_SECONDS]
        for speaker in idle:
            self._flush(speaker)

    def flush_all(self) -> None:
        with self._lock:
            speakers = list(self._buffers)
        for speaker in speakers:
            self._flush(speaker)

    def _flush(self, speaker: str) -> None:
        with self._lock:
            pcm = bytes(self._buffers.pop(speaker, bytearray()))
            self._last_seen.pop(speaker, None)
        if len(pcm) < BYTES_PER_SECOND * MIN_UTTERANCE_SECONDS:
            return  # too short to be speech; drop quietly
        try:
            self._on_utterance(speaker, pcm)
        except Exception:
            log.exception("Utterance callback failed for speaker %s", speaker)


class CaptionSink(voice_recv.AudioSink):
    """voice_recv sink that consumes decoded PCM (never raw Opus)."""

    def __init__(self, segmenter: SpeakerSegmenter) -> None:
        super().__init__()
        self._segmenter = segmenter

    def wants_opus(self) -> bool:
        # False = the library runs the full pipeline for us:
        # UDP receive -> DAVE decrypt -> Opus decode -> PCM in write().
        # True would hand us DAVE-encrypted frames that cannot decode.
        return False

    def write(self, user, data) -> None:
        # Defensive by design: this runs inside the library's packet loop,
        # and one bad packet (or one unknown speaker) must not kill it.
        try:
            pcm = getattr(data, "pcm", None)
            if not pcm:
                return
            speaker = getattr(user, "display_name", None) or getattr(user, "name", None) or "unknown"
            self._segmenter.feed(str(speaker), pcm)
        except Exception:
            log.exception("Dropped a bad audio packet")

    def cleanup(self) -> None:
        try:
            self._segmenter.flush_all()
        except Exception:
            log.exception("Sink cleanup failed")


async def wait_for_dave_ready(vc: voice_recv.VoiceRecvClient, timeout: float = 15.0) -> bool:
    """Wait until the DAVE session is ready to decrypt, if one is exposed.

    Listening before the handshake finishes means trying to process
    encrypted packets without keys, so we poll the session defensively:
    attribute layout differs across discord.py / davey versions, and any
    probe failure is treated as "not ready yet", never as a crash.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = getattr(vc, "_connection", None) or getattr(vc, "connection", None)
            session = getattr(state, "dave_session", None) if state is not None else None
            if session is None:
                session = getattr(vc, "dave_session", None)
            if session is not None and getattr(session, "ready", False):
                log.info("DAVE session is ready")
                return True
            if session is None:
                # No DAVE session object exposed by this build; the send
                # path is DAVE-capable in discord.py >= 2.7, so settle
                # briefly and proceed rather than blocking forever.
                await asyncio.sleep(1.0)
                log.info("No DAVE session object exposed; proceeding after settle delay")
                return True
        except Exception:
            log.exception("DAVE readiness probe failed; retrying")
        await asyncio.sleep(0.25)
    log.warning("DAVE session not confirmed ready after %.0fs; listening anyway", timeout)
    return False


class ReceiverBot(discord.Client):
    def __init__(self, channel_id: int, poster: CaptionPoster, stt: SpeechToText) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True
        intents.guilds = True
        super().__init__(intents=intents)
        self._channel_id = channel_id
        self._poster = poster
        self._stt = stt
        self._segmenter = SpeakerSegmenter(self._handle_utterance)
        self._flusher: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _handle_utterance(self, speaker: str, pcm: bytes) -> None:
        """Segmenter callback (sync): transcribe, then post asynchronously."""
        # Debug: log the utterance's duration and peak/RMS level so silent or
        # near-silent captures (which make Whisper hallucinate) are visible.
        try:
            import struct

            samples = struct.unpack(f"<{len(pcm) // 2}h", pcm)
            if samples:
                peak = max(abs(s) for s in samples)
                rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                log.info(
                    "Utterance from %s: %.2fs peak=%d rms=%.0f",
                    speaker,
                    len(pcm) / BYTES_PER_SECOND,
                    peak,
                    rms,
                )
        except Exception:
            pass
        if os.environ.get("UM_DEBUG_DUMP"):
            try:
                import wave

                path = f"/tmp/utterance-{int(time.time())}.wav"
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(CHANNELS)
                    wf.setsampwidth(2)
                    wf.setframerate(SAMPLE_RATE)
                    wf.writeframes(pcm)
                log.info("Dumped utterance WAV: %s", path)
            except Exception:
                log.exception("WAV dump failed")
        # This callback may run on the event loop (silence flush) or on the
        # library's packet thread (sink cleanup). run_coroutine_threadsafe
        # is correct from both; get_running_loop() would raise off-loop and
        # drop the caption.
        loop = self._loop
        if loop is None:
            log.error("Event loop not ready; utterance from %s dropped", speaker)
            return
        asyncio.run_coroutine_threadsafe(self._process_utterance(speaker, pcm), loop)

    async def _process_utterance(self, speaker: str, pcm: bytes) -> None:
        """Transcribe off the event loop (Whisper blocks for seconds), then post."""
        try:
            text = await asyncio.to_thread(
                self._stt.transcribe, pcm, SAMPLE_RATE, CHANNELS, speaker
            )
        except Exception:
            log.exception("STT failed for speaker %s; utterance dropped", speaker)
            return
        if not text:
            return
        await self._poster.post(speaker, text)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            try:
                self._segmenter.flush_idle()
            except Exception:
                log.exception("Segmenter flush failed; continuing")

    async def on_ready(self) -> None:
        log.info("Logged in as %s", self.user)
        self._loop = asyncio.get_running_loop()
        channel = self.get_channel(self._channel_id)
        if channel is None:
            log.error("Channel %s not found (wrong ID, or bot not in that guild)", self._channel_id)
            await self.close()
            return
        # self_deaf=False is CRITICAL: a deafened bot is sent no audio at all.
        vc = await channel.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False)
        await wait_for_dave_ready(vc)
        vc.listen(CaptionSink(self._segmenter))
        self._flusher = asyncio.create_task(self._flush_loop())
        log.info("Listening in #%s — captions flowing to the backend queue", channel.name)

    async def close(self) -> None:
        if self._flusher is not None:
            self._flusher.cancel()
        await self._poster.close()
        await super().close()


def main() -> None:
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "DISCORD_BOT_TOKEN is not set. The token is pluggable by design: "
            "create the bot (see docs/USER_TASKS.md), store the token in the "
            "Secure Vault, and export it as DISCORD_BOT_TOKEN when running. "
            "Until then, use mock_receiver.py to demo the rest of the system."
        )
    channel_id = os.environ.get("DISCORD_CHANNEL_ID", "").strip()
    if not channel_id.isdigit():
        raise SystemExit("DISCORD_CHANNEL_ID must be set to the numeric voice channel ID.")
    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
    bot = ReceiverBot(int(channel_id), CaptionPoster(backend_url), get_stt())
    bot.run(token)


if __name__ == "__main__":
    main()
