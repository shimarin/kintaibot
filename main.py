#!/usr/bin/env python3
"""
kintaibot - Slackの#kintaiチャンネルを監視し出勤状況を表示する
"""

import argparse
import asyncio
import datetime
import logging
import sys
from pathlib import Path

import keyutils
from aiohttp import web

from status_manager import StatusManager
from slack_handler import SlackHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_PORT = 52963
STATIC_DIR = Path(__file__).parent / "static"


# ── キーリング ──────────────────────────────────────────────────────────────

def get_keyring_value(key_name: str) -> str | None:
    serial = keyutils.request_key(key_name.encode(), keyutils.KEY_SPEC_USER_KEYRING)
    if serial is None:
        return None
    return keyutils.read_key(serial).decode()


# ── 日付変更リセットタスク ──────────────────────────────────────────────────

async def midnight_reset_task(status_manager: StatusManager):
    """毎日 0:00 にステータスをリセットして全クライアントに通知する"""
    while True:
        now = datetime.datetime.now()
        tomorrow = datetime.datetime(now.year, now.month, now.day) + datetime.timedelta(days=1)
        wait_secs = (tomorrow - now).total_seconds()
        logger.info(f"次回リセットまで {wait_secs:.0f} 秒")
        await asyncio.sleep(wait_secs)
        logger.info("日付変更: ステータスをリセットします")
        status_manager.reset()
        await status_manager.broadcast()


# ── Web サーバ ──────────────────────────────────────────────────────────────

async def handle_index(request: web.Request) -> web.Response:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    status_manager: StatusManager = request.app["status_manager"]

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    status_manager.add_ws_client(ws)

    # 接続直後に現在のステータスを送信
    import json
    await ws.send_str(json.dumps({
        "type": "status_update",
        "persons": status_manager.get_all(),
    }))

    try:
        async for msg in ws:
            pass  # クライアントからのメッセージは現状無視
    finally:
        status_manager.remove_ws_client(ws)

    return ws


def build_web_app(status_manager: StatusManager) -> web.Application:
    app = web.Application()
    app["status_manager"] = status_manager
    app.router.add_get("/", handle_index)
    app.router.add_get("/ws", handle_ws)
    app.router.add_static("/static", STATIC_DIR)
    return app


# ── エントリポイント ────────────────────────────────────────────────────────

async def async_main(port: int):
    key_names = ["kintaibot_bot_token", "kintaibot_app_token"]
    keys = {k: get_keyring_value(k) for k in key_names}
    missing = [k for k, v in keys.items() if v is None]
    if missing:
        print("エラー: 以下のキーがキーリングに見つかりません。", file=sys.stderr)
        print("以下のコマンドで登録してください:", file=sys.stderr)
        for k in missing:
            print(f"  read -rsp '{k}: ' v && echo -n \"$v\" | keyctl padd user {k} @u", file=sys.stderr)
        sys.exit(1)
    bot_token = keys["kintaibot_bot_token"]
    app_token = keys["kintaibot_app_token"]

    status_manager = StatusManager()

    async def on_status_change():
        await status_manager.broadcast()

    slack = SlackHandler(
        bot_token=bot_token,
        app_token=app_token,
        status_manager=status_manager,
        on_status_change=on_status_change,
    )

    # 当日ヒストリ読み込み
    await slack.load_history("kintai")

    # Web サーバ起動
    web_app = build_web_app(status_manager)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web サーバ起動: http://0.0.0.0:{port}")

    # Slack Socket Mode 接続
    await slack.start()
    logger.info("Slack Socket Mode 接続完了")

    # 日付変更タスク
    asyncio.create_task(midnight_reset_task(status_manager))

    # 永続待機
    await asyncio.Event().wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="kintaibot - Slack勤怠監視ボット")
    parser.add_argument(
        "--port", "-p", type=int, default=DEFAULT_PORT,
        help=f"Webサーバのポート番号 (デフォルト: {DEFAULT_PORT})",
    )
    args = parser.parse_args()

    try:
        asyncio.run(async_main(args.port))
    except KeyboardInterrupt:
        logger.info("終了します")
