# 安定化：メモリ内データの保持上限（2026-11-26）

長時間稼働でも古いデータが残らないよう、backend/core のインメモリ状態に
上限・有効期限を追加した。デモ中に前日の字幕・カード・書き戻しが
出てこないようにするための対策。対象は `backend/core` のみ、
外部のレスポンス形式は変更なし。

## 仕様

| 対象 | 上限・期限 | 環境変数 | デフォルト |
|---|---|---|---|
| 字幕ストア（`CaptionStore`） | 最新 N 件のみ保持。超過分は古い順に破棄 | `UM_CAPTION_MAX` | 200 件 |
| 保留中の確認カード（`pending_card`） | 作成から失効。`GET /checksum/latest` で返さず、`POST /checksum/respond` も `{"status":"ignored"}` で受け付けない | `UM_CARD_TTL_SECONDS` | 1800 秒（30 分） |
| 未配送の書き戻しイベント（`writeback_events`） | `created_at` から失効。`GET /writeback/pending` で返さずキューから破棄 | `UM_WRITEBACK_TTL_SECONDS` | 3600 秒（1 時間） |

- 環境変数が未設定・非数値・0 以下の場合はデフォルト値を使用。
- 失効処理は既存エンドポイントの流れの中で行う:
  - 字幕: `add()` 時に `deque(maxlen=N)` が自動で古いものを捨てる。
  - カード: `latest` / `respond` 呼び出し時に作成時刻を検査して失効。
  - 書き戻し: `pending` 呼び出し時（および `respond` での enqueue 時）に
    期限切れイベントをキューから削除。`created_at` が欠損・解釈不能な
    イベントは期限切れとして破棄。
- タイムスタンプは内部状態のみで、`/checksum/latest` のカード形状など
  レスポンス形式には手を加えていない。

## 変更ファイル

- `backend/core/captions.py` — `CaptionStore` を `deque(maxlen=)` 化。
  `max_items` 引数または `UM_CAPTION_MAX` で上限指定。
- `backend/core/main.py` — `CARD_TTL` / `WRITEBACK_TTL` 定数、
  `pending_card_created_at`、失効・破棄ヘルパーを追加し、
  `latest` / `respond` / `writeback/pending` 各エンドポイントに組み込み。
- `backend/core/tests/test_stability.py` — 新規テスト 6 件。

## 検証結果

`cd backend/core && .venv/bin/python -m pytest -q`

- 43 件すべてパス（既存 37 件 + 新規 6 件）。
- 新規テストで確認した内容:
  - `CaptionStore(max_items=3)` に 5 件追加 → 最新 3 件のみ残る。
  - `UM_CAPTION_MAX=2` で構築したストアは 2 件に丸められる。
  - カード作成時刻を TTL 以前に遡らせると `latest` が `null` を返し、
    `respond` も `ignored` になる（書き戻しも積まれない）。
  - 期限切れの書き戻しイベントは `pending` に出ず、
    `writeback_events` から物理的に削除される。
  - 期限前のカード・書き戻しは従来通り返ることを確認。
