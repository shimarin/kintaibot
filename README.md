# kintaibot

Slackの #kintai チャンネルを監視し、メンバーの出勤状況をリアルタイムで表示するボット。

## 概要

- Slack の `:in:` / `:out:` 絵文字で記録された出勤・退勤を解析
- Web ブラウザ（OBS Studio のブラウザソース想定）向けにステータスを表示
- ステータス変化を WebSocket でリアルタイム通知
- 毎日 0:00 に自動リセット

## ステータスの定義

| 状態 | 条件 |
|------|------|
| 未出勤 | 当日の `:in:` メッセージがない |
| 勤務中 | `:in:` はあるが、その後に `:out:` がない |
| 退勤済み | `:in:` の後に `:out:` がある |

## セットアップ

### 1. Slack アプリの作成

[api.slack.com](https://api.slack.com/apps) で新規アプリを作成し、以下を設定する。

**OAuth スコープ（Bot Token）**

| スコープ | 用途 |
|---------|------|
| `channels:history` | パブリックチャンネルのヒストリ取得 |
| `channels:read` | チャンネル一覧の取得 |
| `groups:history` | プライベートチャンネルのヒストリ取得 |
| `groups:read` | プライベートチャンネル一覧の取得 |
| `users:read` | ユーザー名の解決 |

**Socket Mode**

Settings → Socket Mode を有効化し、App-Level Token（`connections:write` スコープ）を発行する。

**Event Subscriptions**

Socket Mode 有効化後、Subscribe to bot events で `message.channels` または `message.groups` を追加する。

### 2. ボットをチャンネルに招待

```
/invite @kintaibot
```

### 3. 依存ライブラリのインストール

```bash
# Portage
emerge dev-python/keyutils

# pip
pip install slack-bolt slack-sdk aiohttp --break-system-packages
```

### 4. トークンをキーリングに登録

```bash
# Bot Token (xoxb-...)
read -rsp 'kintaibot_bot_token: ' k && echo -n "$k" | keyctl padd user kintaibot_bot_token @u

# App-Level Token (xapp-...)
read -rsp 'kintaibot_app_token: ' k && echo -n "$k" | keyctl padd user kintaibot_app_token @u
```

トークンはカーネルキーリング（ユーザーキーリング `@u`）に保存されるため、ファイルシステムに書き出されない。再起動・ログアウト後は再登録が必要。

## 起動

```bash
python3 main.py               # デフォルトポート (52963)
python3 main.py --port 8080   # ポート指定
python3 main.py -p 8080       # 短縮形
```

起動時に当日 0:00 以降のヒストリを読み込んで初期ステータスを構築し、その後リアルタイム監視を開始する。

## Web UI

起動後、以下の URL でステータス画面にアクセスできる。

```
http://localhost:52963
```

OBS Studio のブラウザソースに上記 URL を設定すると、配信画面にオーバーレイとして表示できる。WebSocket で自動更新されるため、手動リロードは不要。

## 設計上の注意点

### Slack ソケット切断時のメッセージ欠落

`slack_bolt` の `AsyncSocketModeHandler` は切断時に自動再接続する。ただし、再接続中に投稿された `:in:` / `:out:` メッセージはリアルタイムイベントとして受信されないため、その間の打刻が欠落する可能性がある。

再接続時に `load_history()` を再実行してギャップを埋める対策は実装していない。本ボットは毎日 0:00 にステータスをリセットする運用を前提としており、日中の短時間の欠落は許容範囲と判断したため。

## ファイル構成

```
kintaibot/
├── main.py            # エントリポイント・Web サーバ (aiohttp)
├── slack_handler.py   # Slack 接続・イベント処理 (slack-bolt Socket Mode)
├── status_manager.py  # ステータス管理・WebSocket ブロードキャスト
├── static/
│   └── index.html     # ブラウザソース用 UI
└── read_history.py    # ヒストリ読み出し動作確認用スクリプト
```
