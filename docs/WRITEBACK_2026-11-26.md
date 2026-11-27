# 確認結果のチャット書き戻し（2026-11-26）

確認カードで装着者が「確定」した内容を、元のチャット（Discord / Telegram）へ
投稿する機能。Read-and-write 審査項目およびデモ動画用。

## データフロー

```
話者Aの指示 ─ caption(source, origin 付き) ─┐
                                          ├─ slot diff → 確認カード(pending_card)
話者Bの復唱 ─ caption(source, origin 付き) ─┘   └ instruction / source / origin を保持
        │
        ▼ 装着者が Even G2 で「確認する」
POST /checksum/respond {"id","action":"confirm"}
        │
        ▼ confirm のみ、書き戻しイベントを writeback_events に enqueue
{id, card_id, final_text, source, origin, created_at}
        │
        ▼ 各ボットが自分の source でポーリング
GET /writeback/pending?source=discord|telegram
        │ 投稿成功した id だけ
        ▼
POST /writeback/ack {"ids":[...]}  → キューから削除
```

- `final_text` = 合意版 = カードが保持する元の指示文 `instruction`
  （未取得時はカードの `original` スロット値にフォールバック）。
- `action=send_corrected` は訂正本文を伴わないため書き戻し対象外（記録のみ）。
- `source`/`origin` は caption に乗った値をカードへ引き継ぐ
  （復唱 caption を優先し、なければ指示 caption の値）。

## エンドポイント仕様（backend/core/main.py）

### POST /captions（拡張）
任意フィールド追加: `{"speaker","text","source"?,"origin"?}`。
`source` = `"discord"` / `"telegram"`、`origin` = チャンネルID / chat_id（文字列）。
既存クライアントはフィールド無しで従来通り動作。

### POST /checksum/compare（拡張）
任意フィールド追加: `source?`, `origin?`。
ついでに `original_text` をカードの `instruction`/`source_text` として渡すようにした
（従来は compare 由来カードが常に英語ラベルだったが、日本語指示では日本語ラベルになる）。

### POST /checksum/respond（拡張）
`action:"confirm"` かつ ID 一致時、上記イベントをキューに追加。
戻り値は従来通り `{"status":"ok","action":...}`。

### GET /writeback/pending?source=...
未配送イベントの一覧。`source` 指定時は厳密一致のみ返す
（`source:null` のイベントは無指定呼び出しでのみ返る → 配送先不明のまま残る）。

### POST /writeback/ack {"ids":[...]}
配送済み id をキューから削除。戻り値 `{"status":"ok","acked":<削除数>}`。

## 投稿文の形式

- 日本語文: `✅ 理解チェック確定: 「{final_text}」`
- 英語文:   `✅ Understanding confirmed: "{final_text}"`
- 言語判定は `final_text` 中の仮名・漢字の有無（`checksum.looks_japanese` と同じ正規表現）。
- Discord: 2000 文字上限、Telegram: 4096 文字上限で末尾「…」に切り詰め。

## Discord ボット（backend/discord_bot/receiver.py）

- `CaptionPoster` が caption に `source="discord"`, `origin=<voice channel id>` を付与。
- `WritebackClient` が `/writeback/pending?source=discord` を `WRITEBACK_POLL_SECONDS`
  （デフォルト 5 秒）間隔の asyncio タスクでポーリング。`on_ready` で開始、`close` で停止。
- 投稿先: 接続中ボイスチャンネルのテキストチャット（`channel.send`）。
  イベントの `origin` が別チャンネルIDを指し `get_channel` で解決できる場合はそちらを優先。
- 送信成功したイベントのみ ack。失敗は ack せず次回ポーリングで再送。

## Telegram ボット（backend/telegram_bot/bot.py）

- `post_caption` が `source="telegram"`, `origin=<chat_id>` を付与。
- `post_init` フックで `application.create_task(writeback_loop)` により
  同一イベントループ上の asyncio タスクとしてポーリング
  （`WRITEBACK_POLL_SECONDS`、デフォルト 5 秒）。
  JobQueue は apscheduler 未導入のため使わず `create_task` を採用。
- **chat 特定方法**: イベント `origin`（caption 送信時に記録した chat_id）を最優先。
  `origin` が無い場合は `bot_data["last_confirmation_chat_id"]`
  （`run_checksum` で最後に確認カードを出した chat）にフォールバック。
  どちらも無ければ配送せず pending のまま保持。
- 送信成功のみ ack（at-least-once）。

## 検証結果（2026-11-26 実施）

- `backend/core`: `pytest tests/` 全 37 件パス（既存 29 件 + 新規 8 件、
  `tests/test_writeback.py`）。
- `discord_bot`: `py_compile` + `import receiver` OK、`format_writeback` 日英確認。
- `telegram_bot`: `py_compile` + `import bot` OK、`format_writeback` 日英確認。
- 単体フロー（カード生成 → respond → pending に出る → ack で消える）を
  `test_confirm_queues_writeback_event` / `test_ack_removes_events` で確認済み。
- 実プロセスへの結合確認（Discord/Telegram への実投稿）は未実施。再起動後に実機確認要。

## 追記（2026-11-27）: ライブ検証の実施記録

上記の「未実施」は本レポート作成時点の状態。以下のライブ検証はその後に実施済み：

- **Discord 書き戻し（実投稿）**: 2026-11-26 11:24 JST、MBP 上の実プロセス（backend + receiver）で検証。指示文（佐藤「木曜日までに3部、教務部へ提出をお願いできますか」, source=discord, origin=一般チャンネル）と復唱（田中「金曜日までに…」）を投入 → カード `f7780d477041`（期限 木曜日 vs 金曜日）→ confirm → 書き戻しイベントがキューされ、10秒以内に receiver が「Writeback posted to #一般」をログ出力し、確定文が Discord サーバーの #一般 チャットに実際に投稿されたことを目視確認。検証後に backend を再起動しストアは空に戻した。
- **Telegram 実音声 E2E**: 2026-11-24 夕方、実ボット（understandme_yukilab_bot）＋実音声で検証。挨拶・早口言葉（「隣の客はよくかき食う客だ」）を正確に文字起こし、指示文から deadline=木曜日 / quantity=3部 / destination=教務部 を抽出、確認ボタンまで動作。

## 変更しなかった点・未解決事項

- evenhub / app の UI・文言は未変更。`respond` は「記録」に加え書き戻しも行うが、
  確定表示（"Confirmed" / "確認を記録しました"）は依然として妥当と判断。
- イベントはメモリ内キュー（プロセス再起動で消失）。デモ範囲では許容。
- `source` 不明（caption/compare で未指定）のイベントは各ボットが拾わず滞留する。
  mock_receiver.py は source/origin を送らないため、モック経由のカードは書き戻されない。
- ack 失敗時は次回ポーリングで再投稿＝二重投稿の可能性あり（at-least-once）。
- 同一イベントを複数ボットが同時に拾うケースは未対策（source 厳密一致で回避）。
