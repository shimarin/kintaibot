#!/usr/bin/env python3
"""
kintaiチャンネルのヒストリを読み出すスクリプト
"""

import sys
import keyutils
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


def get_keyring_value(key_name: str) -> str:
    """カーネルキーリングから値を取得する。"""
    serial = keyutils.request_key(key_name.encode(), keyutils.KEY_SPEC_USER_KEYRING)
    if serial is None:
        print(f"エラー: キー '{key_name}' がキーリングに見つかりません。", file=sys.stderr)
        print(f"以下のコマンドで登録してください:", file=sys.stderr)
        print(f"  read -rsp '{key_name}: ' k && echo -n \"$k\" | keyctl padd user {key_name} @u", file=sys.stderr)
        sys.exit(1)
    return keyutils.read_key(serial).decode()


def find_channel_id(client: WebClient, channel_name: str) -> str | None:
    """チャンネル名からIDを検索する。"""
    for page in client.conversations_list(types="public_channel,private_channel", limit=200):
        for ch in page["channels"]:
            if ch["name"] == channel_name:
                return ch["id"]
    return None


def main():
    app_token = get_keyring_value("kintaibot_app_token")
    bot_token = get_keyring_value("kintaibot_bot_token")

    client = WebClient(token=bot_token)

    print("Slackに接続しました。")

    # kintaiチャンネルを検索
    channel_name = "kintai"
    print(f"#{channel_name} チャンネルを検索中...")
    channel_id = find_channel_id(client, channel_name)

    if channel_id is None:
        print(f"エラー: #{channel_name} チャンネルが見つかりません。", file=sys.stderr)
        sys.exit(1)

    print(f"#{channel_name} (ID: {channel_id}) のヒストリを取得中...")

    try:
        result = client.conversations_history(channel=channel_id, limit=20)
    except SlackApiError as e:
        print(f"エラー: ヒストリの取得に失敗しました: {e.response['error']}", file=sys.stderr)
        sys.exit(1)

    messages = result["messages"]
    print(f"\n--- 最新 {len(messages)} 件のメッセージ ---")

    # ユーザー名キャッシュ
    user_cache: dict[str, str] = {}

    for msg in reversed(messages):
        ts = float(msg.get("ts", 0))
        import datetime
        dt = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

        user_id = msg.get("user", "")
        if user_id:
            if user_id not in user_cache:
                try:
                    info = client.users_info(user=user_id)
                    user_cache[user_id] = info["user"]["display_name"] or info["user"]["real_name"]
                except SlackApiError:
                    user_cache[user_id] = user_id
            username = user_cache[user_id]
        else:
            username = msg.get("username", "bot")

        text = msg.get("text", "")
        print(f"[{dt}] {username}: {text}")


if __name__ == "__main__":
    main()
