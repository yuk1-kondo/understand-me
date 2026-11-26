# Understand Me — Even Hub app

The `app/` front-end repackaged as a real **Even Hub** app (Even Realities G2),
verified in the official simulator. Built for Heads Up: Even Realities
Hackathon, Track 01 — Messaging & News.

## What the official format turned out to be

Research sources (official docs, fetched 2026-11-23):

- Architecture — https://hub.evenrealities.com/docs/get-started/architecture
- First app / project layout — https://hub.evenrealities.com/docs/get-started/quickstart/first-app
- Tooling install — https://hub.evenrealities.com/docs/get-started/quickstart/install-tools
- Display & UI system — https://hub.evenrealities.com/docs/build/display
- Networking — https://hub.evenrealities.com/docs/build/networking
- Simulator (incl. headless automation API) — https://hub.evenrealities.com/docs/test/simulator
- Manifest + `.ehpk` packaging — https://hub.evenrealities.com/docs/ship/packaging

Key facts that shaped the port:

1. **An Even Hub app is a plain web app** (Vite + TypeScript here) that runs in a
   WebView inside the Even Realities phone app — it is **not** rendered on the
   glasses. Your JS calls `EvenAppBridge` methods; the glasses composite a fixed
   576×288 canvas from **containers** (`TextContainerProperty`,
   `ListContainerProperty`, `ImageContainerProperty`) placed at absolute pixel
   coordinates. **No DOM, no CSS, no font-size control** reaches the lenses.
2. The only Even-specific project file is **`app.json`** (manifest). Everything
   else is standard Vite. Build with `npm run build`, pack with
   `evenhub pack app.json dist -o app.ehpk` → an `.ehpk` bundle.
3. Input comes through `bridge.onEvenHubEvent` as `textEvent` / `listEvent` /
   `sysEvent` with `OsEventTypeList` types (click, scroll-top/bottom,
   double-click, long-press). Exactly one container per page may have
   `isEventCapture: 1`.
4. `fetch()` to a backend requires **two** gates: a `network` permission with a
   `whitelist` in `app.json` (checked by the Even app), **and** proper CORS
   headers from the server (checked by the WebView — the whitelist does not
   bypass CORS).
5. Tooling: `@evenrealities/evenhub-cli` (0.2.0) + `@evenrealities/evenhub-simulator`
   (0.9.5) installed globally via npm; `@evenrealities/even_hub_sdk` is a project
   dependency.

### Differences vs. the `app/` assumptions

| `app/` (browser demo) | Even Hub reality |
|---|---|
| HTML/CSS draws the 576×288 view | SDK text/list containers at absolute px coordinates; the WebView DOM is invisible on glasses |
| Font sizes / dimming via CSS | One firmware font, one size; brightness via `textColor` 0–4 only |
| Tab / arrows / Enter | Touchpad events via `onEvenHubEvent` (tap, swipe, double-press) |
| `✓`, any Unicode | Firmware font drops unknown glyphs — `✓` (U+2713) is **not** in it; `▲`, `↑↓`, Japanese all render |
| Click = select | Exactly one `isEventCapture` container receives all events |

Input mapping chosen: **tap** on captions → open checksum card; on the card the
two choices are a native **list container** (firmware draws the focus box,
swipe up/down moves it); **tap** selects the focused choice (sends `confirm` or
`send_corrected`); swipe past the list top (`SCROLL_TOP_EVENT`) → back to
captions; **double-press** → `shutDownPageContainer(1)` system exit dialog
(required on the root page by QA).

## Project layout

```
evenhub/
├── app.json              ← Even Hub manifest (required for packaging)
├── index.html            ← WebView entry; shows a one-line status for debugging
├── package.json          ← vite + typescript + @evenrealities/even_hub_sdk@0.0.14
├── tsconfig.json
├── public/icon.png       ← 24×24 app icon
├── src/main.ts           ← the whole app: container UI + polling + events
├── dist/                 ← vite build output (packed into the .ehpk)
└── understand-me.ehpk    ← packaged app (evenhub pack)
```

`src/main.ts` is a line-by-line port of `app/app.js`: same dummy data, same
poll timings (`POLL_MS = 2000`, checksum offset `+700`, first checksum poll at
`1200 ms`), same endpoints. The backend URL defaults to
`http://localhost:8000` and can be overridden at build time:
`VITE_BACKEND_URL=http://<host>:<port> npm run build` (used by
`scripts/display_check.py` to point a build at a test backend):

