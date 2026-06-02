from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from assistant.streaming.session import StreamManager

router = APIRouter(prefix="/api/stream", tags=["流式传输"])
manager = StreamManager.get_instance()


@router.get("/{session_id}")
async def stream_events(session_id: str):
    """
    SSE 端点：消费指定会话的流式事件。
    返回 text/event-stream，客户端可用 EventSource 或 fetch-event-source 连接。
    """
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="流式会话不存在或已过期")

    async def event_stream():
        async for event in session.event_generator():
            event_type = event.get("type", "message")
            import json as _json
            data = _json.dumps(event, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{session_id}/pause")
async def pause_stream(session_id: str):
    """暂停流式输出。"""
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="流式会话不存在或已过期")
    session.pause()
    return {"status": "paused"}


@router.post("/{session_id}/resume")
async def resume_stream(session_id: str):
    """恢复流式输出。"""
    session = manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="流式会话不存在或已过期")
    session.resume()
    return {"status": "resumed"}


@router.post("/{session_id}/cancel")
async def cancel_stream(session_id: str):
    """取消并移除流式会话。"""
    manager.remove_session(session_id)
    return {"status": "cancelled"}
