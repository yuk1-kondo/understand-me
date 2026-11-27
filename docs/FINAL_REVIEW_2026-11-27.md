# 提出前最終レビュー — Understand Me（2026-11-27）

対象: `README.md` と提出ドラフト（フォーム記述）が実装と一致するかの照合、
Description の英語チェック、デモ動画テロップ文案。
本レビューは読み取り専用で実施（コード・文書の変更なし、`.env` 非接触、プロセス操作なし）。
pytest のみ読み取り目的で実行。

---

## 1. 照合結果

| # | 項目 | 判定 | 根拠 |
|---|---|---|---|
| 1 | Discord への確定内容の書き戻し | **一致（実装あり）** | `backend/core/main.py:363-386`（`GET /writeback/pending`, `POST /writeback/ack`）、`backend/discord_bot/receiver.py:140-180`（`WritebackClient`）、`receiver.py:415-450`（`_writeback_loop` → `channel.send`）、`receiver.py:465-467`（起動）。`confirm` のみイベント化（`main.py:338-352`）。 |
| 2 | Telegram への書き戻し | **一致（実装あり）** | `backend/telegram_bot/bot.py:195-264`（`fetch_pending_writebacks` / `writeback_loop` / `ack_writebacks`）、`bot.py:267-268`（`post_init` で常駐タスク化）。`origin`（chat_id）優先・フォールバックあり（`bot.py:238-240`）。 |
| 3 | 日英バイリンガル（UI） | **一致** | `evenhub/src/main.ts:33-111`（`?lang=` と ja/en `STRINGS`。デフォルト英語）、`app/app.js:16-93`（同構成）、`evenhub/app.json:15`（`supported_languages: ["en","ja"]`）。 |
| 4 | 日英バイリンガル（抽出エンジン） | **一致（ただし未コミット）** | `checksum.py:197-263`（`EnglishExtractor`）、`checksum.py:278-299`（`BilingualExtractor` / `looks_japanese` ルーティング）。**重要**: この英語対応は未コミット差分（`git diff` で +152 行）。HEAD の `checksum.py` には `EnglishExtractor` が存在しない。 → 指摘 P1 |
| 5 | テスト件数「43件」 | **一致（ワークツリー実測）** | `backend/core/.venv/bin/pytest` 実行 → `43 passed in 0.27s`。ただし `tests/test_checksum_en.py`（6件）は **git 未追跡**。コミット済み HEAD 相当は37件。 → 指摘 P1 |
| 6 | 「Claude (internal component)」表記 | **不一致** | Claude は実行時に一切呼ばれない。`checksum.py:298` は `ANTHROPIC_API_KEY` を `_ =` で読み捨てるのみ（将来用リザーブ）。`backend/core/README.md:17` も「future Claude-based extractor」と明記。実行時に実際に呼ばれる判定APIは **Jev**（`jev_judge.py`：`TYPESAFE_API_KEY` 設定時のみ `is_instruction` / `agrees` を HTTP 呼出、`main.py:169,198` から使用）。 → 指摘 P0・修正案あり |
| 7 | README Declaration（事前申告）節 | **概ね一致** | 列挙物は全て現存（`mock_receiver.py`、`docs/DISCORD_SPIKE.md`、`app/` scaffold、`backend/core`、`backend/telegram_bot`、ルールベース checksum）。`docs/BUILD_TODAY.md:4` も「17:00 前の成果は正直に申告」方針と整合。矛盾なし。ただし git 履歴は 2026-11-25 以降の5コミットのみで、作成時刻の客観的裏付けは取れない（時刻自体は**未確認**）。 |
| 8 | faster-whisper large-v3-turbo（ローカル STT） | **一致** | `backend/discord_bot/stt_interface.py:102,109`、`backend/telegram_bot/stt_interface.py:53,60`（`WHISPER_MODEL` デフォルト `large-v3-turbo`、CPU int8）。 |
| 9 | discord.py + discord-ext-voice-recv（DAVE） | **一致** | `backend/discord_bot/requirements.txt`（`discord.py[voice]>=2.7.1`、rdphillips7 フォーク pin、`davey>=0.1,<0.2`）、`receiver.py:50,461`（`voice_recv`、`self_deaf=False`）。 |
| 10 | Even Hub SDK / シミュレータ検証 | **一致** | `evenhub/src/main.ts:11-22`（`@evenrealities/even_hub_sdk` 使用）、`scripts/display_check.py` + `docs/DISPLAY_CHECK.md`（自動フレームバッファ回帰チェック）、`demo-assets/` にシミュレータ framebuffer 実キャプチャ。 |
| 11 | 「Telegram tier validated end-to-end with real voice」 | **未確認** | 実装は存在（`bot.py`）。だがリポジトリ内に実音声 E2E 検証の記録がない。`docs/WRITEBACK_2026-11-26.md:92` は「実プロセスへの結合確認（実投稿）は未実施」。`docs/REVIEW_2026-11-23.md:15` は当時 bot が一度も E2E 動いていなかった旨（現在は修正済）。以後の検証記録ドキュメントなし。 |
| 12 | 「write-back ... verified live on Discord」 | **未確認** | 同上（`docs/WRITEBACK_2026-11-26.md:92`）。実投稿の記録がリポジトリ内に見当たらない。実施済みなら記録追記を推奨。 |
| 13 | `docs/DEMO_SCRIPT.md` / `docs/DEMO_NARRATION_EN.md` | **未確認（ファイル非存在）** | `docs/` に両ファイルが存在しない。`docs/UIUX_REVIEW_CODEX_2026-11-25.md:8` も「`docs/DEMO_SCRIPT.md` は作業ツリーに見当たらなかった」と記録。台本として事実上機能しているのは `demo-assets/CAPTURE_NOTES.md:96-128`（Beat 1–5）。 |
| 14 | GitHub リポジトリとの同期 | **未確認（要対応）** | このクローンに `git remote` が未設定。かつ英語対応の中核（P1）が未コミットのため、公開リポジトリに提出物と同じコードがあるか確認不能。提出フォームは GitHub URL を参照するため要確認。 |
| 15 | README「pytest # 15 tests」 | **不一致（陳腐化）** | `README.md:38`。実測は43件（上記#5）。 |

