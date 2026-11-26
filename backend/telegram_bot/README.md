# Understand Me — Telegram tier

The guaranteed fallback line of Understand Me. The Discord voice-channel
line is the flagship, but it depends on fragile post-DAVE voice
receiving; this Telegram tier implements the *same product loop* over
voice notes, which the Telegram Bot API fully supports. If the Discord
spike fails, this becomes the main line; if it succeeds, this is Act 2
of the demo (an instruction from family / a colleague outside Discord).

## How the flow maps to the product

| Product step | Here |
|---|---|
| Instruction arrives by voice | User sends a Telegram **voice message** (or plain text, treated the same way) |
| Read: captions on the lens | Audio is transcribed via `stt_interface`, then posted to the core backend caption queue: `POST {BACKEND_URL}/captions {"speaker", "text"}` — the same queue the G2 app renders |
| Check: checksum points | `POST {BACKEND_URL}/checksum/extract` extracts the slots (deadline / quantity / task / destination); the bot replies with the confirmation points and inline buttons **[この内容で確定] [訂正文を入力]** |
| Write: confirmed understanding goes back | **この内容で確定** → the bot replies with the confirmed text. **訂正文を入力** → the bot asks for the full corrected instruction and runs the checksum on it again |

The pending checksum is kept per chat (one active instruction per
chat), which matches how the glasses flow works: one instruction is
being confirmed at a time.

## Setup (BotFather)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a display name (e.g. `Understand Me`) and a username ending in
   `bot` (e.g. `understand_me_g2_bot`).
3. BotFather returns a token. **Put it in the Secure Vault / your local
   `.env` — never commit it, never paste it into chat or the repo.**
4. No special bot settings are required: the bot uses polling and
   needs no webhook, no privacy-mode change for direct chats.

## Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | BotFather token |
| `BACKEND_URL` | no | `http://localhost:8000` | Core backend (captions + checksum) |
| `STT_PROVIDER` | no | `fake` | `fake` = fixed Japanese sample text (testing/demo); `whisper` = real local STT (faster-whisper, `WHISPER_MODEL` selects size, default `large-v3-turbo`); `real` = production provider stub in `stt_interface.py` (raises until implemented) |

See `../../.env.example` for the full list across components.

## Run

```bash
cd backend/telegram_bot
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...   # from your secret store
export BACKEND_URL=http://localhost:8000
python bot.py
```

Then in Telegram: `/start`, and send a voice note or a text such as
「金曜日までに資料を3部、教務部へ提出してください」.

With the fake STT provider, any voice note transcribes to the canonical
test instruction 「木曜日までに資料を3部、教務部へ提出してください」 —
useful for rehearsing the Thursday/Friday misunderstanding scene:
confirm it, or tap 訂正文を入力 and send the Friday version to watch the
checksum re-run.

## Files

- `bot.py` — handlers (voice / text / callback), backend calls, entry point
- `stt_interface.py` — STT provider interface, fake provider, real-provider stub
- `requirements.txt` — `python-telegram-bot`, `httpx`, `faster-whisper`
