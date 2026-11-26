"use strict";
/* ============================================================
   Understand Me — Even G2 front-end scaffold
   Two views: captions / checksum card. Polls the backend;
   falls back to built-in dummy data so it demos standalone.
   ============================================================ */

// Backend base URL. Change this when the real backend runs elsewhere.
const BACKEND = "http://localhost:8000";

const POLL_MS = 2000;

/* ---------------- i18n ----------------
   ?lang=ja keeps the original Japanese UI; anything else — including no
   query at all — falls back to English (submission build default). */
const LANG = new URLSearchParams(location.search).get("lang") === "ja" ? "ja" : "en";
document.documentElement.lang = LANG;

const STRINGS = {
  ja: {
    notDetected: "検出できず",
    connCaptionsOnly: "字幕のみ",
    connCardsOnly: "カードのみ",
    connOffline: "切断",
    footerToCard: "Tab：確認カードへ",
    backendDown: "バックエンド切断",
    captionsStopped: "字幕更新停止",
    cardsUnavailable: "確認カード取得不可",
    alertPending: "▲ 確認カードがあります（Tab）",
    waiting: "会話を待っています",
    checksumTitle: "理解チェック",
    labelOriginal: "指示",
    labelHeard: "復唱",
    footerHint: "←→：選択　Enter：決定　Tab：字幕へ",
    emptyCard: "確認が必要な項目はありません",
    stateOk: "OK",
    stateUpdated: "更新あり",
    stateCheck: "要確認",
    stateSending: "処理中",
    stateRecorded: "記録済",
    stateRetry: "未記録",
    slotNewer: "新しい確認があります",
    slotUpdated: "この確認は更新されました",
    slotSending: "記録しています…",
    slotRecordedCorrected: "訂正を記録しました",
    slotRecordedConfirmed: "確認を記録しました",
    slotRetry: "記録できませんでした",
    slotCheckPrefix: "確認ポイント：",
    choices: {
      pending: ["確認する", "訂正を記録する"],
      pendingNoOriginal: ["確認する", "字幕へ戻る"],
      retry: ["再試行する", "字幕へ戻る"],
      back: ["字幕へ戻る"],
    },
  },
  en: {
    notDetected: "not detected",
    connCaptionsOnly: "captions only",
    connCardsOnly: "cards only",
    connOffline: "OFFLINE",
    footerToCard: "Tab: view card",
    backendDown: "backend offline",
    captionsStopped: "captions stopped",
    cardsUnavailable: "cards unavailable",
    alertPending: "▲ Confirmation card (Tab)",
    waiting: "Waiting for speech",
    checksumTitle: "Double-check",
    labelOriginal: "Said",
    labelHeard: "Heard",
    footerHint: "←→: select  Enter: OK  Tab: captions",
    emptyCard: "Nothing to confirm",
    stateOk: "OK",
    stateUpdated: "Updated",
    stateCheck: "Check",
    stateSending: "Saving",
    stateRecorded: "Saved",
    stateRetry: "Failed",
    slotNewer: "Newer card pending",
    slotUpdated: "This card was updated",
    slotSending: "Recording…",
    slotRecordedCorrected: "Correction recorded",
    slotRecordedConfirmed: "Confirmed",
    slotRetry: "Recording failed",
    slotCheckPrefix: "Check: ",
    choices: {
      pending: ["Confirm", "Record correction"],
      pendingNoOriginal: ["Confirm", "Back to captions"],
      retry: ["Retry", "Back to captions"],
      back: ["Back to captions"],
    },
  },
};
const S = STRINGS[LANG];