- `GET /captions` — accepts `{ captions: [...] }` **and** the bare array the
  current backend actually returns (`backend/core/main.py` returns `store.all()`,
  a list — the `app/README.md` contract doc says `{ captions }`; we take both).
- `GET /checksum/latest` — `{ checksum } | { id, slot, original, heard } | null`
- `POST /checksum/respond` — `{ id, action: "confirm" | "send_corrected" }`

## Build & run

```bash
cd evenhub
npm install
npm run dev                              # http://localhost:5173

# in a second terminal — simulator window + headless control plane
evenhub-simulator http://localhost:5173 --automation-port 9898
```

Package:

```bash
npm run build
evenhub pack app.json dist -o understand-me.ehpk --sdk-ver 0.0.14
```

## Verified (headless, via `--automation-port`)

All of this was exercised end-to-end against simulator 0.9.5 without a GUI
login, using `/api/console`, `/api/screenshot/glasses` (RGBA lit-pixel counts)
and `/api/input`:

- App boots, `waitForEvenAppBridge()` resolves, `createStartUpPageContainer`
  returns 0 → captions view renders (7,708 lit px).
- Backend down → dummy captions drip in, `DEMO` badge shows, then the dummy
  checksum card pends and the `▲` alert appears.
- `click` → rebuilds to checksum card (`確認ポイント：期限 / 指示：木曜日 /
  復唱：金曜日`, 6,617 lit px, focus box on `確認する`).
- `down` moves list focus silently in firmware; `click` emits `listEvent` with
  `currentSelectItemIndex: 1` → `POST /checksum/respond` fired with
  `send_corrected` (fetch fails only because no backend is running).
- `記録しました` shows once the POST returns `status: "ok"`, then
  auto-returns to captions after 1.8 s; a failed or `ignored` POST keeps
  the card up for retry instead.
- `double_click` → `sysEvent eventType 3` → `shutDownPageContainer(1)` invoked.
- Zero glyph warnings and zero failed container calls in the simulator log.

Two gotchas discovered by testing, both handled in `src/main.ts`:

- **Simulator taps arrive as `sysEvent` with only `eventSource`** (no
  `eventType`) — a tap is `eventType === undefined`, so handlers must treat
  `CLICK_EVENT` and `undefined` as "click" (the docs hint at this in the
  quickstart; confirmed empirically).
- **SDK 0.0.16 is incompatible with simulator 0.9.5**: it calls `imuControl`
  during init, which the simulator's bridge rejects (`unknown variant`), killing
  boot. Pinned to **0.0.14** (the version the simulator tracks per the docs) —
  hence `min_sdk_version: "0.0.14"` and pack floor `min_app_version 2.2.9`.

## What remains for a human

1. **LIVE backend mode.** The backend runs, but the WebView `fetch` will fail
   CORS — `backend/core/main.py` sends no `Access-Control-Allow-Origin` header,
   and the task froze `backend/`. Options: add `CORSMiddleware` to the FastAPI
   app, or put a tiny proxy (e.g. `vite dev` proxy / nginx) in front of
   `localhost:8000` that injects the header, then point `BACKEND` at it.
   Polling itself works — the sim logs show the request leaving the WebView.
2. **Real hardware.** `evenhub qr --url "http://<LAN-IP>:5173"`, scan with the
   phone app (Developer Mode on). Also change `BACKEND` to the LAN IP — on the
   phone, `localhost` is the phone, not the Mac — and add that origin to the
   `app.json` network `whitelist`, then repack.
3. **Account steps** (need an Even Realities login): `evenhub login`, then
   `evenhub create understand-me.ehpk --name "Understand Me" --tagline "..."`
   for a private build, or portal upload for submission.
4. **Visual QA on hardware.** The simulator is not pixel-accurate (font
   rendering, `textColor` levels, list focus position). Check that 4 caption
   lines + header/footer fit without overflow on a real G2; the fixed firmware
   font is wider than the CSS mock for Japanese text.
5. **Decide the exit gesture.** Double-press is wired to the required system
   exit dialog. If the hackathon demo needs "back to captions" instead of exit,
   that's a UX call to make on hardware.
