# Understand Me UI/UX 修正記録（2026-11-25）

`docs/UIUX_REVIEW_CODEX_2026-11-25.md` の指摘に対応した修正内容と検証結果。
対象: `evenhub/src/main.ts`、`app/app.js`、`app/index.html`、`backend/telegram_bot/bot.py`、`evenhub/app.json`。
`backend/discord_bot/` は未変更。稼働中プロセスの停止・再起動、`.env`、git push は行っていない。

## 修正内容

### H-04 スロット値 null で描画が落ちないようにする

- `Checksum` 型を `{ original: string | null; heard: string | null }` に変更し、値がない行は「検出できず」と表示する `show()` ヘルパーを両画面に追加。
- 指示側（`original`）の値がないカードは `pendingNoOriginal` モードになり、選択肢が `[確認する][字幕へ戻る]` になり「訂正を記録する」を出さない。`respondChecksum` 側でも `send_corrected` をガード。

### H-01（部分）有効な選択番号があるときだけ確定する

- グラス: カード画面での確定は `listEvent` の `currentSelectItemIndex` が取れたときだけ実行。番号を持たない `sysEvent` タップは pending/retry 中は無視し、既定の「確認」に落とさない（戻る系モードでは字幕へ戻る）。
- カード画面を開くときに表示対象を `viewed` にスナップショット（ID・値を固定）。表示中に別IDのカードが届く、またはカードが消えたら `stale` モードにし、「新しい確認があります」/「この確認は更新されました」を出して古い操作を受け付けない。新カードは字幕へ戻って開き直す。

### H-02（部分）表示を実際の通信結果に合わせる

- 「送信しました」を廃止。POST `/checksum/respond` の結果を見てから表示:
  - `status: "ok"` → 「確認を記録しました」/「訂正を記録しました」（選択肢も「訂正を記録する」に改名）
  - `status: "ignored"` / HTTPエラー / 通信失敗 → カードを残して `[再試行する][字幕へ戻る]` の retry モードへ（state: 未記録）
  - 送信中は「記録しています…」（state: 処理中）
- 自動で字幕に戻る 1.8 秒タイマーは、処理したカードIDと表示中カードが一致し、`recorded` 状態のときだけ発火。新しいカードを消さない。
- 「正しい内容を送る」等の送信系文言を「記録」系に統一（Discord への送信は実装されていないため）。

### H-03 字幕とカードの接続状態を分離

- `backendLive` を `captionsOk` / `cardsOk` に分割。バッジは両方成功時のみ `LIVE`、片方のみ `字幕のみ`/`カードのみ`、一度つながった後の全断は `切断`、最初から未接続のスタンドアロンは `DEMO`。
- ダミー字幕・ダミーカードは「一度もバックエンドに接続していない」場合だけ出す（`captionsEverOk` / `cardsEverOk`）。実字幕へのサンプル追記はしない。
- 一度つながった後の失敗は固定位置のフッターに短く表示: 「字幕更新停止」「確認カード取得不可」「バックエンド切断」。

### H-05 Telegram ボタンにカードIDを持たせる

- `callback_data` を `checksum:confirm:<message_id>` / `checksum:correct:<message_id>` に変更（指示メッセージの ID をカードIDとして使用）。
- 保留中カードとIDが一致するときだけ確定・訂正へ進む。古いボタン・IDなしボタン・保留なしのタップは「この確認は更新されました。最新の確認メッセージを見てください。」をアラートで返し、現在のカードと保留状態は維持する。

### M-06 Telegram のボタンと訂正案内

- ボタンを `[この内容で確定]` `[訂正文を入力]` に変更し、縦に並べて誤タップを減らす。
- 訂正案内を「直した箇所を含めて、指示の全文を送ってください。（元の指示：…）」に変更（差分だけ送ると他スロットが消えるため）。

### L-01 対応言語を実装どおりに

- `evenhub/app.json` の `supported_languages` を `["ja"]` に変更。

### 付随するドキュメント更新

- `evenhub/README.md`、`app/README.md`、`backend/telegram_bot/README.md`、`demo-assets/CAPTURE_NOTES.md` 内の旧文言（送信しました／正しい内容を送る／正しい・直したいボタン）を実装に合わせて更新。

## 検証結果

- `backend/core` のテスト: `.venv/bin/python -m pytest tests -q` → **23件全件パス**
- evenhub: `npm run build`（tsc + vite）成功、`evenhub pack app.json dist -o understand-me.ehpk --sdk-ver 0.0.14` で `.ehpk` 再生成（40,676 bytes）
- `scripts/display_check.py` → **PASS**。字幕ビュー 7,412 lit px、クリック後に確認カードへ遷移（7.9% の画素変化、`木曜日→金曜日` カード確認）。生成画像: `demo-assets/display-check-captions.png` / `display-check-latest.png`（新しい選択肢「訂正を記録する」の描画を目視確認）
- `app/app.js`: `node --check` パス。`evenhub`: `npx tsc --noEmit` パス
- `backend/telegram_bot/bot.py`: `.venv` 上で import チェックのみ実施（稼働中プロセスは停止していない）

## 残した指摘（今回は未対応）

- **M-01** 「他N件」の2件目以降の差分を確認する導線（1画面1差分＋「次の差分へ」）
- **M-02** 字幕の並び（最新を上へ）・話者名の短縮・折り返しの見直し
- **M-03** 長い値で差分箇所が省略記号の後ろに隠れる問題（差分アライン表示）
- **M-04** レンズ起動失敗・接続先違いの画面での切り分け（撮影方式に応じた whitelist 調整）
- **M-05** ブラウザ画面のタッチ復帰・フォーカス操作全体（ネイティブ button 化など）
- **M-06 残り** Telegram の訂正取り消し導線（同じカードに戻す）
- **H-01 残り** 撮影時の「画面の枠／送るID／操作」の一致確認は実機・撮影で行う
- **H-02 残り** `ignored` 時に最新カードを取り直す動線、相手への訂正文配送（チャット送信）は未実装のまま
- **H-03 残り** 前面復帰時の自動再取得
- **L-01 残り** 英語UIの追加（提出後）

## 備考

- 本修正時点でリポジトリに `.git` が存在しなかったため `git init` し、`.gitignore`（`.env`・`.venv`・`node_modules`・`dist` 等を除外）を追加したうえで初回コミットした。`.env` はコミット対象外。
- 稼働中の受信部・バックエンド・Telegram ボットには触れていない。Telegram ボットの変更は次回再起動時に反映される。
