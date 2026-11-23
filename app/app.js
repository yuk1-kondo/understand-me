"use strict";
/* ============================================================
   Understand Me — Even G2 front-end scaffold
   Two views: captions / checksum card. Polls the backend;
   falls back to built-in dummy data so it demos standalone.
   ============================================================ */

// Backend base URL. Change this when the real backend runs elsewhere.
const BACKEND = "http://localhost:8000";

const POLL_MS = 2000;

/* ---------------- dummy data (standalone demo) ---------------- */
const DUMMY_CAPTIONS = [
  { speaker: "田中さん", text: "じゃあ来週の資料の件だけど" },
  { speaker: "田中さん", text: "木曜日までに、3部" },
  { speaker: "田中さん", text: "教務部へ提出をお願いできる？" },
  { speaker: "佐藤さん", text: "了解、木曜日ですね" },
  { speaker: "田中さん", text: "そう、木曜の午後3時まで" },
];
const DUMMY_CHECKSUM = {
  id: "demo-1",
  slot: "期限",
  original: "木曜日",
  heard: "金曜日",
};

/* ---------------- state ---------------- */
let view = "captions";           // "captions" | "checksum"
let backendLive = false;
let captions = [];
let dummyIdx = 0;
let checksum = null;             // { id, slot, original, heard } or null
let checksumHandled = false;     // true after the wearer responds
let selectedChoice = 0;          // 0 = 確認する, 1 = 正しい内容を送る

const $ = (id) => document.getElementById(id);

/* ---------------- rendering ---------------- */
function renderCaptions() {
  const list = $("caption-list");
  list.innerHTML = "";
  // Show the last 4 lines; older lines dimmer/smaller.
  const shown = captions.slice(-4);
  shown.forEach((c, i) => {
    const div = document.createElement("div");
    div.className = "caption" + (i === shown.length - 1 ? " latest" : " old");
    const sp = document.createElement("span");
    sp.className = "speaker";
    sp.textContent = c.speaker;
    div.appendChild(sp);
    div.appendChild(document.createTextNode(c.text));
    list.appendChild(div);
  });
  $("conn").textContent = backendLive ? "LIVE" : "DEMO";
  $("checksum-alert").classList.toggle("hidden", !(checksum && !checksumHandled));
}

function renderChecksum() {
  const has = !!(checksum && !checksumHandled);
  $("checksum-empty").classList.toggle("hidden", has || checksumHandled);
  $("checksum-card").classList.toggle("hidden", !has);
  $("checksum-done").classList.toggle("hidden", !checksumHandled);
  $("checksum-state").textContent = has ? "要確認" : "OK";
  if (has) {
    $("cs-slot").textContent = "確認ポイント：" + checksum.slot;
    $("cs-original").textContent = checksum.original;
    $("cs-heard").textContent = checksum.heard;
  }
  $("choice-confirm").classList.toggle("selected", selectedChoice === 0);
  $("choice-send").classList.toggle("selected", selectedChoice === 1);
}

function render() { renderCaptions(); renderChecksum(); }

function setView(next) {
  view = next;
  $("view-captions").classList.toggle("active", view === "captions");
  $("view-checksum").classList.toggle("active", view === "checksum");
  render();
}

/* ---------------- backend polling ---------------- */
async function fetchJSON(path) {
  const res = await fetch(BACKEND + path, { cache: "no-store" });
  if (!res.ok) throw new Error(res.status);
  return res.json();
}

async function pollCaptions() {
  try {
    const data = await fetchJSON("/captions");
    // Expected: { captions: [{ speaker, text }, ...] }
    if (Array.isArray(data.captions)) {
      captions = data.captions;
      backendLive = true;
    }
  } catch (_) {
    backendLive = false;
    // Standalone demo: drip-feed dummy captions one by one.
    if (dummyIdx < DUMMY_CAPTIONS.length) {
      captions.push(DUMMY_CAPTIONS[dummyIdx++]);
    }
  }
  render();
}

async function pollChecksum() {
  try {
    const data = await fetchJSON("/checksum/latest");
    // Expected: { id, slot, original, heard } or null / { checksum: null }
    const cs = data && (data.checksum !== undefined ? data.checksum : data);
    if (cs && cs.id !== (checksum && checksum.id)) {
      checksum = cs;
      checksumHandled = false;
      selectedChoice = 0;
    } else if (!cs) {
      checksum = null;
    }
    backendLive = true;
  } catch (_) {
    // Standalone demo: surface the dummy diff once captions have played out.
    if (!checksum && dummyIdx >= 3) {
      checksum = DUMMY_CHECKSUM;
      checksumHandled = false;
    }
  }
  render();
}

/* ---------------- checksum response ---------------- */
async function respondChecksum() {
  if (!checksum || checksumHandled) return;
  const action = selectedChoice === 0 ? "confirm" : "send_corrected";
  checksumHandled = true;
  render();
  try {
    await fetch(BACKEND + "/checksum/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: checksum.id, action }),
    });
  } catch (_) {
    // Standalone demo: nothing to send to; the UI state already updated.
  }
  // After a pause, clear the card and return to captions.
  setTimeout(() => {
    checksum = null;
    checksumHandled = false;
    setView("captions");
  }, 1800);
}

/* ---------------- input (stands in for R1 ring / touch) ---------------- */
document.addEventListener("keydown", (e) => {
  if (e.key === "Tab") {
    e.preventDefault();
    setView(view === "captions" ? "checksum" : "captions");
    return;
  }
  if (view === "checksum") {
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      selectedChoice = 0; render();
    } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      selectedChoice = 1; render();
    } else if (e.key === "Enter") {
      respondChecksum();
    }
  }
});

// Tap/click also works (simulator mouse, future touch mapping).
$("choice-confirm").addEventListener("click", () => { selectedChoice = 0; render(); respondChecksum(); });
$("choice-send").addEventListener("click", () => { selectedChoice = 1; render(); respondChecksum(); });
$("checksum-alert").addEventListener("click", () => setView("checksum"));

/* ---------------- boot ---------------- */
render();
setInterval(pollCaptions, POLL_MS);
setInterval(pollChecksum, POLL_MS + 700);
pollCaptions();
setTimeout(pollChecksum, 1200);