/* ---------------- dummy data (standalone demo) ---------------- */
const DUMMY_CAPTIONS = LANG === "ja" ? [
  { speaker: "田中さん", text: "じゃあ来週の資料の件だけど" },
  { speaker: "田中さん", text: "木曜日までに、3部" },
  { speaker: "田中さん", text: "教務部へ提出をお願いできる？" },
  { speaker: "佐藤さん", text: "了解、木曜日ですね" },
  { speaker: "田中さん", text: "そう、木曜の午後3時まで" },
] : [
  { speaker: "Tanaka", text: "About next week's handout" },
  { speaker: "Tanaka", text: "I need 3 copies by Thursday" },
  { speaker: "Tanaka", text: "submitted to the office, OK?" },
  { speaker: "Sato", text: "Got it, Thursday" },
  { speaker: "Tanaka", text: "Right, Thursday by 3pm" },
];
const DUMMY_CHECKSUM = LANG === "ja" ? {
  id: "demo-1",
  slot: "期限",
  original: "木曜日",
  heard: "金曜日",
} : {
  id: "demo-1",
  slot: "deadline",
  original: "Thursday",
  heard: "Friday",
};

/* ---------------- state ---------------- */
let view = "captions";           // "captions" | "checksum"
// H-03: captions and checksum cards have separate liveness so one failing
// endpoint cannot mask the other.
let captionsOk = false;
let cardsOk = false;
let captionsEverOk = false;      // once real data arrived, never fall back to dummies
let cardsEverOk = false;
let captions = [];
let dummyIdx = 0;
let checksum = null;             // latest card from the backend
let checksumHandled = false;     // latest card already recorded by this app
// H-01: the card under review is frozen on view entry so a newer card
// arriving mid-review can never be acted on by stale input.
let viewed = null;
let viewedStale = false;
let viewedResult = "pending";    // "pending" | "sending" | "recorded" | "retry"
let lastAction = "confirm";      // "confirm" | "send_corrected"
let selectedChoice = 0;          // focused item index in the current mode

const $ = (id) => document.getElementById(id);

/* ---------------- display rules (mirror evenhub/src/main.ts) ----------
   The lens fits ~24 full-width glyphs per 576px row. Clip to the same
   budgets so this demo previews what the glasses actually show. */
const LINE = 24;
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);
// Same layout rules as evenhub/src/main.ts: latest pinned at the visual
// center, up to HISTORY_MAX dimmed rows above it, speaker names capped.
const HISTORY_MAX = 2;
const SPEAKER_MAX = 6;
const LATEST_NAME_MAX = 10;
// Slot values the backend could not extract arrive as null (H-04).
const show = (s) => (s ? clip(s, LINE - 4) : S.notDetected);

/* ---------------- connection status (H-03) ---------------- */
function connLabel() {
  if (captionsOk && cardsOk) return "LIVE";
  if (captionsOk) return S.connCaptionsOnly;
  if (cardsOk) return S.connCardsOnly;
  return (captionsEverOk || cardsEverOk) ? S.connOffline : "DEMO";
}

function captionFooterText(pending) {
  if (pending) return S.footerToCard;
  const capDown = captionsEverOk && !captionsOk;
  const cardDown = cardsEverOk && !cardsOk;
  if (capDown && cardDown) return S.backendDown;
  if (capDown) return S.captionsStopped;
  if (cardDown) return S.cardsUnavailable;
  return S.footerToCard;
}

/* ---------------- rendering ---------------- */
// DOM is only touched when the signature changes — same "don't re-send
// settled lines" rule as the glasses' container-upgrade cache.
let captionSig = "";
function renderCaptions() {
  const pending = !!(checksum && !checksumHandled);
  const conn = connLabel();
  const footer = captionFooterText(pending);
  const shown = captions.slice(-(HISTORY_MAX + 1));
  const sig = JSON.stringify([shown, pending, conn, footer]);
  if (sig === captionSig) return;
  captionSig = sig;

  const list = $("caption-list");
  list.innerHTML = "";
  // Gaze guidance: while a card waits, the caption side dims one step so
  // the alert stays the brightest thing. Steady level — never blinking.
  list.classList.toggle("dimmed", pending);
  shown.slice(0, -1).forEach((c) => {
    const div = document.createElement("div");
    div.className = "caption old";
    div.textContent = clip(`${clip(c.speaker, SPEAKER_MAX)}: ${c.text}`, LINE);
    list.appendChild(div);
  });
  const latest = shown.at(-1);
  const div = document.createElement("div");
  div.className = "caption latest";
  if (latest) {
    const sp = document.createElement("div");
    sp.className = "spk";
    sp.textContent = clip(latest.speaker, LATEST_NAME_MAX);
    div.appendChild(sp);
    const body = document.createElement("div");
    body.textContent = clip(latest.text, LINE * 2 - 4);
    div.appendChild(body);
  } else {
    div.textContent = S.waiting;
  }
  list.appendChild(div);

  $("conn").textContent = conn;
  $("checksum-alert").classList.toggle("hidden", !pending);
  $("cap-footer").textContent = footer;
}

