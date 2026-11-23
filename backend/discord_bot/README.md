# Discord voice receiver

Joins a Discord voice channel, receives speakers' audio (DAVE-decrypted
PCM), transcribes each utterance, and posts captions to the backend:

```
POST {BACKEND_URL}/captions   {"speaker": "...", "text": "..."}
```

The bot token is **pluggable**: it is read from the `DISCORD_BOT_TOKEN`
environment variable at startup. It is never written into code, logs, or
this repository — it lives in the Secure Vault.

## Files

| File | Role |
|---|---|
| `receiver.py` | The bot: voice receive → per-speaker segmentation → STT → caption POST |
| `stt_interface.py` | STT behind an interface (`SpeechToText`), with a fake (canned Japanese) and a stub for the real provider |
| `mock_receiver.py` | Token-free stand-in: posts a scripted two-speaker Japanese conversation into the same `/captions` path |

## Setup

```bash
cd backend/discord_bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Dependencies are pinned to what actually works after Discord made DAVE
(E2EE) mandatory on 2026-03-02: `discord.py[voice]>=2.7.1`, the
`davey` crypto bindings, and `discord-ext-voice-recv` from the
**unmerged PR #54** — the stable release cannot decrypt DAVE packets.
See `docs/DISCORD_SPIKE.md` in the repo root docs for sources.

Environment (see the repo-root `.env.example`):

```bash
export DISCORD_BOT_TOKEN=...      # from the Secure Vault, at run time only
export DISCORD_CHANNEL_ID=...     # numeric ID of the test voice channel
export BACKEND_URL=http://localhost:8000
export STT_PROVIDER=fake          # 'fake' (default) or 'stub'
```

## Run the real receiver

```bash
python receiver.py
```

Invite the bot to your own test server only, and run spikes only where
everyone in the channel has agreed to be transcribed.

## Run the mock (no token needed)

```bash
python mock_receiver.py               # posts the script, 3 s apart
python mock_receiver.py --dry-run     # just print the payloads
python mock_receiver.py --interval 1 --loop
```

The script is a two-speaker conversation （佐藤/田中） that includes the
checksum test instruction: 「木曜日までに3部、教務部へ提出」.

## Known pitfalls (learned from published field reports)

1. **`self_deaf=False` is mandatory.** `connect()` defaults to
   `self_deaf=True`, and a deafened bot is sent *no audio packets at
   all* — the bot joins, looks healthy, and hears nothing.
2. **Wait for the DAVE handshake before listening.** Packets processed
   before the session has keys cannot be decrypted. `receiver.py`
   polls for session readiness before calling `listen()`.
3. **Take PCM, not Opus.** The sink's `wants_opus()` returns `False`
   so the library does DAVE decrypt + Opus decode internally. Raw
   frames are still encrypted and fail with
   `OpusError: corrupted stream`.
4. **Pin PR #54.** The DAVE receive support is not in any release;
   "just upgrade the library" does not work yet.
5. **Never let a bad packet kill the loop.** All sink callbacks are
   wrapped defensively; bad packets are logged and skipped.
6. **py-cord does not support DAVE** (connections are refused with
   close 4017). Use discord.py.
