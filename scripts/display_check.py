#!/usr/bin/env python3
"""Understand Me — glasses display regression check (local only, macOS).

End-to-end: build evenhub (into an ISOLATED outDir so the live demo's
evenhub/dist is never overwritten) -> backend on :8001 -> static server on
:5174 -> evenhub-simulator (automation :9899) -> post the canonical
instruction / paraphrase pair -> drive the glasses via the headless
automation API and assert on the actual framebuffer.

Asserts:
  (a) the caption-view framebuffer is not blank (lit pixels > threshold)
  (b) a checksum card appears after a click input (framebuffer changes
      substantially AND the backend reports the pending card)

Saves the post-click framebuffer (raw RGBA PNG, never flattened) to
  demo-assets/display-check-latest.png
and the caption-view framebuffer for comparison to
  demo-assets/display-check-captions.png

Uses ONLY ports 8001 / 5174 / 9899 so it can run alongside a live demo on
8000 / 5173 / 9898. Every process it spawns is killed on exit. Stdlib only.

    python3 scripts/display_check.py
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_PORT = 8001
STATIC_PORT = 5174
AUTOMATION_PORT = 9899

BACKEND_URL = f"http://localhost:{BACKEND_PORT}"
APP_URL = f"http://localhost:{STATIC_PORT}"
AUTO = f"http://127.0.0.1:{AUTOMATION_PORT}/api"

OUT_DIR = ROOT / "demo-assets"
OUT_CARD = OUT_DIR / "display-check-latest.png"
OUT_CAPTIONS = OUT_DIR / "display-check-captions.png"

# The canonical misunderstanding: Sato says Thursday, Tanaka hears Friday.
CAPTIONS = [
    ("佐藤", "木曜日までに資料を3部、教務部へ提出してください"),
    ("田中", "金曜日までに資料を3部、教務部へ提出します"),
]

# A rendered caption view measured ~7,700 lit pixels; a dead framebuffer is 0.
MIN_LIT_PIXELS = 500
# The card view is a full page rebuild; require a clearly visible change.
MIN_DIFF_RATIO = 0.02

results: list[tuple[bool, str, str]] = []  # (ok, check name, detail)


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((ok, name, detail))
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    return ok


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def http_get(url: str, timeout: float = 5.0) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 0, b""


def http_post(url: str, payload: dict, timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except Exception:
        return 0, b""


def wait_http(url: str, timeout_s: float, want: int = 200) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        status, _ = http_get(url, timeout=2)
        if status == want:
            return True
        time.sleep(0.5)
    return False


def port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# ---------------------------------------------------------------------------
# Minimal PNG decoder -> RGBA (8-bit, non-interlaced, color types 6/2/0)
# ---------------------------------------------------------------------------

def decode_png_rgba(data: bytes) -> tuple[int, int, bytearray]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    pos = 8
    idat = bytearray()
    w = h = colortype = interlace = depth = 0
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            w, h, depth, colortype, _c, _f, interlace = struct.unpack(">IIBBBBB", chunk)
        elif ctype == b"IDAT":
            idat += chunk
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if depth != 8 or interlace != 0 or colortype not in (0, 2, 6):
        raise ValueError(f"unsupported PNG: depth={depth} type={colortype} interlace={interlace}")
    bpp = {0: 1, 2: 3, 6: 4}[colortype]
    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    px = bytearray()
    prev = bytearray(stride)
    i = 0
    for _y in range(h):
        f = raw[i]
        i += 1
        line = bytearray(raw[i:i + stride])
        i += stride
        if f == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif f == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif f == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        elif f != 0:
            raise ValueError(f"unknown PNG filter {f}")
        px += line
        prev = line
    if bpp == 4:
        return w, h, px
    rgba = bytearray(w * h * 4)
    if bpp == 3:
        rgba[0::4], rgba[1::4], rgba[2::4] = px[0::3], px[1::3], px[2::3]
    else:
        rgba[0::4] = rgba[1::4] = rgba[2::4] = px
    rgba[3::4] = b"\xff" * (w * h)
    return w, h, rgba


def lit_pixels(px: bytearray) -> int:
    """Count pixels that are both visible (alpha) and non-black."""
    n = 0
    for i in range(0, len(px), 4):
        if px[i + 3] and (px[i] or px[i + 1] or px[i + 2]):
            n += 1
    return n


def diff_ratio(a: bytearray, b: bytearray) -> float:
    if len(a) != len(b):
        return 1.0
    n = 0
    for i in range(0, len(a), 4):
        if a[i:i + 4] != b[i:i + 4]:
            n += 1
    return n / (len(a) // 4)


# ---------------------------------------------------------------------------
# Process management — only ever kills what it spawned
# ---------------------------------------------------------------------------

spawned: list[tuple[str, subprocess.Popen, object]] = []
log_dir = Path(tempfile.mkdtemp(prefix="display-check-"))


def spawn(name: str, argv: list[str], cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen:
    logf = open(log_dir / f"{name}.log", "wb")
    p = subprocess.Popen(
        argv, cwd=cwd, env=env, stdout=logf, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    spawned.append((name, p, logf))
    return p


def cleanup() -> None:
    for name, p, _lf in spawned:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
            except Exception:
                pass
    time.sleep(1.0)
    for name, p, lf in spawned:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                pass
        lf.close()


def dump_log_tails() -> None:
    for name, _p, _lf in spawned:
        log = log_dir / f"{name}.log"
        try:
            tail = log.read_text(errors="replace").strip().splitlines()[-8:]
        except Exception:
            continue
        print(f"  --- {name} log tail ---")
        for line in tail:
            print(f"    {line}")


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def main() -> int:
    overall = True

    # -- preflight ----------------------------------------------------------
    print("[preflight]")
    if not check("ports free (8001/5174/9899)",
                 all(port_free(p) for p in (BACKEND_PORT, STATIC_PORT, AUTOMATION_PORT)),
                 "another process holds one of the check ports"):
        return finish(1)
    sim_bin = shutil.which("evenhub-simulator")
    if not check("evenhub-simulator on PATH", sim_bin is not None, sim_bin or "not found"):
        return finish(1)
    if not check("npm on PATH", shutil.which("npm") is not None):
        return finish(1)
    venv_py = ROOT / "backend" / "core" / ".venv" / "bin" / "python"
    backend_py = str(venv_py) if venv_py.exists() else sys.executable
    print(f"  info  backend python: {backend_py}")

    # -- build ---------------------------------------------------------------
    # The app bakes BACKEND_URL in at build time, so the check builds into an
    # ISOLATED outDir — evenhub/dist belongs to the live demo and must not be
    # overwritten with a :8001 build.
    print("[build] tsc + vite build -> isolated dist (VITE_BACKEND_URL=%s)" % BACKEND_URL)
    env = dict(os.environ, VITE_BACKEND_URL=BACKEND_URL)
    dist_dir = Path(log_dir) / "dist"
    for argv in (["npx", "tsc"], ["npx", "vite", "build", "--outDir", str(dist_dir), "--emptyOutDir"]):
        build = subprocess.run(
            argv, cwd=ROOT / "evenhub", env=env,
            capture_output=True, text=True, timeout=300,
        )
        if not check(" ".join(argv[:2]), build.returncode == 0,
                     (build.stdout + build.stderr).strip().splitlines()[-1] if build.returncode else ""):
            print(build.stdout + build.stderr)
            return finish(1)
    if not check("isolated dist/index.html exists", (dist_dir / "index.html").exists()):
        return finish(1)

    try:
        # -- backend on :8001 ---------------------------------------------------
        print("[run] backend on :%d" % BACKEND_PORT)
        spawn("backend", [backend_py, "-m", "uvicorn", "main:app", "--port", str(BACKEND_PORT)],
              cwd=ROOT / "backend" / "core")
        if not check("backend /health", wait_http(f"{BACKEND_URL}/health", 30)):
            return finish(1)

        # -- static server on :5174 --------------------------------------------
        print("[run] static server on :%d -> isolated dist" % STATIC_PORT)
        spawn("static", [sys.executable, "-m", "http.server", str(STATIC_PORT), "--bind", "127.0.0.1"],
              cwd=dist_dir)
        if not check("static server", wait_http(APP_URL + "/", 15)):
            return finish(1)

        # -- simulator on :9899 ------------------------------------------------
        print("[run] evenhub-simulator %s --automation-port %d" % (APP_URL, AUTOMATION_PORT))
        spawn("simulator", [sim_bin, APP_URL, "--automation-port", str(AUTOMATION_PORT)])
        if not check("simulator /api/ping", wait_http(f"{AUTO}/ping", 90)):
            return finish(1)
        # Bridge boot + first poll cycles need a few seconds after ping is up
        # (input sent before the event-capturing container exists is dropped).
        print("[run] waiting for app boot + first polls (7s)")
        time.sleep(7)

        # -- canonical caption pair --------------------------------------------
        print("[drive] POST canonical pair (佐藤 木曜日 / 田中 金曜日)")
        for speaker, text in CAPTIONS:
            status, _ = http_post(f"{BACKEND_URL}/captions", {"speaker": speaker, "text": text})
            if not check(f"caption POST ({speaker})", status == 200, f"HTTP {status}"):
                return finish(1)

        # The app's poll loop needs a cycle to pick captions + card up.
        time.sleep(5)

        status, body = http_get(f"{BACKEND_URL}/checksum/latest")
        card = None
        if status == 200:
            try:
                card = json.loads(body)
            except Exception:
                card = None
        card_ok = (
            isinstance(card, dict)
            and card.get("original") == "木曜日"
            and card.get("heard") == "金曜日"
        )
        if not check("backend pending card (木曜日→金曜日)", card_ok, repr(card)):
            return finish(1)

        # -- assertion (a): framebuffer not blank -------------------------------
        status, shot1 = http_get(f"{AUTO}/screenshot/glasses", timeout=15)
        if not check("screenshot #1 (captions)", status == 200 and len(shot1) > 100,
                     f"HTTP {status}, {len(shot1)} bytes"):
            return finish(1)
        try:
            w1, h1, px1 = decode_png_rgba(shot1)
        except ValueError as e:
            check("decode screenshot #1", False, str(e))
            return finish(1)
        lit1 = lit_pixels(px1)
        check("framebuffer not blank", lit1 > MIN_LIT_PIXELS,
              f"{lit1} lit px on {w1}x{h1}")

        # -- drive click, assertion (b): checksum card --------------------------
        print("[drive] POST /api/input click")
        status, _ = http_post(f"{AUTO}/input", {"action": "click"})
        check("click input accepted", status == 200, f"HTTP {status}")
        time.sleep(2.5)

        status, shot2 = http_get(f"{AUTO}/screenshot/glasses", timeout=15)
        if not check("screenshot #2 (post-click)", status == 200 and len(shot2) > 100,
                     f"HTTP {status}, {len(shot2)} bytes"):
            return finish(1)
        w2, h2, px2 = decode_png_rgba(shot2)
        lit2 = lit_pixels(px2)
        ratio = diff_ratio(px1, px2) if (w1, h1) == (w2, h2) else 1.0
        check("card framebuffer not blank", lit2 > MIN_LIT_PIXELS, f"{lit2} lit px")
        check("checksum card appears after click", ratio > MIN_DIFF_RATIO,
              f"{ratio:.1%} of pixels changed captions->card")

        # -- save artifacts (raw RGBA PNG bytes, never flattened) ---------------
        OUT_DIR.mkdir(exist_ok=True)
        OUT_CAPTIONS.write_bytes(shot1)
        OUT_CARD.write_bytes(shot2)
        print(f"[artifacts] {OUT_CAPTIONS.relative_to(ROOT)} ({len(shot1)} B), "
              f"{OUT_CARD.relative_to(ROOT)} ({len(shot2)} B)")

        # -- optional positive-identification of the card -----------------------
        # The card view keeps '要確認' + the mismatch rows on screen; without
        # OCR we prove it via the backend card (checked above) + page change.
        overall = all(ok for ok, _n, _d in results)
        return finish(0 if overall else 1)
    except KeyboardInterrupt:
        print("interrupted")
        return finish(130)
    except Exception:
        import traceback
        traceback.print_exc()
        check("unhandled exception", False)
        return finish(1)


def finish(code: int) -> int:
    cleanup()
    fails = [n for ok, n, d in results if not ok]
    if code == 0:
        print("\nPASS — glasses display pipeline verified end-to-end")
    else:
        print(f"\nFAIL — {len(fails)} check(s) failed: {', '.join(fails)}")
        if fails:
            dump_log_tails()
        print(f"(logs kept at {log_dir})")
    return code


if __name__ == "__main__":
    sys.exit(main())
