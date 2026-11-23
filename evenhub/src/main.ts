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

const BACKEND = 'http://localhost:8000'
const POLL_MS = 2000

/* ---------------- dummy data (standalone demo) ---------------- */
const DUMMY_CAPTIONS = [
  { speaker: '田中さん', text: 'じゃあ来週の資料の件だけど' },
  { speaker: '田中さん', text: '木曜日までに、3部' },
  { speaker: '田中さん', text: '教務部へ提出をお願いできる？' },
  { speaker: '佐藤さん', text: '了解、木曜日ですね' },
  { speaker: '田中さん', text: 'そう、木曜の午後3時まで' },
]
const DUMMY_CHECKSUM = { id: 'demo-1', slot: '期限', original: '木曜日', heard: '金曜日' }

/* ---------------- state (mirrors app/app.js) ---------------- */
type View = 'captions' | 'checksum'
type Checksum = { id: string; slot: string; original: string; heard: string }

let view: View = 'captions'
let backendLive = false
let captions: { speaker: string; text: string }[] = []
let dummyIdx = 0
let checksum: Checksum | null = null
let checksumHandled = false
let csMode: 'pending' | 'empty' | 'done' = 'empty' // last-rendered checksum layout
let exited = false // true once the system exit dialog is up; stop updating dead containers

let bridge: EvenAppBridge

const statusEl = document.getElementById('app-status')
const setStatus = (s: string) => {
  if (statusEl) statusEl.textContent = `Understand Me — ${s}`
}

/* ---------------- container helpers ---------------- */
const text = (p: Partial<TextContainerProperty>) => new TextContainerProperty(p)

function captionPage(): { textObject: TextContainerProperty[] } {
  const shown = captions.slice(-4)
  const older = shown
    .slice(0, -1)
    .map((c) => `${c.speaker}: ${c.text}`)
    .join('\n')
  const latest = shown.length ? `${shown.at(-1)!.speaker}: ${shown.at(-1)!.text}` : ' '
  const footer =
    (checksum && !checksumHandled ? '▲ 確認カードがあります\n' : '') + 'タップ：確認カードへ'
  return {
    textObject: [
      text({ xPosition: 0, yPosition: 0, width: 400, height: 30, paddingLength: 4, containerID: 1, containerName: 'header', content: 'Understand Me' }),
      text({ xPosition: 400, yPosition: 0, width: 172, height: 30, paddingLength: 4, containerID: 2, containerName: 'conn', content: backendLive ? 'LIVE' : 'DEMO', textColor: 2 }),
      text({ xPosition: 0, yPosition: 34, width: 576, height: 150, paddingLength: 4, containerID: 3, containerName: 'capold', content: older || ' ', textColor: 2, isEventCapture: 1 }),
      text({ xPosition: 0, yPosition: 186, width: 576, height: 60, paddingLength: 4, containerID: 4, containerName: 'capnew', content: latest }),
      text({ xPosition: 0, yPosition: 250, width: 576, height: 38, paddingLength: 4, containerID: 5, containerName: 'footer', content: footer, textColor: 3 }),
    ],
  }
}

function checksumMode(): 'pending' | 'empty' | 'done' {
  if (checksumHandled) return 'done'
  return checksum ? 'pending' : 'empty'
}

function checksumCardText(): string {
  if (checksumHandled) return '送信しました'
  if (!checksum) return '確認が必要な項目はありません'
  return `確認ポイント：${checksum.slot}\n指示：${checksum.original}\n復唱：${checksum.heard}`
}

function checksumPage(): RebuildPageContainer {
  const pending = checksum && !checksumHandled
  const items = pending ? ['確認する', '正しい内容を送る'] : ['字幕へ戻る']
  return new RebuildPageContainer({
    containerTotalNum: 5,
    textObject: [
      text({ xPosition: 0, yPosition: 0, width: 400, height: 30, paddingLength: 4, containerID: 1, containerName: 'header', content: '理解チェック' }),
      text({ xPosition: 400, yPosition: 0, width: 172, height: 30, paddingLength: 4, containerID: 2, containerName: 'csstate', content: pending ? '要確認' : 'OK', textColor: 2 }),
      text({ xPosition: 0, yPosition: 34, width: 576, height: 140, paddingLength: 4, containerID: 3, containerName: 'card', content: checksumCardText() }),
      text({ xPosition: 0, yPosition: 264, width: 576, height: 24, paddingLength: 4, containerID: 5, containerName: 'footer', content: '↑↓：選択　タップ：決定', textColor: 2 }),
    ],
    listObject: [
      new ListContainerProperty({
        xPosition: 0,
        yPosition: 178,
        width: 576,
        height: 82,
        paddingLength: 4,
        containerID: 4,
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
const upgrade = (containerID: number, containerName: string, content: string) =>
  bridge.textContainerUpgrade(new TextContainerUpgrade({ containerID, containerName, content }))

function render() {
  if (exited) return
  if (view === 'captions') {
    const page = captionPage().textObject
    // flicker-free in-place updates; layout never changes on this view
    upgrade(2, 'conn', page[1].content!)
    upgrade(3, 'capold', page[2].content!)
    upgrade(4, 'capnew', page[3].content!)
    upgrade(5, 'footer', page[4].content!)
  } else {
    const mode = checksumMode()
    if (mode !== csMode) {
      // list items change per mode -> full rebuild required
      csMode = mode
      bridge.rebuildPageContainer(checksumPage())
    } else {
      upgrade(2, 'csstate', checksum && !checksumHandled ? '要確認' : 'OK')
      upgrade(3, 'card', checksumCardText())
    }
  }
  setStatus(`${view} | ${backendLive ? 'LIVE' : 'DEMO'} | checksum:${checksumMode()}`)
}

async function setView(next: View) {
  view = next
  if (next === 'captions') {
    const page = captionPage()
    await bridge.rebuildPageContainer(
      new RebuildPageContainer({ containerTotalNum: page.textObject.length, textObject: page.textObject }),
    )
  } else {
    csMode = checksumMode()
    await bridge.rebuildPageContainer(checksumPage())
  }
  setStatus(`${view} | ${backendLive ? 'LIVE' : 'DEMO'}`)
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
    if (list) {
      captions = list
      backendLive = true
    }
  } catch {
    backendLive = false
    if (dummyIdx < DUMMY_CAPTIONS.length) captions.push(DUMMY_CAPTIONS[dummyIdx++])
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
    backendLive = true
  } catch {
    if (!checksum && dummyIdx >= 3) {
      checksum = DUMMY_CHECKSUM
      checksumHandled = false
    }
  }
  render()
}

/* ---------------- checksum response ---------------- */
async function respondChecksum(action: 'confirm' | 'send_corrected') {
  if (!checksum || checksumHandled) return
  checksumHandled = true
  render()
  try {
    await fetch(BACKEND + '/checksum/respond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: checksum.id, action }),
    })
  } catch {
    // standalone demo: nothing to send to
  }
  setTimeout(() => {
    checksum = null
    checksumHandled = false
    setView('captions')
  }, 1800)
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
      if (checksum && !checksumHandled) {
        // Prefer the focused list item; sysEvent clicks carry no index -> confirm.
        const idx = l?.currentSelectItemIndex ?? 0
        respondChecksum(idx === 1 ? 'send_corrected' : 'confirm')
      } else {
        setView('captions')
      }
    }
  }
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

bridge.onEvenHubEvent(onEvent)
console.log('[understand-me] ready')

setInterval(pollCaptions, POLL_MS)
setInterval(pollChecksum, POLL_MS + 700)
pollCaptions()
setTimeout(pollChecksum, 1200)
