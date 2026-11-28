/* ============================================================
   Understand Me — Even Hub app
   Ported from app/ (plain HTML/CSS demo). Same backend contract:
     GET  /captions          -> { captions: [{speaker,text}] } (bare array also accepted)
     GET  /checksum/latest   -> { id, slot, original, heard } | { checksum } | null
     POST /checksum/respond  <- { id, action: "confirm" | "send_corrected" }
   The glasses render SDK containers, not this page's DOM; the DOM
   below is only a status line visible in the host WebView.
   ============================================================ */

import {
  waitForEvenAppBridge,
  TextContainerProperty,
  TextContainerUpgrade,
  ListContainerProperty,
  ListItemContainerProperty,
  CreateStartUpPageContainer,
  RebuildPageContainer,
  OsEventTypeList,
  type EvenAppBridge,
  type EvenHubEvent,
} from '@evenrealities/even_hub_sdk'

// Backend base URL — overridable at build time (e.g. the display-check
// script builds with VITE_BACKEND_URL=http://localhost:8001).
const BACKEND = (import.meta.env.VITE_BACKEND_URL as string | undefined) || 'http://localhost:8000'
const POLL_MS = 2000

/* ---------------- i18n ----------------
   ?lang=ja keeps the original Japanese UI; anything else — including no
   query at all — falls back to English (submission build default). */
type Lang = 'ja' | 'en'
const LANG: Lang = new URLSearchParams(location.search).get('lang') === 'ja' ? 'ja' : 'en'
document.documentElement.lang = LANG

const STRINGS = {
  ja: {
    notDetected: '検出できず',
    connCaptionsOnly: '字幕のみ',
    connCardsOnly: 'カードのみ',
    connOffline: '切断',
    footerToCard: 'タップ：確認カードへ',
    backendDown: 'バックエンド切断',
    captionsStopped: '字幕更新停止',
    cardsUnavailable: '確認カード取得不可',
    waiting: '会話を待っています',
    alertPending: '▲ 確認カードがあります',
    checksumTitle: '理解チェック',
    fieldLabels: '指示\n復唱',
    emptyCard: '確認が必要な項目はありません',
    stateOk: 'OK',
    stateUpdated: '更新あり',
    stateCheck: '要確認',
    stateSending: '処理中',
    stateRecorded: '記録済',
    stateRetry: '未記録',
    slotNewer: '新しい確認があります',
    slotUpdated: 'この確認は更新されました',
    slotSending: '記録しています…',
    slotRecordedCorrected: '訂正を記録しました',
    slotRecordedConfirmed: '確認を記録しました',
    slotRetry: '記録できませんでした',
    slotCheck: (slot: string, extra: number) =>
      `確認ポイント：${slot}${extra > 0 ? `　他${extra}件` : ''}`,
    footerSelect: '↑↓：選択　タップ：決定',
    footerBack: 'タップ：字幕へ戻る',
    choices: {
      pending: ['確認する', '訂正を記録する'],
      pendingNoOriginal: ['確認する', '字幕へ戻る'],
      retry: ['再試行する', '字幕へ戻る'],
      back: ['字幕へ戻る'],
    },
  },
  en: {
    notDetected: 'not detected',
    connCaptionsOnly: 'captions only',
    connCardsOnly: 'cards only',
    connOffline: 'OFFLINE',
    footerToCard: 'Tap: view card',
    backendDown: 'backend offline',
    captionsStopped: 'captions stopped',
    cardsUnavailable: 'cards unavailable',
    waiting: 'Waiting for speech',
    alertPending: '▲ Confirmation card',
    checksumTitle: 'Double-check',
    fieldLabels: 'Said\nHeard',
    emptyCard: 'Nothing to confirm',
    stateOk: 'OK',
    stateUpdated: 'Updated',
    stateCheck: 'Check',
    stateSending: 'Saving',
    stateRecorded: 'Saved',
    stateRetry: 'Failed',
    slotNewer: 'Newer card pending',
    slotUpdated: 'This card was updated',
    slotSending: 'Recording…',
    slotRecordedCorrected: 'Correction recorded',
    slotRecordedConfirmed: 'Confirmed',
    slotRetry: 'Recording failed',
    slotCheck: (slot: string, extra: number) =>
      `Check: ${slot}${extra > 0 ? ` +${extra} more` : ''}`,
    footerSelect: 'Scroll: select  Tap: OK',
    footerBack: 'Tap: back',
    choices: {
      pending: ['Confirm', 'Record correction'],
      pendingNoOriginal: ['Confirm', 'Back to captions'],
      retry: ['Retry', 'Back to captions'],
      back: ['Back to captions'],
    },
  },
}
const S = STRINGS[LANG]

