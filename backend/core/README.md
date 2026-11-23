# Understand Me — backend core

Caption queue + checksum engine for the Even G2 app "Understand Me"
(captions for deaf / hard-of-hearing wearers, plus a teach-back check that
catches misheard instructions — e.g. 木曜日 vs 金曜日）。

## Run

```bash
cd backend/core
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

No API keys are needed: slot extraction is rule-based and works offline.
(`ANTHROPIC_API_KEY` is reserved for a future Claude-based extractor —
see `checksum.py`. STT is behind an interface in `stt.py`; set
`STT_PROVIDER=fake` to use the fixed-text fake provider.)

## Endpoints

| Method | Path | Body / response |
|---|---|---|
| POST | `/captions` | `{speaker, text}` → the stored caption `{speaker, text, ts}`; also pushed to WebSocket clients |
| GET | `/captions` | list of all captions so far |
| WS | `/ws` | each new caption is pushed live as a JSON object |
| POST | `/checksum/extract` | `{text}` → `{deadline, quantity, task, destination}` |
| POST | `/checksum/compare` | `{original_text, paraphrase_text}` → list of diffs `[{slot, original, paraphrase}]` (empty = match); a non-empty result also becomes the pending card |
| GET | `/checksum/latest` | pending checksum card `{id, slot, original, heard, diffs}` for the glasses app, or `null` |
| POST | `/checksum/respond` | `{id, action: "confirm" \| "send_corrected"}` → records the wearer's response and clears the card |
| GET | `/health` | `{"status": "ok"}` |

Auto-checksum: an instruction-like caption (slots found) from a different speaker than the last instruction is treated as its paraphrase; any slot mismatch automatically becomes the pending card at `/checksum/latest`, and the instruction is consumed so the next instruction-like utterance starts a fresh comparison.

Captions always have the shape `{speaker: str, text: str, ts: ISO string}`.

## Tests

```bash
pytest
```

Covers: 木曜日/金曜日 mismatch detection, quantity mismatch detection,
identical instructions producing zero diffs, caption queue + WebSocket
push, and the STT stub / fake.

## Layout

- `main.py` — FastAPI app (endpoints + WebSocket)
- `captions.py` — in-memory caption store + WebSocket fan-out
- `checksum.py` — slot extraction interface, rule-based extractor, diffing
- `stt.py` — STT interface (stub raises `NotImplementedError`; `FakeSTT` for tests)
