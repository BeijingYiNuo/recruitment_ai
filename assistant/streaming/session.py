import asyncio
import uuid
from datetime import datetime
from typing import AsyncGenerator, Callable, Optional, Any


class StreamSession:
    """一次流式会话，包装一个 async generator，支持暂停/继续/取消。"""

    def __init__(self, generator_factory: Callable, args: tuple = (),
                 kwargs: dict = None, metadata: dict = None):
        self.id = str(uuid.uuid4())
        self._generator_factory = generator_factory
        self._args = args
        self._kwargs = kwargs or {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._paused = asyncio.Event()
        self._paused.set()  # 默认未暂停
        self._cancelled = asyncio.Event()
        self._done = False
        self._task: Optional[asyncio.Task] = None
        self.created_at = datetime.now()
        self.metadata = metadata or {}

    @property
    def is_paused(self) -> bool:
        return not self._paused.is_set()

    @property
    def is_done(self) -> bool:
        return self._done

    def pause(self) -> None:
        self._paused.clear()

    def resume(self) -> None:
        self._paused.set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._done = True
        if self._task and not self._task.done():
            self._task.cancel()

    async def start(self) -> None:
        """在后台启动 generator。"""
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            generator = self._generator_factory(*self._args, **self._kwargs)
            async for event in generator:
                if self._cancelled.is_set():
                    break
                # 暂停时阻塞等待（同样产生背压，阻止生产者过快填充）
                await self._paused.wait()
                await self._queue.put(event)

            if not self._cancelled.is_set():
                await self._queue.put({"type": "done"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            await self._queue.put({"type": "error", "message": str(e)})
        finally:
            self._done = True

    async def event_generator(self) -> AsyncGenerator[dict, None]:
        """
        供 SSE StreamingResponse 消费的 async generator。
        从队列中读取事件，空闲时发送心跳。
        """
        while not self._done or not self._queue.empty():
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=2)
                yield event
            except asyncio.TimeoutError:
                if self._cancelled.is_set():
                    break
                yield {"type": "heartbeat"}
                continue

        # 排空剩余事件
        while not self._queue.empty():
            yield await self._queue.get()


class StreamManager:
    """全局流式会话注册中心（单例）。"""

    _instance = None
    _sessions: dict[str, StreamSession] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> "StreamManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def create_session(self, generator_factory: Callable, *args,
                       metadata: dict = None, **kwargs) -> StreamSession:
        """创建新会话并自动启动后台生产者。"""
        session = StreamSession(generator_factory, args, kwargs, metadata)
        self._sessions[session.id] = session
        return session

    def get_session(self, session_id: str) -> Optional[StreamSession]:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session:
            session.cancel()

    def cleanup_stale(self, max_age_seconds: int = 300) -> int:
        """清理超时会话，返回清理数量。"""
        now = datetime.now()
        stale = [
            sid for sid, s in self._sessions.items()
            if (now - s.created_at).total_seconds() > max_age_seconds
        ]
        for sid in stale:
            self._sessions.pop(sid, None)
        return len(stale)