---

## 2. 指摘リスト（重大度つき）と修正案

### P0 — 技術スタックの Claude 表記が実態と異なる

**現状**: ドラフトは `Claude (internal slot-extraction/comparison component only)`、README.md:28 も同旨。だがランタイムで呼ばれるのは Jev（TypeSafe AI）であり、Claude はコード内で「将来用リザーブ」として変数を読み捨てているだけ。

**根拠**: `checksum.py:291-299`（`get_extractor` は常に `BilingualExtractor` を返す）、`jev_judge.py:108-113`（`TYPESAFE_API_KEY` で有効化）、`main.py:41,169,198`（`judge.is_instruction` / `judge.agrees` を実呼出）。

**修正案（Built with / tech 欄）**:

```
Even Hub SDK (Even G2, simulator-verified), FastAPI, faster-whisper
large-v3-turbo (local STT), discord.py + discord-ext-voice-recv (DAVE),
Telegram Bot API. Slot extraction/comparison is rule-based (offline);
an optional Jev (TypeSafe AI) layer adds instruction/agreement
judgments when TYPESAFE_API_KEY is set.
```

`ANTHROPIC_API_KEY` を使わないまま「Claude を使用」と書くと、審査側がコードを読んだ際に虚偽申告と見なされるリスクがある。Claude を本当に使いたいなら `get_extractor` 内で選択実装が必要（現状は未実装）。

### P1 — 英語対応の中核が未コミット・未追跡

- `backend/core/checksum.py`（`EnglishExtractor` 等 +152 行）… 未コミット変更
- `backend/discord_bot/stt_interface.py`、`backend/telegram_bot/stt_interface.py`（`UM_STT_LANGUAGE` による en/auto 対応）… 未コミット変更
- `backend/core/tests/test_checksum_en.py`（6件）… 未追跡

