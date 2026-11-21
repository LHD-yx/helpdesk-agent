"""会话记忆：按 session_id 保留最近几轮对话。

放进程内存，30 分钟不活动就过期。对话里有工单细节，落盘得先处理加密和
生命周期，这个版本先不做。多 worker 会各存各的，README 的已知限制里写了。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

MAX_CONTENT_CHARS = 200


@dataclass(frozen=True)
class Turn:
    role: str      # "user" | "assistant"
    content: str
    ts: float


class SessionStore:
    """线程安全的内存会话存储。

    max_turns     每个会话最多保留多少条消息（6 = 3 轮问答）
    ttl_seconds   多久没活动就过期（1800 = 30 分钟）
    max_sessions  最多同时保留多少个会话（防止内存无限增长）
    """

    def __init__(
        self,
        max_turns: int = 6,
        ttl_seconds: float = 1800.0,
        max_sessions: int = 200,
    ) -> None:
        if max_turns <= 0:
            raise ValueError("max_turns 必须大于 0")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds 必须大于 0")
        if max_sessions <= 0:
            raise ValueError("max_sessions 必须大于 0")

        self._max_turns = max_turns
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._data: dict[str, list[Turn]] = {}
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def _is_expired(self, session_id: str, now: float) -> bool:
        return now - self._last_seen.get(session_id, 0.0) > self._ttl

    def _drop(self, session_id: str) -> None:
        self._data.pop(session_id, None)
        self._last_seen.pop(session_id, None)

    def _evict_oldest(self) -> None:
        if len(self._data) <= self._max_sessions:
            return
        oldest = min(self._last_seen, key=self._last_seen.get)
        self._drop(oldest)

    def append(self, session_id: str, role: str, content: str) -> None:
        """追加一条消息。超长内容截断，超出窗口的旧消息丢弃。"""
        now = time.time()
        with self._lock:
            if self._is_expired(session_id, now):
                self._drop(session_id)
            turns = self._data.setdefault(session_id, [])
            turns.append(
                Turn(role=role, content=content.strip()[:MAX_CONTENT_CHARS], ts=now)
            )
            del turns[: -self._max_turns]
            self._last_seen[session_id] = now
            self._evict_oldest()

    def recent(self, session_id: str, limit_turns: int = 3) -> list[Turn]:
        """取最近 limit_turns 轮（1 轮 = 1 问 1 答 = 2 条消息）。"""
        if limit_turns <= 0:
            return []
        now = time.time()
        with self._lock:
            if self._is_expired(session_id, now):
                self._drop(session_id)
                return []
            return list(self._data.get(session_id, [])[-limit_turns * 2 :])

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._drop(session_id)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