/* ---------------- dummy data (standalone demo) ---------------- */
const DUMMY_CAPTIONS =
  LANG === 'ja'
    ? [
        { speaker: '田中さん', text: 'じゃあ来週の資料の件だけど' },
        { speaker: '田中さん', text: '木曜日までに、3部' },
        { speaker: '田中さん', text: '教務部へ提出をお願いできる？' },
        { speaker: '佐藤さん', text: '了解、木曜日ですね' },
        { speaker: '田中さん', text: 'そう、木曜の午後3時まで' },
      ]
    : [
        { speaker: 'Tanaka', text: "About next week's handout" },
        { speaker: 'Tanaka', text: 'I need 3 copies by Thursday' },
        { speaker: 'Tanaka', text: 'submitted to the office, OK?' },
        { speaker: 'Sato', text: 'Got it, Thursday' },
        { speaker: 'Tanaka', text: 'Right, Thursday by 3pm' },
      ]
const DUMMY_CHECKSUM =
  LANG === 'ja'
    ? { id: 'demo-1', slot: '期限', original: '木曜日', heard: '金曜日' }
    : { id: 'demo-1', slot: 'deadline', original: 'Thursday', heard: 'Friday' }

/* ---------------- display rules (docs/UX_REVIEW_2026-11-23.md) ---------
   Firmware font: ~27px line pitch, ~24 full-width glyphs per 576px row.
   A text container must be taller than its content or LVGL clips it and
   draws a scroll nub — so every string gets clipped to its line budget. */
const LINE = 24
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s)
/* Caption layout (docs/UX_COMFORT_2026-11-25.md): the latest utterance is
   pinned at the optical center of the 288px lens (y ~130-200); up to
   HISTORY_MAX dimmed rows flow upward above it. Speaker names never eat
   the body budget — history prefixes cap the name at SPEAKER_MAX glyphs
   and the latest row gets its own dim name line (LATEST_NAME_MAX). */
const HISTORY_MAX = 2
const SPEAKER_MAX = 6
const LATEST_NAME_MAX = 10
// Slot values the backend could not extract arrive as null (H-04).
const show = (s: string | null | undefined) => (s ? clip(s, LINE - 4) : S.notDetected)

/* ---------------- state (mirrors app/app.js) ---------------- */
type View = 'captions' | 'checksum'
type Checksum = { id: string; slot: string; original: string | null; heard: string | null; diffs?: unknown[] }
type CsResult = 'pending' | 'sending' | 'recorded' | 'retry'
type CsMode = 'empty' | 'pending' | 'pendingNoOriginal' | 'sending' | 'recorded' | 'retry' | 'stale'

let view: View = 'captions'
// H-03: captions and checksum cards have separate liveness so one failing
// endpoint cannot mask the other.
let captionsOk = false
let cardsOk = false
let captionsEverOk = false // once real data arrived, never fall back to dummies
let cardsEverOk = false
let captions: { speaker: string; text: string }[] = []
let dummyIdx = 0
let checksum: Checksum | null = null // latest card from the backend
let checksumHandled = false // latest card already recorded by this app
// H-01: the card under review is frozen on view entry so a newer card
// arriving mid-review can never be acted on by stale input.
let viewed: Checksum | null = null
let viewedStale = false
let viewedResult: CsResult = 'pending'
let lastAction: 'confirm' | 'send_corrected' = 'confirm'
let csMode: CsMode = 'empty' // last-rendered checksum layout
let exited = false // true once the system exit dialog is up; stop updating dead containers

let bridge: EvenAppBridge

const statusEl = document.getElementById('app-status')
const setStatus = (s: string) => {
  if (statusEl) statusEl.textContent = `Understand Me — ${s}`
}

