"""
勤怠ステータス管理モジュール
"""

import json
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Set

from aiohttp import web


class Status(str, Enum):
    NOT_IN = "not_in"   # 未出勤
    WORKING = "working" # 勤務中
    LEFT = "left"       # 退勤済み


@dataclass
class PersonStatus:
    user_id: str
    display_name: str
    status: Status = Status.NOT_IN
    last_in_ts: Optional[float] = None
    last_out_ts: Optional[float] = None


class StatusManager:
    def __init__(self):
        self._persons: dict[str, PersonStatus] = {}
        self._ws_clients: Set[web.WebSocketResponse] = set()

    def reset(self):
        """0:00 になったときにステータスをリセット"""
        for p in self._persons.values():
            p.status = Status.NOT_IN
            p.last_in_ts = None
            p.last_out_ts = None

    def process_message(
        self,
        user_id: str,
        display_name: str,
        text: str,
        ts: float,
    ) -> bool:
        """
        メッセージを処理してステータスを更新する。
        :in: / :out: を含まないメッセージは無視。
        ステータスに変化があれば True を返す。
        """
        has_in = ":in:" in text
        has_out = ":out:" in text
        if not has_in and not has_out:
            return False

        if user_id not in self._persons:
            self._persons[user_id] = PersonStatus(
                user_id=user_id, display_name=display_name
            )

        person = self._persons[user_id]
        person.display_name = display_name  # 表示名は常に最新に

        old_status = person.status

        if has_in and (person.last_in_ts is None or ts > person.last_in_ts):
            person.last_in_ts = ts
        if has_out and (person.last_out_ts is None or ts > person.last_out_ts):
            person.last_out_ts = ts

        # ステータス判定
        if person.last_in_ts is None:
            person.status = Status.NOT_IN
        elif (
            person.last_out_ts is not None
            and person.last_out_ts > person.last_in_ts
        ):
            person.status = Status.LEFT
        else:
            person.status = Status.WORKING

        return person.status != old_status

    def get_all(self) -> list[dict]:
        return [
            {
                "user_id": p.user_id,
                "display_name": p.display_name,
                "status": p.status.value,
            }
            for p in sorted(self._persons.values(), key=lambda x: x.display_name)
        ]

    # ── WebSocket ブロードキャスト ──────────────────────────────────────────

    def add_ws_client(self, ws: web.WebSocketResponse):
        self._ws_clients.add(ws)

    def remove_ws_client(self, ws: web.WebSocketResponse):
        self._ws_clients.discard(ws)

    async def broadcast(self):
        """接続中の全 WebSocket クライアントに現在のステータスを送信"""
        if not self._ws_clients:
            return
        data = json.dumps({"type": "status_update", "persons": self.get_all()})
        dead: Set[web.WebSocketResponse] = set()
        for ws in self._ws_clients:
            try:
                await ws.send_str(data)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead
