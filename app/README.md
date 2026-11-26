# Understand Me — G2 app (front-end scaffold)

Self-contained HTML/CSS/JS for the Even G2 display. No build step, no dependencies, no CDN.

## How to open

Any of these works:

- Double-click `index.html` in a browser, or
- Serve the folder: `python3 -m http.server 8080` in this directory, then open `http://localhost:8080`

The stage is exactly the G2 frame (576×288), monochrome green on black.

## Views

| View | What it shows |
|---|---|
| Captions | Latest speaker-labelled captions, newest line brightest. Header badge shows `LIVE` (backend connected) or `DEMO`. |
| Checksum card | One card only: the mismatched slot with 指示 (what was said) vs 復唱 (what the wearer repeated back), and two choices — [確認する] [訂正を記録する]. |

**Controls** (standing in for the R1 ring / touch panel):

- `Tab` — toggle between captions and checksum views
- `←` / `→` (or `↑` / `↓`) — move the choice selection on the checksum card
- `Enter` — confirm the selected choice
- Mouse click also works on the choices and on the "確認カードがあります" alert

## Dummy-data demo flow (no backend needed)

1. Open the page. Captions drip in one line at a time (Tanaka-san asking for 資料を木曜日までに3部、教務部へ提出）.
2. After a few lines, a dummy checksum diff appears （期限： 指示＝木曜日 / 復唱＝金曜日） and the caption view shows a green alert: 「確認カードがあります」.
3. Press `Tab` to open the card, pick a choice with the arrow keys, press `Enter`.
4. The card shows 「記録しました」 once the backend answers `status: "ok"`, and returns to the caption view.

## Backend contract (what app.js polls)

Backend URL is configured at the top of `app.js` (`BACKEND`, default `http://localhost:8000`).

- `GET /captions` → the backend currently returns a **bare array** `[{ "speaker": "田中さん", "text": "...", "ts": "..." }, ...]`; `app.js` also accepts the `{ "captions": [...] }` wrapper
- `GET /checksum/latest` → `{ "id": "x", "slot": "期限", "original": "木曜日", "heard": "金曜日" }` or `null`
- `POST /checksum/respond` ← `{ "id": "x", "action": "confirm" | "send_corrected" }`

If a request fails before the backend has ever answered, the app falls back to the dummy data above, so the UI never blocks on the backend. Once real data arrived, failed polls never inject dummy lines — the footer shows a short connection note instead （字幕更新停止 / 確認カード取得不可）.

## Still to wire to the real Even Hub SDK during the build

- Package this web app as an Even Hub app (`.ehpk`) and load it in the Even Hub simulator instead of a plain browser tab.
- Replace keyboard input with the real input events: R1 ring / touch-panel gestures from the SDK (tap = Enter, swipe = arrow keys, the SDK's view-switch event = Tab).
- Replace HTTP polling with the SDK's recommended channel if one exists for companion-backend data (or keep polling if the sandbox allows it — verify in the simulator, since the WebView is suspended in the background; the app is foreground-only by design).
- Route the wearer's actual voice input (paraphrase capture) through the phone/glasses mic path the SDK exposes, instead of the backend-only flow assumed here.
- Confirm the 576×288 layout and green levels against the simulator's rendering (16-level monochrome) and trim type sizes if lines wrap.