/* ---------------- container helpers ---------------- */
const text = (p: Partial<TextContainerProperty>) => new TextContainerProperty(p)

/* ---------------- connection status (H-03) ---------------- */
const connLabel = () => {
  if (captionsOk && cardsOk) return 'LIVE'
  if (captionsOk) return S.connCaptionsOnly
  if (cardsOk) return S.connCardsOnly
  return captionsEverOk || cardsEverOk ? S.connOffline : 'DEMO'
}

const captionFooter = (pending: boolean) => {
  if (pending) return S.footerToCard
  const capDown = captionsEverOk && !captionsOk
  const cardDown = cardsEverOk && !cardsOk
  if (capDown && cardDown) return S.backendDown
  if (capDown) return S.captionsStopped
  if (cardDown) return S.cardsUnavailable
  return ' '
}

function captionPage(): { textObject: TextContainerProperty[] } {
  const pending = !!(checksum && !checksumHandled)
  // Gaze guidance: while a card waits, the caption side drops one
  // brightness step so the alert (and the card behind it) stays the
  // brightest thing on the lens. Steady level — never blinking.
  const dim = (base: number) => Math.max(1, base - (pending ? 1 : 0))
  const shown = captions.slice(-(HISTORY_MAX + 1))
  const history = shown
    .slice(0, -1)
    .map((c) => clip(`${clip(c.speaker, SPEAKER_MAX)}: ${c.text}`, LINE))
    .join('\n')
  const latest = shown.at(-1)
  return {
    textObject: [
      text({ xPosition: 0, yPosition: 0, width: 400, height: 36, paddingLength: 4, containerID: 1, containerName: 'header', content: 'Understand Me' }),
      text({ xPosition: 400, yPosition: 0, width: 172, height: 36, paddingLength: 4, containerID: 2, containerName: 'conn', content: connLabel(), textColor: 2 }),
      text({ xPosition: 0, yPosition: 40, width: 576, height: 64, paddingLength: 4, containerID: 3, containerName: 'hist', content: history || ' ', textColor: dim(2) }),
      text({ xPosition: 0, yPosition: 104, width: 576, height: 36, paddingLength: 4, containerID: 4, containerName: 'spk', content: latest ? clip(latest.speaker, LATEST_NAME_MAX) : ' ', textColor: dim(2) }),
      text({ xPosition: 0, yPosition: 140, width: 576, height: 66, paddingLength: 4, containerID: 5, containerName: 'capnew', content: latest ? clip(latest.text, LINE * 2 - 4) : S.waiting, textColor: dim(4), isEventCapture: 1 }),
      text({ xPosition: 0, yPosition: 210, width: 576, height: 38, paddingLength: 4, containerID: 6, containerName: 'alert', content: pending ? S.alertPending : ' ' }),
      text({ xPosition: 0, yPosition: 250, width: 576, height: 38, paddingLength: 4, containerID: 7, containerName: 'footer', content: captionFooter(pending), textColor: 2 }),
    ],
  }
}

function checksumMode(): CsMode {
  if (!viewed) return 'empty'
  if (viewedStale) return 'stale'
  if (viewedResult !== 'pending') return viewedResult
  // H-04: with no instruction-side value there is nothing to correct
  // against, so the correction action must not be offered.
  return viewed.original ? 'pending' : 'pendingNoOriginal'
}

const CHOICE_ITEMS: Record<CsMode, string[]> = {
  pending: [...S.choices.pending],
  pendingNoOriginal: [...S.choices.pendingNoOriginal],
  retry: [...S.choices.retry],
  empty: [...S.choices.back],
  stale: [...S.choices.back],
  sending: [...S.choices.back],
  recorded: [...S.choices.back],
}

