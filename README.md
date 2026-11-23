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

```
Discord voice channel ── bot receives audio (DAVE-decrypted PCM)
                              │  speech-to-text
Telegram voice message ───────┤
                              ▼
                     backend/core (FastAPI)
                     caption queue ──► Even Hub app polls /captions
                     checksum engine: extract slots from the instruction,
                     compare with the listener's paraphrase,
                     mismatch ──► pending card at /checksum/latest
                              │
                              ▼
                     Even Hub app (evenhub/)
                     captions as text containers on the 576×288 canvas;
                     checksum card as a native list — tap to confirm
                     or send the corrected version back (POST /checksum/respond)
```

- `evenhub/` — the submitted Even Hub app (EvenAppBridge container UI, `.ehpk`)
- `app/` — the same UI as a plain browser demo (dummy data, no tooling needed)
- `backend/core/` — caption queue, checksum engine (rule-based slot extraction; a Claude extractor can be swapped in behind the same interface), STT interface
- `backend/discord_bot/` — joins a voice channel and receives audio (token-pluggable), plus a mock receiver for token-free demos
- `backend/telegram_bot/` — voice-message tier running the same checksum loop

Claude is used only as an internal AI component (slot extraction / comparison). The only external services integrated are Discord and Telegram, per Track 01.

## Setup

Prerequisites: Python 3.12, Node.js (for the Even Hub tooling).

1. Backend core:
   ```
   cd backend/core
   python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   .venv/bin/uvicorn main:app --port 8000
   ```
   Verify: `curl http://localhost:8000/health` → `{"status":"ok"}`. Tests: `.venv/bin/python -m pytest`.
2. Glasses app (simulator): see `evenhub/README.md` — in short, `npm install`, `npm run build`, `evenhub pack app.json dist -o understand-me.ehpk`, then load the `.ehpk` in the Even Hub simulator.
3. Discord tier (optional, needs your own bot): see `backend/discord_bot/README.md`. Tokens are read from environment variables only (see `.env.example`); never commit them.
4. Telegram tier (optional): see `backend/telegram_bot/README.md`.

Quick end-to-end check without any tokens: start the backend, run `backend/discord_bot/mock_receiver.py` to feed scripted captions, then post an instruction and a paraphrase as two speakers — the checksum card appears at `GET /checksum/latest`.

## Demo

Demo script: `docs/DEMO_SCRIPT.md`. Video: _to be added before submission (≤ 3 min, recorded in the Even Hub simulator)._

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
- Even Hub app package (`evenhub/`): the front-end ported to the official EvenAppBridge container model, built into `understand-me.ehpk` and verified loading in the official Even Hub simulator (SDK pinned to 0.0.14 for simulator 0.9.5 compatibility)

Everything not listed above was created during the build week (Nov 23–29, 2026).

## License

MIT