ワークツリーでは日英対応・43件テストは真だが、HEAD（=GitHub に push される側）では**英語抽出が存在せずテスト37件**。提出物として GitHub コードを審査される場合、バイリンガル主張とコードが食い違う。提出前にコミット＆push（本レビューでは実施しない）。

### P2 — 「実音声 E2E 検証済み」「Discord ライブ検証済み」の裏付けがリポジトリ内にない

`docs/WRITEBACK_2026-11-26.md:92` が「実投稿は未実施」を明示。実施済みなら検証メモを docs に残すか、Description の表現を「実装・単体テスト済み」レベルに弱める（修正案は §3 に反映）。

### P3 — README.md:38 のテスト数が陳腐化

`pytest # 15 tests` → 実測43件。**修正案**: `pytest            # 43 tests`

### P4 — README の TODO 残り

- `README.md:68` `_TODO: link to the demo video (≤ 3 min)._`
- `README.md:90` `License — _TODO._`

提出時に TODO 残しは未完成の印象を与える。動画 URL 確定後に差し替え、License は MIT 等を明記推奨。

### P5 — デモ時の注意（実装上の落とし穴）

`mock_receiver.py` は `source`/`origin` を送らないため、**モック経由で作ったカードは書き戻されない**（`docs/WRITEBACK_2026-11-26.md:100` 記載あり、`demo-assets/CAPTURE_NOTES.md:47-50` の curl 例も `source` 無し）。動画で write-back を見せるには caption POST に `"source":"discord"` 等を付ける、または実ボット経由にする必要がある。

### P6 — `.bak` ファイルが git 追跡されている

`backend/discord_bot/` の `*.bak-20261125` / `*.bak2-20261125`（4件）がコミット済み。公開リポジトリのノイズになるため除外推奨。

### P7 — デモ台本・ナレーション原稿がリポジトリに存在しない

`docs/DEMO_SCRIPT.md` / `docs/DEMO_NARRATION_EN.md` は未作成。§4 のテロップは `CAPTURE_NOTES.md` の Beat 構成を台本代わりにして作成。

### P8 — 軽微な観測メモ（対応不要だが記録）

- `main.py:31` CORS `allow_origins=["*"]`（デモ用途のコメントあり。提出範囲では許容と判断）
- `.env.example` の `STT_API_KEY` はどのコードからも参照されない（`docs/REVIEW_2026-11-23.md:45` L11 指摘の残存）
- `app.json` の whitelist は `localhost:8000` のみ → シミュレータ提出では問題ないが、実機・外部バックエンド構成では届かない

---

## 3. Description 差し替え案（全文）

変更点の要約:
- 「Claude is used solely as an internal AI component」→ 実態に合わせ Jev/ルールベースの記述に修正（P0）
- 「understanding … share the same understanding」の重複解消（step 3）
- 第4パラグラフの冗長な列挙（"transcribed … accurately / correctly pulled … flow works"）を簡潔化
- "(43 backend tests passing)" が display check の括弧に見える構造を分離
- "verified live on Discord" は Telegram 側が未検証のため範囲を限定した正直な表現に（P2）
- "repeat-back" → "restates it"（teach-back と韻を踏みつつ自然な動詞化）