function checksumFields(): { slot: string; labels: string; values: string; state: string; slotColor: number } {
  const mode = checksumMode()
  if (mode === 'empty') {
    return { slot: S.emptyCard, labels: ' ', values: ' ', state: S.stateOk, slotColor: 3 }
  }
  const c = viewed!
  const labels = S.fieldLabels
  const values = `${show(c.original)}\n${show(c.heard)}`
  switch (mode) {
    case 'stale':
      return {
        slot: checksum && checksum.id !== c.id ? S.slotNewer : S.slotUpdated,
        labels, values, state: S.stateUpdated, slotColor: 3,
      }
    case 'sending':
      return { slot: S.slotSending, labels, values, state: S.stateSending, slotColor: 3 }
    case 'recorded':
      return {
        slot: lastAction === 'send_corrected' ? S.slotRecordedCorrected : S.slotRecordedConfirmed,
        labels, values, state: S.stateRecorded, slotColor: 4,
      }
    case 'retry':
      return { slot: S.slotRetry, labels, values, state: S.stateRetry, slotColor: 3 }
    default: {
      const extra = (c.diffs?.length ?? 1) - 1
      return {
        slot: S.slotCheck(c.slot, extra),
        labels, values, state: S.stateCheck, slotColor: 3,
      }
    }
  }
}

function checksumPage(): RebuildPageContainer {
  const mode = checksumMode()
  const items = CHOICE_ITEMS[mode]
  const f = checksumFields()
  const selectable = mode === 'pending' || mode === 'pendingNoOriginal' || mode === 'retry'
  return new RebuildPageContainer({
    containerTotalNum: 7,
    textObject: [
      text({ xPosition: 0, yPosition: 0, width: 400, height: 36, paddingLength: 4, containerID: 1, containerName: 'header', content: S.checksumTitle }),
      text({ xPosition: 400, yPosition: 0, width: 172, height: 36, paddingLength: 4, containerID: 2, containerName: 'csstate', content: f.state, textColor: 3 }),
      text({ xPosition: 0, yPosition: 40, width: 576, height: 38, paddingLength: 4, containerID: 3, containerName: 'slot', content: f.slot, textColor: f.slotColor }),
      text({ xPosition: 0, yPosition: 82, width: 96, height: 64, paddingLength: 4, containerID: 4, containerName: 'labels', content: f.labels, textColor: 2 }),
      text({ xPosition: 100, yPosition: 82, width: 476, height: 64, paddingLength: 4, containerID: 5, containerName: 'values', content: f.values }),
      text({ xPosition: 0, yPosition: 244, width: 576, height: 38, paddingLength: 4, containerID: 6, containerName: 'footer', content: selectable ? S.footerSelect : S.footerBack, textColor: 2 }),
    ],
    listObject: [
      new ListContainerProperty({
        xPosition: 0,
        yPosition: 150,
        width: 576,
        height: 90,
        paddingLength: 4,
        containerID: 7,
        containerName: 'choices',
        isEventCapture: 1,
        itemContainer: new ListItemContainerProperty({
          itemCount: items.length,
          itemWidth: 576,
          isItemSelectBorderEn: 1,
          itemName: items,
        }),
      }),
    ],
  })
}

/* ---------------- rendering ---------------- */
// Updates go through TextContainerUpgrade only, and a container is sent
// again only when its content or brightness actually changed — settled
// lines are never re-rendered, so a poll cycle causes no flicker.
const BRIGHTNESS_DEFAULT = 4 // device default when textColor is omitted
const sentContent = new Map<number, { content: string; color: number }>()

function upgrade(containerID: number, containerName: string, content: string, color?: number) {
  const c = color ?? BRIGHTNESS_DEFAULT
  const prev = sentContent.get(containerID)
  if (prev && prev.content === content && prev.color === c) return
  sentContent.set(containerID, { content, color: c })
  bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID, containerName, content, textColor: c }))
}

// A page create/rebuild rewrites every container, so the cache must be
// reseeded with exactly what was sent or the diffing goes stale.
function rememberPage(texts: TextContainerProperty[] | undefined) {
  sentContent.clear()
  for (const t of texts ?? []) {
    if (t.containerID !== undefined) {
      sentContent.set(t.containerID, { content: t.content ?? '', color: t.textColor ?? BRIGHTNESS_DEFAULT })
    }
  }
}

