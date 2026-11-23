"""Understand Me — mock receiver (no Discord, no token, no audio).

Feeds a scripted sequence of sample Japanese utterances from two speakers
into the exact same caption-queue path the real Discord receiver uses:

    POST {BACKEND_URL}/captions   {"speaker": "...", "text": "..."}

Use it to develop and demo everything downstream of the receiver —
caption display, checksum slot extraction, confirmation UI — while the
bot token does not exist yet.

    python mock_receiver.py                 # post the script, 3s apart
    python mock_receiver.py --interval 1    # faster
    python mock_receiver.py --dry-run       # print payloads, POST nothing
    python mock_receiver.py --loop          # repeat the script forever
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request

# (speaker, text) — a Friday game-night call: small talk, then an
# instruction whose deadline is 木曜日 (the checksum test case), then a
# second speaker with a different plan that must not be mixed into it.
SCRIPT = [
    ("佐藤", "こんばんは、聞こえていますか。"),
    ("佐藤", "今週の資料なんだけど、木曜日までに3部、教務部へ提出をお願いできますか。"),
    ("田中", "金曜の夜はいつものゲーム、21時からだよ。"),
    ("佐藤", "提出先は教務部、部数は3部でお願いします。"),
    ("田中", "了解、木曜日の件も聞いていました。"),
]


def post_caption(backend_url: str, speaker: str, text: str, dry_run: bool) -> None:
    payload = {"speaker": speaker, "text": text}
    if dry_run:
        print(f"[dry-run] POST {backend_url}/captions {json.dumps(payload, ensure_ascii=False)}")
        return
    request = urllib.request.Request(
        backend_url.rstrip("/") + "/captions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            print(f"[{resp.status}] {speaker}: {text}")
    except urllib.error.URLError as exc:
        # The mock's job is to exercise the path; a down backend is
        # reported, not fatal, so the script still plays through.
        print(f"[FAILED: {exc}] would have posted {speaker}: {text}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=3.0, help="seconds between utterances")
    parser.add_argument("--dry-run", action="store_true", help="print payloads instead of POSTing")
    parser.add_argument("--loop", action="store_true", help="repeat the script forever")
    args = parser.parse_args()

    backend_url = os.environ.get("BACKEND_URL", "http://localhost:8000")
    print(f"Mock receiver -> {backend_url}/captions (interval {args.interval}s)")
    while True:
        for speaker, text in SCRIPT:
            post_caption(backend_url, speaker, text, args.dry_run)
            time.sleep(args.interval)
        if not args.loop:
            break
    print("Mock script finished.")


if __name__ == "__main__":
    main()
