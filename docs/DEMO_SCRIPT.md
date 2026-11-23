# デモ動画 台本（3分以内 / Even Hub シミュレータで撮影）

想定視聴者: 審査員。英語字幕＋英語ナレーション（TTS可）。撮影はシミュレータ画面＋バックエンドのターミナルを並べる。

## 構成
- **0:00–0:25 課題**
  ナレーション: "Captions tell you what was said. They don't tell you whether you understood it correctly."
  画面: 金曜夜のDiscordに一人だけ参加できていない様子（イメージ）→ テロップ「60% of deaf and hard-of-hearing people say calls are inaccessible」
- **0:25–0:50 製品紹介**
  "Understand Me adds a checksum to human conversation."
  画面: G2（シミュレータ）に字幕が流れる。名前付き字幕（佐藤／田中）
- **0:50–1:40 本編：指示と聞き違い**
  佐藤（音声）: 「今週の資料なんだけど、木曜日までに3部、教務部へ提出をお願いできますか」
  → 字幕表示。田中（装着者）が復唱: 「金曜日までに3部、教務部へ提出します」
  → チェックサムカードが出現：期限 木曜日（指示） vs 金曜日（復唱）
- **1:40–2:20 確認と書き戻し**
  装着者がカードを開き「正しい内容を送る」を選択 → 確定文がチャットへ返り、佐藤が「ありがとう、その通り」と反応
  テロップ: "Read. Check. Write back. Both sides now share the same understanding."
- **2:20–2:45 Telegram版（保証ライン）**
  ボイスメモでも同じループが回ることを短く見せる（母からのボイスメモ→確認カード→返信）
- **2:45–3:00 締め**
  "Understand Me — because hearing is not the same as understanding."
  Track 01 / Discord + Telegram / リポジトリURL

## 撮影チェックリスト
- [ ] バックエンド起動（uvicorn）＋モック受信 or 実Bot のどちらで回すか決める
- [ ] シミュレータで .ehpk を読み込み、字幕→カード→応答の流れをリハーサル
- [ ] ナレーション原稿の英語化と TTS 生成
- [ ] 3分以内に収まるか通しで計測