function render() {
  if (exited) return
  if (view === 'captions') {
    // flicker-free in-place updates; layout never changes on this view
    for (const t of captionPage().textObject) {
      upgrade(t.containerID!, t.containerName!, t.content ?? '', t.textColor)
    }
  } else {
    const mode = checksumMode()
    if (mode !== csMode) {
      // list items change per mode -> full rebuild required
      csMode = mode
      const page = checksumPage()
      bridge.rebuildPageContainer(page)
      rememberPage(page.textObject)
    } else {
      const f = checksumFields()
      upgrade(2, 'csstate', f.state, 3)
      upgrade(3, 'slot', f.slot, f.slotColor)
      upgrade(4, 'labels', f.labels, 2)
      upgrade(5, 'values', f.values)
    }
  }
  setStatus(`${view} | ${connLabel()} | checksum:${checksumMode()}`)
}

async function setView(next: View) {
  view = next
  if (next === 'captions') {
    viewed = null
    viewedStale = false
    viewedResult = 'pending'
    const page = captionPage()
    await bridge.rebuildPageContainer(
      new RebuildPageContainer({ containerTotalNum: page.textObject.length, textObject: page.textObject }),
    )
    rememberPage(page.textObject)
  } else {
    // Freeze the card under review (H-01): polls keep updating `checksum`,
    // but this view and its actions only ever see the frozen snapshot.
    viewed = checksum ? { ...checksum } : null
    viewedStale = false
    viewedResult = 'pending'
    csMode = checksumMode()
    const page = checksumPage()
    await bridge.rebuildPageContainer(page)
    rememberPage(page.textObject)
  }
  setStatus(`${view} | ${connLabel()}`)
}

/* ---------------- backend polling (contract unchanged) ---------------- */
async function fetchJSON(path: string) {
  const res = await fetch(BACKEND + path, { cache: 'no-store' })
  if (!res.ok) throw new Error(String(res.status))
  return res.json()
}

async function pollCaptions() {
  try {
    const data = await fetchJSON('/captions')
    // Contract: { captions: [...] }; the current backend also serves a bare array.
    const list = Array.isArray(data?.captions) ? data.captions : Array.isArray(data) ? data : null
    if (list) captions = list
    captionsOk = true
    captionsEverOk = true
  } catch {
    captionsOk = false
    // H-03: dummy captions are a standalone-demo fallback only. Once real
    // captions arrived, a failed poll must never append sample lines.
    if (!captionsEverOk && dummyIdx < DUMMY_CAPTIONS.length) captions.push(DUMMY_CAPTIONS[dummyIdx++])
  }
  render()
}

async function pollChecksum() {
  try {
    const data = await fetchJSON('/checksum/latest')
    const cs = data && (data.checksum !== undefined ? data.checksum : data)
    if (cs && cs.id !== checksum?.id) {
      checksum = cs
      checksumHandled = false
    } else if (!cs) {
      checksum = null
      checksumHandled = false
    }
    cardsOk = true
    cardsEverOk = true
  } catch {
    cardsOk = false
    // H-03: same standalone-only rule for the demo checksum card.
    if (!cardsEverOk && !checksum && dummyIdx >= 3) {
      checksum = DUMMY_CHECKSUM
      checksumHandled = false
    }
  }
  // H-01: while a frozen card is under review, a different card arriving
  // (or this one disappearing) marks the view stale so old input cannot
  // act on a card the wearer never saw.
  if (viewed && (viewedResult === 'pending' || viewedResult === 'retry')) {
    if (!checksum || checksum.id !== viewed.id) viewedStale = true
  }
  render()
}

/* ---------------- checksum response ---------------- */
// H-02: report the POST result, not optimism. Only status:"ok" counts as
// recorded; "ignored" means the backend moved on to a different card, and
// any failure leaves the card up for retry.
async function respondChecksum(action: 'confirm' | 'send_corrected') {
  if (!viewed || viewedStale) return
  if (viewedResult !== 'pending' && viewedResult !== 'retry') return
  if (action === 'send_corrected' && !viewed.original) return
  const card = viewed
  lastAction = action
  viewedResult = 'sending'
  render()

  let outcome: 'ok' | 'ignored' | 'failed'
  try {
    const res = await fetch(BACKEND + '/checksum/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: card.id, action }),
    })
    if (!res.ok) {
      outcome = 'failed'
    } else {
      const data = await res.json().catch(() => null)
      outcome = data?.status === 'ok' ? 'ok' : data?.status === 'ignored' ? 'ignored' : 'failed'
    }
  } catch {
    outcome = 'failed'
  }

  if (outcome === 'ok' && checksum?.id === card.id) checksumHandled = true
  if (view !== 'checksum' || viewed?.id !== card.id) {
    render() // wearer left mid-flight; just keep the captions alert honest
    return
  }
  if (outcome === 'ok') {
    viewedResult = 'recorded'
    render()
    const id = card.id
    // H-02: the auto-return timer applies only to the card we processed —
    // a newer card that arrived meanwhile is never cleared by this timer.
    setTimeout(() => {
      if (view === 'checksum' && viewed?.id === id && viewedResult === 'recorded') {
        if (checksum?.id === id) checksum = null
        setView('captions')
      }
    }, 1800)
  } else if (outcome === 'ignored') {
    viewedStale = true
    render()
  } else {
    viewedResult = 'retry'
    render()
  }
}

