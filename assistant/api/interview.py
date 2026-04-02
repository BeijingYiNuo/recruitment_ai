from fastapi import APIRouter, Depends, HTTPException, status, Request
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

from assistant.user_management.session_manager import SessionManager
from assistant.audio.audio_manager import AudioManager
from assistant.ASR.asr_manager import ASRManager
from assistant.LLM.llm_manager import LLMManager
from assistant.utils.logger import logger

# 初始化各个管理器
session_manager = SessionManager()
audio_manager = AudioManager()
llm_manager = LLMManager()
asr_manager = ASRManager(llm_manager=llm_manager)

router = APIRouter(prefix="/api", tags=["面试管理"])

# 会话管理相关接口
class StartAsrRequest(BaseModel):
    url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    seg_duration: int = 200
    mic: bool = True
    file: Optional[str] = None
    use_llm: bool = True

# 语音识别相关接口
@router.post("/asr/start/{user_id}", tags=["语音识别"])
async def start_asr(user_id: str, req: StartAsrRequest):
    """
    为指定用户启动ASR服务
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        await asr_manager.start_asr(user_id, req, use_llm=req.use_llm)
        return {
            "status": "started",
            "mode": "mic" if req.mic else "file"
        }
    except Exception as e:
        logger.error(f"Error starting ASR: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start ASR: {str(e)}")

@router.post("/asr/stop/{user_id}", tags=["语音识别"])
async def stop_asr(user_id: str):
    """
    为指定用户停止ASR服务
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        await asr_manager.stop_asr(user_id)
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Error stopping ASR: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop ASR: {str(e)}")

@router.get("/asr/stream/{user_id}", tags=["语音识别"])
async def stream_asr(user_id: str):
    """
    SSE端点，用于传输ASR和LLM的流式数据
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    async def event_generator():
        while True:
            # 检查ASR队列
            asr_queue = asr_manager.get_asr_queue(user_id)
            if asr_queue and not asr_queue.empty():
                try:
                    asr_data = await asr_queue.get()
                    yield f"data: {json.dumps({'type': 'asr', 'data': asr_data})}\n\n"
                except Exception as e:
                    logger.error(f"Error getting ASR data: {e}")
            
            # 检查LLM队列
            llm_queue = llm_manager.get_llm_queue(user_id)
            streaming_llm_queue = llm_manager.get_streaming_llm_queue(user_id)
            if streaming_llm_queue and not streaming_llm_queue.empty():
                try:
                    streaming_llm_data = await streaming_llm_queue.get()
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
                    yield f"data: {json.dumps(formatted_data, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.error(f"Error getting LLM data: {e}")
            
            # 短暂休眠，避免CPU占用过高
            await asyncio.sleep(0.1)
    
    from fastapi.responses import StreamingResponse
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# 音频设备相关接口
@router.post("/audio/stream/{user_id}", tags=["音频设备"])
async def create_audio_stream(user_id: str, device_id: Optional[int] = None):
    """
    为用户创建音频流
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        stream_id = audio_manager.create_stream(user_id, device_id)
        return {"stream_id": stream_id, "status": "created"}
    except Exception as e:
        logger.error(f"Error creating audio stream: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create audio stream: {str(e)}")

@router.post("/audio/stream/{user_id}/start", tags=["音频设备"])
async def start_audio_stream(user_id: str):
    """
    启动用户音频流
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        audio_manager.start_stream(user_id)
        return {"status": "started"}
    except Exception as e:
        logger.error(f"Error starting audio stream: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start audio stream: {str(e)}")

@router.post("/audio/stream/{user_id}/stop", tags=["音频设备"])
async def stop_audio_stream(user_id: str):
    """
    停止用户音频流
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    try:
        audio_manager.stop_stream(user_id)
        return {"status": "stopped"}
    except Exception as e:
        logger.error(f"Error stopping audio stream: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to stop audio stream: {str(e)}")




# 面试报告相关接口
@router.get("/interviews/reports", response_model=List[InterviewReportResponse])
def get_interview_reports(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取面试报告列表"""
    reports = db.query(InterviewReport).offset(skip).limit(limit).all()
    return reports


@router.get("/interviews/reports/{report_id}", response_model=InterviewReportResponse)
def get_interview_report(
    report_id: int,
    db: Session = Depends(get_db)
):
    """获取单个面试报告"""
    report = db.query(InterviewReport).filter(InterviewReport.id == report_id).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在"
        )
    return report


@router.post("/interviews/reports", response_model=InterviewReportResponse, status_code=status.HTTP_201_CREATED)
def create_interview_report(
    report: InterviewReportCreate,
    db: Session = Depends(get_db)
):
    """创建面试报告"""
    # 检查面试会话是否存在
    session = db.query(InterviewSession).filter(InterviewSession.id == report.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    db_report = InterviewReport(
        session_id=report.session_id,
        report_content=report.report_content,
        status=report.status
    )
    
    db.add(db_report)
    db.commit()
    db.refresh(db_report)
    
    return db_report


@router.put("/interviews/reports/{report_id}", response_model=InterviewReportResponse)
def update_interview_report(
    report_id: int,
    report: InterviewReportUpdate,
    db: Session = Depends(get_db)
):
    """更新面试报告"""
    db_report = db.query(InterviewReport).filter(InterviewReport.id == report_id).first()
    if not db_report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试报告不存在"
        )
    
    update_data = report.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_report, key, value)
    
    db.commit()
    db.refresh(db_report)
    
    return db_report


# 面试提醒相关接口
@router.get("/interviews/reminders", response_model=List[InterviewReminderResponse])
def get_interview_reminders(
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取面试提醒列表"""
    reminders = db.query(InterviewReminder).offset(skip).limit(limit).all()
    return reminders


@router.get("/interviews/reminders/{reminder_id}", response_model=InterviewReminderResponse)
def get_interview_reminder(
    reminder_id: int,
    db: Session = Depends(get_db)
):
    """获取单个面试提醒"""
    reminder = db.query(InterviewReminder).filter(InterviewReminder.id == reminder_id).first()
    if not reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试提醒不存在"
        )
    return reminder


@router.post("/interviews/reminders", response_model=InterviewReminderResponse, status_code=status.HTTP_201_CREATED)
def create_interview_reminder(
    reminder: InterviewReminderCreate,
    db: Session = Depends(get_db)
):
    """创建面试提醒"""
    # 检查面试会话是否存在
    session = db.query(InterviewSession).filter(InterviewSession.id == reminder.session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试会话不存在"
        )
    
    db_reminder = InterviewReminder(
        session_id=reminder.session_id,
        user_id=reminder.user_id,
        reminder_time=reminder.reminder_time,
        message=reminder.message,
        status=ReminderStatus.PENDING,
        send_method=reminder.send_method
    )
    
    db.add(db_reminder)
    db.commit()
    db.refresh(db_reminder)
    
    return db_reminder


@router.put("/interviews/reminders/{reminder_id}", response_model=InterviewReminderResponse)
def update_interview_reminder(
    reminder_id: int,
    reminder: InterviewReminderUpdate,
    db: Session = Depends(get_db)
):
    """更新面试提醒"""
    db_reminder = db.query(InterviewReminder).filter(InterviewReminder.id == reminder_id).first()
    if not db_reminder:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="面试提醒不存在"
        )
    
    update_data = reminder.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_reminder, key, value)
    
    db.commit()
    db.refresh(db_reminder)
    
    return db_reminder