/* ---------------- checksum card ---------------- */
// Item labels per mode; single-item modes only offer the way back.
const CHOICES = {
  pending: S.choices.pending,
  pendingNoOriginal: S.choices.pendingNoOriginal,
  retry: S.choices.retry,
};

const STATE_LABEL = {
  empty: S.stateOk, stale: S.stateUpdated,
  pending: S.stateCheck, pendingNoOriginal: S.stateCheck,
  sending: S.stateSending, recorded: S.stateRecorded, retry: S.stateRetry,
};

function checksumMode() {
  if (!viewed) return "empty";
  if (viewedStale) return "stale";
  if (viewedResult !== "pending") return viewedResult;
  // H-04: with no instruction-side value there is nothing to correct
  // against, so the correction action must not be offered.
  return viewed.original ? "pending" : "pendingNoOriginal";
}

function renderChecksum() {
  const mode = checksumMode();
  const hasCard = mode !== "empty" && mode !== "recorded";
  $("checksum-empty").classList.toggle("hidden", mode !== "empty");
  $("checksum-card").classList.toggle("hidden", !hasCard);
  $("checksum-done").classList.toggle("hidden", mode !== "recorded");
  $("checksum-state").textContent = STATE_LABEL[mode];

  if (mode === "empty") {
    $("checksum-empty").textContent = S.emptyCard;
  }
  if (hasCard && viewed) {
    $("cs-slot").textContent =
      mode === "sending" ? S.slotSending :
      mode === "retry" ? S.slotRetry :
      mode === "stale" ? (checksum && checksum.id !== viewed.id ? S.slotNewer : S.slotUpdated) :
      S.slotCheckPrefix + viewed.slot;
    $("cs-original").textContent = show(viewed.original);
    $("cs-heard").textContent = show(viewed.heard);
  }
  if (mode === "recorded") {
    $("checksum-done").textContent =
      lastAction === "send_corrected" ? S.slotRecordedCorrected : S.slotRecordedConfirmed;
  }

  const items = CHOICES[mode] || S.choices.back;
  $("choice-confirm").textContent = items[0];
  $("choice-send").textContent = items[1] || "";
  $("choice-send").classList.toggle("hidden", items.length < 2);
  $("choice-confirm").classList.toggle("selected", selectedChoice === 0);
  $("choice-send").classList.toggle("selected", selectedChoice === 1 && items.length > 1);
}

function render() { renderCaptions(); renderChecksum(); }

function setView(next) {
  view = next;
  if (next === "checksum") {
    // Freeze the card under review (H-01): polls keep updating `checksum`,
    // but this view and its actions only ever see the frozen snapshot.
    viewed = checksum ? { ...checksum } : null;
    viewedStale = false;
    viewedResult = "pending";
    selectedChoice = 0;
  } else {
    viewed = null;
    viewedStale = false;
    viewedResult = "pending";
  }
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
    // Contract: { captions: [...] }; the current backend also serves a bare array.
    const list = Array.isArray(data.captions) ? data.captions : Array.isArray(data) ? data : null;
    if (list) captions = list;
    captionsOk = true;
    captionsEverOk = true;
  } catch (_) {
    captionsOk = false;
    // H-03: dummy captions are a standalone-demo fallback only. Once real
    // captions arrived, a failed poll must never append sample lines.
    if (!captionsEverOk && dummyIdx < DUMMY_CAPTIONS.length) {
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
      checksumHandled = false;
    }
    cardsOk = true;
    cardsEverOk = true;
  } catch (_) {
    cardsOk = false;
    // H-03: same standalone-only rule for the demo checksum card.
    if (!cardsEverOk && !checksum && dummyIdx >= 3) {
      checksum = DUMMY_CHECKSUM;
      checksumHandled = false;
    }
  }
  // H-01: while a frozen card is under review, a different card arriving
  // (or this one disappearing) marks the view stale so old input cannot
  // act on a card the wearer never saw.
  if (viewed && (viewedResult === "pending" || viewedResult === "retry")) {
    if (!checksum || checksum.id !== viewed.id) viewedStale = true;
  }
  render();
}

