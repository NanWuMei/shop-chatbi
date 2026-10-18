"""SSE 事件缓冲（FR-5 / B7）：每 turn 一个，单调 id、保留 10 分钟、Last-Event-ID 尽力补帧。

- append/close 为同步方法（仅在事件循环线程内调用）；
- wait 供 SSE 生成器挂起等待新事件；
- 过期（自创建起超过保留期）后流自然结束，超时引导重问（SDD §3.2）。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class Frame:
    id: int
    event: str
    data: dict


class EventBuffer:
    def __init__(self, *, retention_seconds: int = 600, clock: Optional[Callable[[], float]] = None) -> None:
        self._events: list[Frame] = []
        self._next_id = 1
        self._new_event = asyncio.Event()
        self._closed = False
        self._clock = clock or time.monotonic
        self._created_at = self._clock()
        self._retention = retention_seconds

    # ---- 写（事件循环线程内同步调用） ----
    def append(self, event: str, data: dict) -> int:
        f = Frame(id=self._next_id, event=event, data=data)
        self._next_id += 1
        self._events.append(f)
        self._new_event.set()
        return f.id

    def close(self) -> None:
        self._closed = True
        self._new_event.set()

    # ---- 读 ----
    def after(self, last_id: int) -> list[Frame]:
        return [f for f in self._events if f.id > last_id]

    @property
    def frames(self) -> list[Frame]:
        return list(self._events)

    @property
    def closed(self) -> bool:
        return self._closed

    def expired(self) -> bool:
        return (self._clock() - self._created_at) > self._retention

    async def wait(self, timeout: Optional[float] = None) -> None:
        """等待新事件；timeout 后返回（调用方重查 after/closed/expired）。"""
        try:
            await asyncio.wait_for(self._new_event.wait(), timeout)
        except asyncio.TimeoutError:
            return
        finally:
            self._new_event.clear()
