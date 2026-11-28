# Understand Me

**Hearing what was said is not the same as understanding it correctly.**

Understand Me is an Even G2 app for listeners who are deaf or hard of hearing. It shows speaker-labelled captions from Discord voice channels and Telegram voice messages on the glasses — and then goes one step further: when an instruction is given, the app extracts its key points (deadline, quantity, task, destination), asks the wearer to confirm them, and sends the confirmed understanding back to the speaker. A "checksum" for human conversation.

- **Track:** 01 — Messaging & News (Discord / Telegram)
- **Built for:** Heads Up: Even Realities Hackathon (build week Nov 23–29, 2026)
- **Runs on:** Even Hub simulator (no G2 hardware required to try it)

## The problem

Live captions solved "can I read what was said?" They did not solve "did I understand it the way the speaker meant?" A misheard deadline — Thursday vs. Friday — is invisible until it becomes a missed delivery. Understand Me closes that gap with a teach-back loop on the glasses:

1. **Read** — captions from the voice conversation appear on the lens.
2. **Check** — the app extracts the instruction's key slots and shows only what needs confirming.
3. **Write** — the confirmed (or corrected) version goes back to the chat, so both sides share the same understanding.

## How it works

- `evenhub/` — the real Even Hub app (verified in the official simulator): caption view + checksum card built from SDK text/list containers
- `app/` — browser fallback demo of the same UI (no build, dummy data when the backend is down)
- `backend/core/` — FastAPI caption queue (REST + WebSocket) and the rule-based checksum engine (slot extraction → diff → pending card), with tests
- `backend/discord_bot/` — joins a Discord voice channel, receives DAVE-decrypted audio (discord-ext-voice-recv), segments per speaker, transcribes locally with faster-whisper, posts captions
- `backend/telegram_bot/` — Telegram voice-message tier running the same checksum loop
- `scripts/display_check.py` — local end-to-end display regression check (build → backend → simulator → framebuffer assertions; see `docs/DISPLAY_CHECK.md`)

Slot extraction and comparison are rule-based and run offline; an optional Jev (TypeSafe AI) layer adds instruction/agreement judgments when `TYPESAFE_API_KEY` is set. The only external services integrated are Discord and Telegram, per Track 01.

## Setup

Backend (no API keys needed — extraction is rule-based):

```bash
cd backend/core && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000
pytest            # 43 tests
```

Even Hub app + simulator (needs `evenhub-simulator` + `evenhub` CLI from
`@evenrealities/*` npm packages, and the display-check ports free):

```bash
cd evenhub && npm install && npm run build
(cd dist && python3 -m http.server 5173 &)
evenhub-simulator http://localhost:5173 --automation-port 9898
python3 ../scripts/display_check.py   # full local regression check → PASS
```

Input tiers (tokens via env vars only — see `.env.example`; never commit `.env`):

- Discord: `backend/discord_bot/` — `pip install -r requirements.txt` (pins
  `davey>=0.1,<0.2` and the rdphillips7 voice-recv fork; see
  `docs/DISCORD_SPIKE.md` for why), then `DISCORD_BOT_TOKEN=... DISCORD_CHANNEL_ID=... STT_PROVIDER=whisper python receiver.py`. `mock_receiver.py` demos the caption path with no token.
- Telegram: `backend/telegram_bot/` — `TELEGRAM_BOT_TOKEN=... STT_PROVIDER=whisper python bot.py`.

STT is real: `STT_PROVIDER=whisper` runs faster-whisper `large-v3-turbo`
locally on both bots (`WHISPER_MODEL` overrides; `STT_PROVIDER=fake` gives
canned text for demos).

CI: `.github/workflows/ci.yml` runs the backend tests and the evenhub
build on every push. The glasses framebuffer check stays local — it needs
the macOS simulator.

## Demo

[Watch the demo video (2:55)](https://drive.google.com/file/d/1Q4iYqp7DYJVn_S2JINTgdIB9rUzA-iz9/view?usp=drivesdk) — real Discord voice through the Even Hub simulator, a Telegram voice-message cut, and English narration. The conversation is in Japanese (the app is bilingual); the glasses UI is shown in English.

## What existed before the official build start (hackathon declaration)

Per the hackathon rules, this section declares everything that existed before the official build start (Nov 23, 2026, 17:00 JST).

Prepared before Nov 23:
- Market / prior-art research on Even G2 apps (internal notes, not part of this repo)
- The product concept and MVP plan for Understand Me (ideation documents)
- This repository skeleton: directory layout and this README outline
- A documented recipe for receiving Discord voice audio after DAVE encryption, assembled from public sources (see `docs/DISCORD_SPIKE.md`)

Created on Nov 23 before 17:00 JST (declared honestly as pre-start work):
- Backend core: caption queue API (REST + WebSocket), rule-based checksum engine (slot extraction and diff), STT interface — with passing tests
- Discord voice receiver written to the public DAVE recipe (token-pluggable; not yet connected to Discord) plus a mock receiver for token-free demos
- Telegram bot tier (voice message → transcript → checksum → confirm/correct flow; not yet connected)
- Glasses-app front-end scaffold (caption view + checksum card, 576×288, with built-in dummy data)

Everything not listed above was created during the build week (Nov 23–29, 2026).

## License

MIT
