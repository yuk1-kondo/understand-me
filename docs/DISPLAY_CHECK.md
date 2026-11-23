# Display check — glasses framebuffer regression test

`scripts/display_check.py` is the local end-to-end regression check for the
glasses display path. It is **local-only** (needs the macOS
`evenhub-simulator` binary) and deliberately uses alternate ports so it can
run while a live demo occupies `:8000` / `:5173` / `:9898`.

## What it does

1. Preflight: ports `8001`, `5174`, `9899` free; `evenhub-simulator` and
   `npm` on `PATH`.
2. Builds `evenhub/` with `VITE_BACKEND_URL=http://localhost:8001` into an
   **isolated temp outDir** (`tsc` + `vite build --outDir`), so the live
   demo's `evenhub/dist` is never overwritten with a `:8001` build. The
   app's backend URL is a build-time constant — see `evenhub/src/main.ts`.
3. Starts the FastAPI backend on `:8001`, a static server for the isolated
   dist on `:5174`, and `evenhub-simulator` with `--automation-port 9899`.
4. POSTs the canonical pair — 佐藤「木曜日までに資料を3部、教務部へ提出」/
   田中「金曜日…」— then verifies `GET /checksum/latest` reports the
   期限 木曜日→金曜日 card.
5. Captures `GET /api/screenshot/glasses` and asserts the framebuffer is not
   blank (>500 lit RGBA pixels; a healthy caption view is ~7,000).
6. POSTs `/api/input {"action":"click"}` and asserts the framebuffer changes
   substantially (>2 % of pixels differ) and stays non-blank — the checksum
   card view.
7. Cleans up every process it spawned and prints `PASS` / `FAIL` with the
   failing checks and log tails.

## Usage

```bash
python3 scripts/display_check.py
```

Artifacts (raw RGBA PNGs straight from the LVGL framebuffer — never
flattened to RGB, since both background and text are pure green):

- `demo-assets/display-check-latest.png` — post-click framebuffer (the card)
- `demo-assets/display-check-captions.png` — pre-click caption view

Exit code is 0 on PASS. Logs of spawned processes live under
`/tmp/display-check-*/` and are tailed automatically on failure.

Why not CI: the script needs `evenhub-simulator`, which only ships as a
macOS desktop app/binary and opens a real WebView; GitHub-hosted runners
can't provide it. `.github/workflows/ci.yml` runs the pytest suite and the
vite build instead.