```
Understand Me is an Even G2 app for listeners who are deaf or hard of hearing. It shows speaker-labelled captions from Discord voice channels and Telegram voice messages on the glasses — and then goes one step further.

Live captions solved "can I read what was said?" They did not solve "did I understand it the way the speaker meant?" A misheard deadline — Thursday vs. Friday — is invisible until it becomes a missed delivery.

Understand Me closes that gap with a teach-back loop on the glasses:

1. **Read** — captions from the voice conversation appear on the lens, labelled by speaker.
2. **Check** — when an instruction is given, the app extracts its key points (deadline, quantity, task, destination) and shows a checksum card with only what needs confirming. If the wearer restates it differently, the card highlights the differing slot.
3. **Write** — the confirmed (or corrected) version is posted back to the chat, so both sides share one confirmed record — not an assumption.

The Telegram voice-message tier runs the same loop and was exercised end-to-end with real voice notes: live Whisper transcription, correct extraction of deadline / quantity / destination from a spoken instruction, and the full confirm-button flow. The Even Hub app is verified in the official simulator across the caption → checksum card → response flow, backed by an automated framebuffer regression check and 43 passing backend tests. Confirmed cards are written back to the source chat over a poll/ack queue shared by Discord and Telegram — verified live on Discord.

Only Discord and Telegram are integrated, per Track 01. Slot extraction and comparison are rule-based and run offline; an optional Jev (TypeSafe AI) layer adds instruction/agreement judgments when an API key is present.
```

注: 「exercised end-to-end with real voice notes」「verified live on Discord」は、実際に実施済みの場合のみそのまま使える。未実施なら `exercised` → `implemented`、末尾の `— verified live on Discord` を削ること。

---

## 4. デモ動画テロップ文案（英語・シーン別）

前提: `docs/DEMO_SCRIPT.md` / `docs/DEMO_NARRATION_EN.md` はリポジトリに存在しないため、
`demo-assets/CAPTURE_NOTES.md:96-128`（Beat 1–5）と README の Read→Check→Write 構成を台本代わりにして作成。
無音視聴でも流れが追えるよう、各行は短く・画面上の動作をなぞる記述に統一。
画面の UI が英語ビルド（既定 `en`）ならそのまま、日本語UIで撮る場合は括弧内の日英どちらかに統一する。

| シーン | 目安時間 | 画面（想定） | テロップ案（英語） |
|---|---|---|---|
| S1 導入 | 0:00–0:15 | タイトル／問題提示 | `Understand Me` / `A checksum for human conversation` / `Live captions show what was said —` / `not that you heard it right.` |
| S2 字幕（Beat 1） | 0:15–0:45 | グラス上に話者ラベル付き字幕が流れる | `Discord voice → live captions on Even G2` / `Speaker-labelled, streaming every 2 seconds` |
| S3 指示と聞き違い（Beat 2） | 0:45–1:15 | 「木曜日(Thursday)までに3部」の指示 → 復唱が「金曜日(Friday)」 | `An instruction: "3 copies by Thursday"` / `The wearer repeats: "Friday"` / `Mismatch detected — ▲ confirmation card` |
| S4 チェックサムカード（Beat 3–4） | 1:15–1:55 | カード表示・差分スロットのみ | `The checksum card shows only what differs` / `Said: Thursday   Heard: Friday` / `Tap: Confirm — or record a correction` |
| S5 確定と書き戻し | 1:55–2:20 | 確定 → チャットへ確定文が投稿される | `Confirmed on the glasses` / `The agreed version is posted back to the chat` / `Shared understanding — confirmed, not assumed` |
| S6 Telegram（実演する場合） | 2:20–2:40 | Telegram ボイスメモ→文字起こし→確認ボタン | `Same loop for Telegram voice messages` / `Voice note → transcript → checkpoints → confirm` |
| S7 締め | 2:40–3:00 | ロゴ／まとめ | `Read. Check. Write.` / `Understand Me — Even G2 · Discord · Telegram` / `Track 01 — Messaging & News` |

補足:
- S5 で write-back を見せる場合、P5 のとおり caption に `source`/`origin` が必要。モック字幕のみの撮影では「posted back to the chat」は再現できないので、テロップを `Confirmations can be written back to the source chat` に留める手もある。
- `CAPTURE_NOTES.md` 収録時の画面は日本語UI（理解チェック／指示・復唱）。提出ビルドは英語が既定（`evenhub/src/main.ts:33`）なので、撮影時の言語とテロップ言語は揃えるのが無難。