/* ---------------- input: G2 touchpad / R1 ring ---------------- */
function onEvent(event: EvenHubEvent) {
  const t = event.textEvent
  const l = event.listEvent
  const s = event.sysEvent
  const et = t?.eventType ?? l?.eventType ?? s?.eventType
  exited = false // any new event means the page is still alive (e.g. exit dialog cancelled)

  // Double press anywhere on the root page -> system exit dialog (required by QA).
  if (et === OsEventTypeList.DOUBLE_CLICK_EVENT) {
    exited = true
    bridge.shutDownPageContainer(1)
    return
  }

  // Tap arrives as a sysEvent carrying only eventSource on simulator 0.9.x:
  // eventType is normalized to undefined, so "click" = click OR undefined.
  const isClick = et === OsEventTypeList.CLICK_EVENT || et === undefined

  if (view === 'captions') {
    if (isClick && !l) setView('checksum')
    return
  }

  if (view === 'checksum') {
    if (l && et === OsEventTypeList.SCROLL_TOP_EVENT) {
      setView('captions')
      return
    }
    if (isClick) {
      // H-01: a card action runs only when the tap carries a real selection
      // index from the choices list. A sysEvent tap carries no index and
      // must never fall through to "confirm".
      if (l && typeof l.currentSelectItemIndex === 'number') {
        onChecksumChoice(l.currentSelectItemIndex)
      } else if (l) {
        // Simulator compat: the Even Hub simulator (0.9.x) strips eventType
        // and currentSelectItemIndex from list events — real G2 firmware
        // always sends a numeric index — which would make cards impossible
        // to confirm in the simulator at all. Treat a list tap without an
        // index as a tap on the first (focused) item. The H-01 guard above
        // still applies to sysEvent taps, and hardware behavior is unchanged.
        onChecksumChoice(0)
      } else {
        const mode = checksumMode()
        if (mode !== 'pending' && mode !== 'pendingNoOriginal' && mode !== 'retry') {
          setView('captions')
        }
      }
    }
  }
}

// Dispatch a focused-list tap by the current mode's item list.
function onChecksumChoice(idx: number) {
  const mode = checksumMode()
  if (mode === 'pending' || mode === 'pendingNoOriginal') {
    if (idx === 0) {
      respondChecksum('confirm')
    } else if (idx === 1) {
      if (mode === 'pending') respondChecksum('send_corrected')
      else setView('captions')
    }
    return
  }
  if (mode === 'retry') {
    if (idx === 0) respondChecksum(lastAction)
    else setView('captions')
    return
  }
  // empty / stale / sending / recorded: the single item goes back.
  if (idx === 0) setView('captions')
}

/* ---------------- boot ---------------- */
const bridgeReady = await waitForEvenAppBridge()
bridge = bridgeReady

const page = captionPage()
const result = await bridge.createStartUpPageContainer(
  new CreateStartUpPageContainer({
    containerTotalNum: page.textObject.length,
    textObject: page.textObject,
  }),
)
if (result !== 0) console.error('createStartUpPageContainer failed:', result)
else rememberPage(page.textObject)

bridge.onEvenHubEvent(onEvent)
console.log('[understand-me] ready')

setInterval(pollCaptions, POLL_MS)
setInterval(pollChecksum, POLL_MS + 700)
pollCaptions()
setTimeout(pollChecksum, 1200)
