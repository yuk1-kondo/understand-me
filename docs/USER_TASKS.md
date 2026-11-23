# ゆうきちゃんの作業（2点のみ）

どちらも本人操作が必要なもの。合計15分ほど。急ぎではないけれど、Day 1 のスパイクは手順2が終わってから始まる。

## 手順1: Even Realities アカウント作成（約5分）
1. https://www.evenrealities.com にアクセス
2. 右上のアカウント／サインインから新規登録（メールアドレスで登録）
3. 確認メールが来たらリンクを開いて認証完了
4. 終わったら司令官ちゃんに「Evenアカウントできた」と一言

※ Even Hub（開発者向けシミュレータ）の利用に必要。G2実機は不要。

## 手順2: Discord Bot 作成（約10分）— スパイク開始時に実施
1. https://discord.com/developers/applications に Discord アカウントでログイン
2. 「New Application」→ 名前は `Understand Me`（仮でOK）→ Create
3. 左メニュー「Bot」→ 「Reset Token」でトークンを表示
   - **トークンはチャットに貼らないこと。** Secure Vault の入力カードを司令官ちゃんが出すので、そこに入力する
4. 同じ Bot ページで「Privileged Gateway Intents」は今回すべて OFF でよい（音声受信に特権インテントは不要）
5. 左メニュー「OAuth2 → URL Generator」で `bot` スコープを選択し、権限は `Connect` と `Speak`（ボイス接続用）を付けて、生成された URL からテスト用サーバーに Bot を招待
   - テスト用サーバーが無ければ、自分のサーバーを1つ新規作成しておく（Discord 左端の「＋」→「オリジナルを作成する」）
6. 終わったら司令官ちゃんに「Botできた」と一言

※ Bot の招待先は自分たちのテストサーバーだけにすること（他人のサーバーへは入れない）。
