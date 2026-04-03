from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import asyncio
import json

from assistant.config.database import get_db
from assistant.entity import (
    InterviewSession, SessionType, SessionStatus,
    InterviewSessionQuestion, InterviewSessionStandard,
    InterviewEvaluation, Recommendation,
    InterviewReport, ReportStatus,
    InterviewReminder, ReminderStatus, SendMethod
)
from assistant.entity.DTO import (
    InterviewSessionCreate, InterviewSessionUpdate,
    InterviewSessionQuestionCreate, InterviewSessionStandardCreate,
    InterviewEvaluationCreate, InterviewEvaluationUpdate,
    InterviewReportCreate, InterviewReportUpdate,
    InterviewReminderCreate, InterviewReminderUpdate
)
from assistant.entity.VO import (
    InterviewSessionResponse, InterviewSessionQuestionResponse,
    InterviewSessionStandardResponse, InterviewEvaluationResponse,
    InterviewReportResponse, InterviewReminderResponse
)

from assistant.user_management.auth_middleware import get_current_user_id, get_current_user_id_from_websocket
from assistant.audio.audio_manager import AudioManager
from assistant.ASR.asr_manager import ASRManager
from assistant.LLM.llm_manager import LLMManager
from assistant.utils.logger import logger

# 初始化各个管理器
audio_manager = AudioManager()
llm_manager = LLMManager()
asr_manager = ASRManager(llm_manager=llm_manager)

router = APIRouter(prefix="/api", tags=["面试辅助"])

# 会话管理相关接口
class StartAsrRequest(BaseModel):
    url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    seg_duration: int = 200
    mic: bool = True
    file: Optional[str] = None
    use_llm: bool = True

# 语音识别相关接口
@router.post("/asr/start/{session_id}")
async def start_asr(session_id: str, req: StartAsrRequest ,db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id)):
    """
    为指定会话启动ASR服务
    """
    sessions = db.query(InterviewSession).filter(InterviewSession.recruiter_id == current_user_id, InterviewSession.id == session_id).all()
    if not sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在或用户没有权限访问该会话。"
        )
    
    try:
        await asr_manager.start_asr(session_id, req, use_llm=req.use_llm)
        return {
            "status": "started",
            "mode": "mic" if req.mic else "file"
        }
    except Exception as e:
        logger.error(f"Error starting ASR: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start ASR: {str(e)}")

@router.post("/asr/stop/{session_id}")
async def stop_asr(session_id: str, db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id)):
    """
    为指定会话停止ASR服务
    """
    sessions = db.query(InterviewSession).filter(InterviewSession.recruiter_id == current_user_id, InterviewSession.id == session_id).all()
    if not sessions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在或用户没有权限访问该会话。"
        )
    
    try:
        # 停止ASR服务（会自动断开WebSocket连接）
        await asr_manager.stop_asr(session_id)
        
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Error stopping ASR: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop ASR: {str(e)}")

@router.websocket("/asr/stream/{session_id}")
async def websocket_asr_stream(websocket: WebSocket, session_id: str, db: Session = Depends(get_db)):
    """
    WebSocket端点，用于传输ASR和LLM的流式数据
    """
    # 使用统一的认证中间件获取用户ID
    try:
        current_user_id = await get_current_user_id_from_websocket(websocket)
    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
        return
    
    # 检查会话是否存在且用户有权限
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    
    if not session:
        await websocket.close(code=1008, reason="会话不存在或用户没有权限访问该会话")
        return
    
    # 接受WebSocket连接
    await websocket.accept()
    
    # 检查ASRManager中是否已经存在该session_id的客户端信息
    if session_id in asr_manager.clients:
        # 更新现有客户端的WebSocket连接
        asr_manager.clients[session_id]['websocket'] = websocket
        logger.info(f"WebSocket connection updated for session {session_id}")
    else:
        # 如果不存在，返回错误
        await websocket.close(code=1008, reason="ASR service not started for this session")
        logger.error(f"WebSocket connection failed: ASR service not started for session {session_id}")
        return
    
    try:
        while True:
            # 检查ASR队列
            asr_queue = asr_manager.get_asr_queue(session_id)
            if asr_queue and not asr_queue.empty():
                try:
                    asr_data = await asr_queue.get()
                    await websocket.send_json({
                        'type': 'asr',
                        'data': asr_data
                    })
                except Exception as e:
                    logger.error(f"Error getting ASR data: {e}")
            
            # 检查LLM队列
            llm_queue = llm_manager.get_llm_queue(session_id)
            streaming_llm_queue = llm_manager.get_streaming_llm_queue(session_id)
            
            if streaming_llm_queue and not streaming_llm_queue.empty():
                try:
                    streaming_llm_data = await streaming_llm_queue.get()
                    await websocket.send_json({
                        'type': 'streaming_llm',
                        'data': streaming_llm_data
                    })
                except Exception as e:
                    logger.error(f"Error getting streaming LLM data: {e}")
            
            if llm_queue and not llm_queue.empty():
                try:
                    llm_data = await llm_queue.get()
                    # 添加测试数据，确保前端能显示内容
                    follow_up_questions = llm_data.get('follow_up_questions', []) 
                    evaluation = llm_data.get('evaluation', '') 
                    block_text = llm_data.get('block','')
                    
                    follow_up_text = "\n".join([f"{i+1}. {q}" for i, q in enumerate(follow_up_questions)])
                    evaluation_text = evaluation
                    logger.info(f"--------follow_up_questions--------- :{follow_up_questions}")
                    logger.info(f"--------evaluation--------- :{evaluation_text}")
                    formatted_data = {
                        'type': 'llm',
                        'data': {
                            'follow_up_questions': follow_up_questions,
                            'evaluation': evaluation_text,
                            'block_text': block_text,
                            'formatted': {
                                'follow_up': follow_up_text,
                                'evaluation': evaluation_text,
                                'block_text': block_text
                            }
                        }
                    }
                    await websocket.send_json(formatted_data)
                except Exception as e:
                    logger.error(f"Error getting LLM data: {e}")
            
            # 短暂休眠，避免CPU占用过高
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
        # 保持客户端信息，但将websocket设为None
        if session_id in asr_manager.clients:
            asr_manager.clients[session_id]['websocket'] = None
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        # 保持客户端信息，但将websocket设为None
        if session_id in asr_manager.clients:
            asr_manager.clients[session_id]['websocket'] = None
        await websocket.close(code=1011, reason=f"Internal server error: {str(e)}")




