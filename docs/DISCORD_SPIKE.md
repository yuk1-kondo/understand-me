# Discord 音声受信スパイク — レシピと手順

目的: DAVE（E2EE）必須化後の Discord ボイスチャンネルで、Bot が他人の発話音声を受信し、話者別に PCM を得られることを実証する。
背景: Discord の音声はグラス／シミュレータを通らない。Bot がサーバー側で受信→STT→字幕キューへ流し、アプリは文字を表示するだけ。このスパイクが Understand Me 本線の成否を決める。

## 本日の検証結果（2026-11-23 追記）

実環境でのスパイクを実施し、**ログイン／ボイス参加／DAVE ハンドシェイクは全て成功**。Bot はチャンネルに接続でき、受信パイプラインまで到達した。一方で依存関係に2件の破損を確認し、以下の通り対処した：

- **davey 0.2.0 は壊れている。** transition/key まわりの API 変更で DAVE セッションが成立しない。venv は `davey==0.1.6` で動作確認済み。`requirements.txt` は `davey>=0.1,<0.2` にピン留めした（0.2 系は API を再検証してから上げる）。
- **PR #54 は復号バグあり。** imayhaveborkedit/discord-ext-voice-recv PR #54 には二重復号（double-decryption）バグがあり、デコード結果がノイズ化する。venv は修正済みの **rdphillips7 フォーク**（github.com/rdphillips7/discord-ext-voice-recv）に差し替え、`requirements.txt` も同フォークを参照するよう更新した。
- **デコード後音声の品質は最終再テスト待ち。** フォーク差し替え後の PCM で Whisper 書き起こし品質を確認するリテストが残っている。STT 本体は実装済み：faster-whisper `large-v3-turbo`（ローカル、CPU int8）、`STT_PROVIDER=whisper` で有効化（discord_bot / telegram_bot 両方の stt_interface）。

## 確認済みの前提（2026-11-21 調査）
- 2026-03-02 に DAVE が全ボイスチャンネルで必須化。旧来の受信方法は全滅し、DAVE ダウングレード申告（protocol version 0）は接続拒否（close 4017）で不成立。
- ただし受信の動作実績は複数公開されている（xhepi.dev のフィールドレポート、vapi-discord-bridge の互換ノート、複数の個人実装）。「原理的に可能」で、残るのは自分たちの環境で安定するかの検証のみ。

## 依存関係（ピン留め必須）
```
discord.py[voice] >= 2.7.1            # DAVE 対応はこの世代から
discord-ext-voice-recv @ git+https://github.com/rdphillips7/discord-ext-voice-recv.git
                                       # PR #54 は二重復号バグ（2026-11-23 実測）→ rdphillips7 フォーク
davey >= 0.1, < 0.2                    # 0.2.0 は handshake 破壊（同日実測）
PyNaCl, opus ランタイム                # discord.py[voice] の前提
faster-whisper, numpy                  # STT_PROVIDER=whisper（ローカル STT）
```
- リリースではなく「現実」にピン留めする。上流が安定版を出したら戻す。
- py-cord は DAVE 未対応（close 4017）なので使わない。

## ハマりどころ（先行事例から）
1. **Bot が deaf で参加すると音声が一切届かない**
   `connect()` のデフォルト `self_deaf=True` では Discord が音声パケットを送らない。
   → `vc = await channel.connect(cls=voice_recv.VoiceRecvClient, self_deaf=False)`
2. **DAVE ハンドシェイク完了前に受信を始めると復号できない**
   ハンドシェイク完了を待ってから listen を開始する。鍵が無い状態で来たパケットは捨てる。
3. **パケット処理ループが無言で死ぬ**
   PR #54 にはパケット処理まわりのバグ報告あり。先行事例では `_process_packet` を「絶対に落ちない・悪いパケットは優雅にスキップ」方針で再実装／モンキーパッチして安定化している。スパイクでも例外を握りつぶさず、落とさない設計にする。
4. **Sink は PCM で受け取る**
   `wants_opus() -> False` にして、DAVE 復号＋Opus デコードをライブラリ側に任せ、`write(user, data)` の `data.pcm` を消費する。生 Opus を自前デコードしようとすると暗号化フレームで全滅する。
5. **話者の対応付け（SSRC→ユーザー）**
   先行事例では SSRC マッピングのヒューリスティクスが一番壊れやすい箇所。話者が取れない場合は「不明な話者」として字幕に流し、機能全体は止めない。

## スパイク手順
1. テスト用 Discord サーバーとボイスチャンネルを用意（ゆうきちゃんの Bot 作成は docs/USER_TASKS.md 手順2）
2. 上記依存で最小 Bot を書き、ボイスチャンネルへ `self_deaf=False` で参加
3. `voice_recv.AudioSink`（`wants_opus() = False`）で話者別 PCM を受信し、無音区間で発話を区切る
4. PCM → STT → 「話者名＋テキスト」を字幕キューへ投入
5. 成功条件: 2人以上の発話が話者別に文字化され、10分間セッションが落ちない
6. 失敗条件（Day 2 ゲート）: ハンドシェイク不成立が再現性をもって続く／PCM が復号できない状態から抜けられない → Telegram 版へ全振り

## 注意
- Bot トークンは Secure Vault 経由でのみ受け渡す。コード・ログ・README に書かない。
- 通話参加者の同意なく録音しない。スパイクは自分たちのテストサーバーでのみ行う。
- レート制限・切断時は無理に再接続を繰り返さない。

## 出典
- Receiving Voice in Discord After DAVE: A Field Report — https://www.xhepi.dev/logs/discord-dave-voice-receive/
- discord-ext-voice-recv PR #54（DAVE decryption）— https://github.com/imayhaveborkedit/discord-ext-voice-recv/pull/54
- vapi-discord-bridge: DAVE incompatibility note / voice bridge protocols（GitHub）
