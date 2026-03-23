"""
Slack 接続・イベント処理モジュール
"""

import datetime
import logging
from typing import Callable, Awaitable

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from status_manager import StatusManager

logger = logging.getLogger(__name__)

# 今日の 0:00 の UNIX タイムスタンプ（JST）
def _today_start_ts() -> float:
    today = datetime.date.today()
    return datetime.datetime(today.year, today.month, today.day).timestamp()


class SlackHandler:
    def __init__(
        self,
        bot_token: str,
        app_token: str,
        status_manager: StatusManager,
        on_status_change: Callable[[], Awaitable[None]],
    ):
        self._app_token = app_token
        self._status_manager = status_manager
        self._on_status_change = on_status_change
        self._user_cache: dict[str, str] = {}  # user_id → display_name

        self._client = AsyncWebClient(token=bot_token)
        self._bolt_app = AsyncApp(client=self._client, token=bot_token)

        # イベントハンドラ登録
        self._bolt_app.message()(self._handle_message)

    async def _resolve_user(self, user_id: str) -> str:
        """ユーザーIDを表示名に解決（キャッシュあり）"""
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            info = await self._client.users_info(user=user_id)
            user = info["user"]
            profile = user.get("profile", {})
            # display_name は profile 以下にある
            name = (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("real_name")
                or user.get("name")
                or user_id
            )
            self._user_cache[user_id] = name
            return name
        except Exception as e:
            logger.warning(f"ユーザー情報の取得に失敗 ({user_id}): {e}")
            return user_id

    async def _find_channel_id(self, channel_name: str) -> str | None:
        """チャンネル名から ID を検索"""
        cursor = None
        while True:
            kwargs: dict = dict(types="public_channel,private_channel", limit=200)
            if cursor:
                kwargs["cursor"] = cursor
            result = await self._client.conversations_list(**kwargs)
            for ch in result["channels"]:
                if ch["name"] == channel_name:
                    return ch["id"]
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                return None

    async def load_history(self, channel_name: str = "kintai"):
        """起動時に当日のヒストリを読み込んでステータスを構築する"""
        channel_id = await self._find_channel_id(channel_name)
        if channel_id is None:
            logger.error(f"#{channel_name} チャンネルが見つかりません")
            return

        oldest = str(_today_start_ts())
        logger.info(f"#{channel_name} (ID={channel_id}) のヒストリを取得中...")

        cursor = None
        while True:
            kwargs = dict(channel=channel_id, oldest=oldest, limit=200)
            if cursor:
                kwargs["cursor"] = cursor
            result = await self._client.conversations_history(**kwargs)

            for msg in reversed(result["messages"]):  # 古い順に処理
                user_id = msg.get("user")
                if not user_id:
                    continue
                text = msg.get("text", "")
                ts = float(msg.get("ts", 0))
                display_name = await self._resolve_user(user_id)
                self._status_manager.process_message(user_id, display_name, text, ts)

            if not result.get("has_more"):
                break
            cursor = result["response_metadata"]["next_cursor"]

        logger.info("ヒストリ読み込み完了")

    async def _handle_message(self, message):
        """リアルタイムメッセージイベントのハンドラ"""
        try:
            user_id = message.get("user")
            if not user_id:
                return
            text = message.get("text", "")
            ts = float(message.get("ts", 0))

            logger.debug(f"メッセージ受信: user={user_id} ts={ts} text={text!r}")

            # 当日のメッセージのみ処理
            if ts < _today_start_ts():
                return

            display_name = await self._resolve_user(user_id)
            changed = self._status_manager.process_message(user_id, display_name, text, ts)
            if changed:
                logger.info(f"ステータス変化: {display_name} → {self._status_manager._persons[user_id].status.value}")
                await self._on_status_change()
        except Exception:
            logger.exception("メッセージ処理中にエラーが発生しました")

    async def start(self):
        """Socket Mode で Slack に接続して待機"""
        handler = AsyncSocketModeHandler(self._bolt_app, self._app_token)
        await handler.start_async()
