"""
任务事件通知：通过 SSE 向前端推送单条简历解析完成事件。
"""
import asyncio
import json
from typing import Dict, List


class TaskEventManager:
    """管理任务事件的订阅和推送"""

    _instance = None

    def __init__(self):
        self._subscribers: Dict[int, List[asyncio.Queue]] = {}

    @classmethod
    def get_instance(cls) -> "TaskEventManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, task_id: int) -> asyncio.Queue:
        """订阅某个任务的事件，返回一个队列"""
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers.setdefault(task_id, []).append(queue)
        return queue

    def unsubscribe(self, task_id: int, queue: asyncio.Queue):
        """取消订阅"""
        subs = self._subscribers.get(task_id, [])
        self._subscribers[task_id] = [q for q in subs if q is not queue]
        if not self._subscribers[task_id]:
            del self._subscribers[task_id]

    def notify(self, task_id: int, event: dict):
        """向所有订阅者推送事件"""
        subs = self._subscribers.get(task_id, [])
        for queue in subs[:]:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscriber_count(self, task_id: int) -> int:
        """指定任务有多少订阅者"""
        return len(self._subscribers.get(task_id, []))

    async def event_generator(self, task_id: int):
        """异步生成器，用于 SSE 流式输出。连接打开后先发送当前状态。"""
        queue = self.subscribe(task_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                    # batch_completed 事件表示所有简历处理完毕，关闭 SSE 连接
                    if event.get("type") == "batch_completed":
                        return
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat"}
        except asyncio.CancelledError:
            pass
        finally:
            self.unsubscribe(task_id, queue)
