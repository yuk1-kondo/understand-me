# Demo capture notes — Understand Me (Even G2)

Captured 2026-11-23 on this Mac. All data is mock/demo only — no real API keys,
no Discord/Telegram tokens.

## Assets in this folder

| File | What it shows | How it was captured |
|---|---|---|
| `01-caption-view.png` | 576×288 glasses framebuffer: speaker-labelled live captions （佐藤/田中）, `LIVE` badge, `▲ 確認カードがあります` alert | `GET /api/screenshot/glasses` |
| `02-checksum-card.png` | 576×288 glasses framebuffer: 理解チェック card — 確認ポイント: 期限 / 指示: 木曜日 / 復唱: 金曜日, focus box on 確認する | `POST /api/input {"action":"click"}` then `GET /api/screenshot/glasses` |

Both are RGBA PNGs straight from the simulator's LVGL framebuffer — keep them
RGBA; converting to RGB fuses background and text (both pure green).

## Exactly what was run

```bash
# 1) Backend (venv created at backend/core/.venv — new directory, no source edits)
cd ~/understand-me/backend/core
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./.venv/bin/uvicorn main:app --port 8000        # still running in background

# 2) Rebuild + repack (build output was byte-identical; ehpk re-stamped anyway)
cd ~/understand-me/evenhub
npm run build
evenhub pack app.json dist -o understand-me.ehpk --sdk-ver 0.0.14

# 3) Simulator — see "What did not work" for why dist/ is served instead of
#    passing the .ehpk directly.
cd ~/understand-me/evenhub/dist
python3 -m http.server 5173 &                  # still running
evenhub-simulator http://localhost:5173 --automation-port 9898 &   # still running

# 4) Demo conversation — mock receiver (5 scripted utterances, all HTTP 200)
cd ~/understand-me/backend/discord_bot
~/understand-me/backend/core/.venv/bin/python mock_receiver.py --interval 0.6

# The mock script alone leaves a messy card (期限: null → 木曜日), so the
# requested clean mismatch pair was posted on top:
curl -X POST http://localhost:8000/captions -H 'Content-Type: application/json' \
  -d '{"speaker":"佐藤","text":"木曜日までに3部、事務所へ提出してください。"}'
curl -X POST http://localhost:8000/captions -H 'Content-Type: application/json' \
  -d '{"speaker":"田中","text":"金曜日までに3部、事務所へ提出してください。"}'
# → GET /checksum/latest = { slot: 期限, original: 木曜日, heard: 金曜日 }  (single diff)

# 5) Captures
curl -o demo-assets/01-caption-view.png  http://127.0.0.1:9898/api/screenshot/glasses
curl -X POST http://127.0.0.1:9898/api/input -H 'Content-Type: application/json' -d '{"action":"click"}'
curl -o demo-assets/02-checksum-card.png http://127.0.0.1:9898/api/screenshot/glasses
```

## What worked

- Backend core on :8000 with the rule-based extractor (no API key needed).
  `CORSMiddleware` is already in `main.py`, so the simulator WebView's
  `fetch()` polling works — zero console errors, `LIVE` badge confirms it.
- The `.ehpk` packs cleanly (`evenhub pack`, 39,598 bytes).
- Headless automation: `/api/ping`, `/api/console`, `/api/input`,
  `/api/screenshot/glasses` all behaved per the docs; `click` on the caption
  view opened the checksum card exactly as on hardware.

## What did not work

- **The simulator cannot load the `.ehpk` directly in this setup.**
  `evenhub-simulator` rejects `file://` and plain paths ("invalid URL format
  (expected http:// or https://)"), and pointing it at an `.ehpk` served over
  local HTTP (`http://localhost:8099/understand-me.ehpk`) produced a blank
  WebView and blank framebuffer after 15 s — the 0.9.x simulator's
  "`.ehpk` URL" support appears to mean a hosted/portal URL, not a local file.
  Workaround used instead: serve `dist/` (byte-identical to what the `.ehpk`
  contains — the bundle is `app.json` + the dist tree) over HTTP on :5173.
- `/api/screenshot/webview` returns a blank white PNG when the page fails to
  load — useful as a quick "did it boot" check.

## Manual steps to record the 3-minute demo video

Everything needed is **already running** right now: backend on :8000, static
server on :5173, simulator window open with the checksum card pending.
If you closed them, restart first:

```bash
cd ~/understand-me/backend/core && ./.venv/bin/uvicorn main:app --port 8000 &
cd ~/understand-me/evenhub/dist && python3 -m http.server 5173 &
evenhub-simulator http://localhost:5173 --automation-port 9898 &
# reset demo state: restart uvicorn (clears in-memory store), then re-run
# the two curl POSTs above once the sim is showing captions.
```

To record:

1. **Start screen recording.** Fastest on this Mac: press `Cmd+Shift+5` →
   "Record Selected Portion" → drag a box around the simulator's glasses
   window → Record. (Or QuickTime Player → File → New Screen Recording.)
   Stop with `Cmd+Ctrl+Esc` or the menu-bar stop button; the clip lands on
   the Desktop.
2. **Beat 1 — captions (~40 s).** In a terminal, run
   `python mock_receiver.py --interval 3` (slower = more readable on video)
   against the running backend. The glasses view fills with 佐藤/田中
   captions as they arrive (2 s poll).
3. **Beat 2 — the mismatch (~30 s).** Run the two `curl` POSTs above. Within
   ~3 s the `▲ 確認カードがあります` alert appears.
4. **Beat 3 — the card (~40 s).** Tap the simulator's touchpad area (or
   `POST /api/input {"action":"click"}`). The 理解チェック card shows
   指示: 木曜日 vs 復唱: 金曜日.
5. **Beat 4 — resolve (~30 s).** `down` to move focus to 正しい内容を送る,
   `click` to send — glasses show 送信しました and auto-return to captions;
   the backend logs the `send_corrected` response. (Or `click` on 確認する
   for the confirm path.)
6. **Beat 5 — exit (~10 s).** `double_click` on the root page raises the
   system exit dialog — required by QA and a clean end-card for the video.

Headless equivalents for every gesture (for scripted takes):

```bash
for a in click down click double_click; do
  curl -X POST http://127.0.0.1:9898/api/input -H 'Content-Type: application/json' -d "{\"action\":\"$a\"}"; sleep 1;
done
```

Note: a `click`/`down` sent while no event-capturing container exists is
silently dropped; allow ~4 s after simulator launch before driving input.