/* ---------------- checksum response ---------------- */
// H-02: report the POST result, not optimism. Only status:"ok" counts as
// recorded; "ignored" means the backend moved on to a different card, and
// any failure leaves the card up for retry.
async function respondChecksum(action) {
  if (!viewed || viewedStale) return;
  if (viewedResult !== "pending" && viewedResult !== "retry") return;
  if (action === "send_corrected" && !viewed.original) return;
  const card = viewed;
  lastAction = action;
  viewedResult = "sending";
  render();

  let outcome;
  try {
    const res = await fetch(BACKEND + "/checksum/respond", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: card.id, action }),
    });
    if (!res.ok) {
      outcome = "failed";
    } else {
      const data = await res.json().catch(() => null);
      outcome = data && data.status === "ok" ? "ok" :
                data && data.status === "ignored" ? "ignored" : "failed";
    }
  } catch (_) {
    outcome = "failed";
  }

  if (outcome === "ok" && checksum && checksum.id === card.id) checksumHandled = true;
  if (view !== "checksum" || !viewed || viewed.id !== card.id) {
    render(); // wearer left mid-flight; just keep the captions alert honest
    return;
  }
  if (outcome === "ok") {
    viewedResult = "recorded";
    render();
    const id = card.id;
    // H-02: the auto-return timer applies only to the card we processed —
    // a newer card that arrived meanwhile is never cleared by this timer.
    setTimeout(() => {
      if (view === "checksum" && viewed && viewed.id === id && viewedResult === "recorded") {
        if (checksum && checksum.id === id) checksum = null;
        setView("captions");
      }
    }, 1800);
  } else if (outcome === "ignored") {
    viewedStale = true;
    render();
  } else {
    viewedResult = "retry";
    render();
  }
}

// Dispatch a choice tap/keypress by the current mode's item list.
function activateChoice(idx) {
  const mode = checksumMode();
  if (mode === "pending" || mode === "pendingNoOriginal") {
    if (idx === 0) {
      respondChecksum("confirm");
    } else if (idx === 1) {
      if (mode === "pending") respondChecksum("send_corrected");
      else setView("captions");
    }
    return;
  }
  if (mode === "retry") {
    if (idx === 0) respondChecksum(lastAction);
    else setView("captions");
    return;
  }
  // empty / stale / sending / recorded: the single item goes back.
  setView("captions");
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
      // H-01: Enter activates the focused choice only; it never defaults
      // to "confirm" when the view is not offering card actions.
      activateChoice(selectedChoice);
    }
  }
});

// Tap/click also works (simulator mouse, future touch mapping).
$("choice-confirm").addEventListener("click", () => { selectedChoice = 0; render(); activateChoice(0); });
$("choice-send").addEventListener("click", () => { selectedChoice = 1; render(); activateChoice(1); });
$("checksum-alert").addEventListener("click", () => setView("checksum"));

/* ---------------- boot ---------------- */
// Static chrome that render() never touches (title, alert, row labels,
// footer hint) is filled once from the string table.
$("checksum-alert").textContent = S.alertPending;
$("cs-title").textContent = S.checksumTitle;
$("cs-label-original").textContent = S.labelOriginal;
$("cs-label-heard").textContent = S.labelHeard;
$("cs-footer").textContent = S.footerHint;
render();
setInterval(pollCaptions, POLL_MS);
setInterval(pollChecksum, POLL_MS + 700);
pollCaptions();
setTimeout(pollChecksum, 1200);
