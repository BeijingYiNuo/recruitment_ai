from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from pydantic import BaseModel
import asyncio
import json
import wave
from assistant.entity.user import User
from fastapi import WebSocketDisconnect
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
from assistant.ASR.task_manager import TaskManager
from assistant.LLM.llm_manager import LLMManager
from assistant.utils.logger import logger
import numpy as np
# 初始化各个管理器
llm_manager = LLMManager()
task_manager = TaskManager(llm_manager=llm_manager)

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
async def start_asr(session_id: str, req: StartAsrRequest ,db: Session = Depends(get_db), current_user_id: int = Depends(get_current_user_id),record_voice: bool = True):
    """
    为指定会话启动ASR服务
    """
    session = db.query(InterviewSession).filter(InterviewSession.recruiter_id == current_user_id, InterviewSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在或用户没有权限访问该会话。"
        )
    if session.status != SessionStatus.SCHEDULED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="会话状态错误，不能启动ASR服务。"
        )
    
    try:

        await task_manager.start_interview(session_id,req,record_voice,current_user_id,db)
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
    # 验证会话存在且用户有权限
    session = db.query(InterviewSession).filter(
        InterviewSession.id == session_id,
        InterviewSession.recruiter_id == current_user_id
    ).first()
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="会话不存在或用户没有权限访问该会话。"
        )
    
    try:
        # 停止ASR服务（会自动断开WebSocket连接）
        await task_manager.stop_asr(session_id)
        
        session = db.query(InterviewSession).filter(InterviewSession.id == session_id, InterviewSession.recruiter_id == current_user_id).first()
        session.status = SessionStatus.COMPLETED
        user = db.query(User).filter(User.username == session.candidate_name).first()
        user.status = "COMPLETED"
        db.commit()
        db.refresh(session)
        db.refresh(user)
        return {
            "status": "completed"
        }
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
    if session_id in task_manager.clients:
        # 更新现有客户端的WebSocket连接
        task_manager.set_websocket(session_id, websocket)
    else:
        # 如果不存在，返回错误
        await websocket.close(code=1008, reason="ASR service not started for this session")
        logger.error(f"WebSocket connection failed: ASR service not started for session {session_id}")
        return
    
    def validate_audio_data(data: bytes) -> bool:
        """
        验证音频数据格式是否符合要求
        
        Args:
            data: 音频数据
            
        Returns:
            bool: 是否符合要求
        """
        SAMPLE_RATE = 16000          # 采样率：16000Hz
        FRAME_DURATION_MS = 30       # 每帧时长：30ms（WebRTC VAD/ASR标准）
        CHANNELS = 1                 # 通道数：单声道
        BIT_DEPTH = 16               # 位深：16bit
        BYTES_PER_SAMPLE = BIT_DEPTH // 8  # 每个采样点2字节

        # 计算每帧的理论字节数：16000 * 30 / 1000 * 2 = 960字节
        EXPECTED_FRAME_BYTES = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000 * BYTES_PER_SAMPLE)
        # 计算每帧的理论采样点数：16000 * 30 / 1000 = 480个
        EXPECTED_SAMPLE_COUNT = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)
        # 16bit int的合法范围：-32768 ~ 32767
        INT16_MIN = -32768
        INT16_MAX = 32767
        # 检查数据长度
        # 每帧30毫秒，16000Hz采样率，16位深度int16，单声道
        # 480个采样点 × 2字节/采样点 = 960字节
        expected_length = 480 * 2  # 960 bytes
        
        # ========== 1. 基础长度校验（最核心，99%的问题先卡在这里）==========
        if not isinstance(data, bytes):
            logger.error(f"音频数据类型错误，期望bytes，实际为{type(data)}")
            return False
        
        data_len = len(data)
        if data_len != EXPECTED_FRAME_BYTES:
            logger.error(f"音频包长度错误！期望{EXPECTED_FRAME_BYTES}字节，实际{data_len}字节")
            return False

        # ========== 2. 采样点数量校验 ==========
        # 960字节 = 480个int16采样点，必须整除
        if data_len % BYTES_PER_SAMPLE != 0:
            logger.error(f"音频包长度不是2的整数倍，无法解析为int16")
            return False
        
        sample_count = data_len // BYTES_PER_SAMPLE
        if sample_count != EXPECTED_SAMPLE_COUNT:
            logger.error(f"采样点数量错误！期望{EXPECTED_SAMPLE_COUNT}个，实际{sample_count}个")
            return False

        # ========== 3. 解析为int16数组，校验数值范围（验证16bit格式）==========
        try:
            # 小端序int16解析（JS/浏览器默认小端序，完全匹配前端格式）
            pcm_int16 = np.frombuffer(data, dtype=np.int16)
        except Exception as e:
            logger.error(f"音频数据解析为int16失败: {str(e)}")
            return False

        # 校验数值范围是否在16bit合法区间内（-32768 ~ 32767）
        if np.any(pcm_int16 < INT16_MIN) or np.any(pcm_int16 > INT16_MAX):
            logger.error(f"音频数据数值溢出，超出16bit int范围")
            return False

        # ========== 4. 可选：静音帧校验（防止全0异常包，可选开启）==========
        # 静音帧应为全0或接近0，这里做一个宽松校验，避免误判底噪
        # if np.all(pcm_int16 == 0):
        #     logger.debug("收到静音帧（全0），格式合法")
        # 可根据需求开启，不影响核心校验

        # ========== 5. 所有校验通过 ==========
        # logger.info(f"音频数据格式校验通过，长度{data_len}字节，{sample_count}个采样点")
        return True

    audio_q = task_manager.get_audio_queue(session_id)
    output_q = task_manager.get_output_queue(session_id)
    wf = wave.open("dump.wav", "wb")
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(16000)
    
    async def receive_audio():
        """
        从前端接收语音块并发送给audio_q
        """
        try:
            while True:
                # 接收前端发送的语音块
                data = await websocket.receive_bytes()
                
                # 验证音频数据格式
                if not validate_audio_data(data):
                    logger.error(f"Invalid audio data format for session {session_id}")
                    await websocket.close(code=1008, reason="Invalid audio data format")
                    return
                wf.writeframes(data)
                # 将语音块放入audio_q
                
                if audio_q:
                    try:
                        await audio_q.put(data)
                    except Exception as e:
                        logger.error(f"Error putting audio data into queue: {e}")
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected during audio reception for session {session_id}")
        except RuntimeError as e:
            # 处理WebSocket连接错误
            if "WebSocket is not connected" in str(e) or "Cannot call \"send\" once a close message has been sent" in str(e):
                logger.info(f"WebSocket connection error during audio reception: {e}")
            else:
                logger.error(f"Runtime error in audio reception: {e}")
        except Exception as e:
            logger.error(f"Error in audio reception: {e}")
    
    async def send_output():
        """
        从output_q中获取数据并通过websocket发送给前端
        """
        try:
            while True:
                if output_q and not output_q.empty():
                    try:
                        output_data = await output_q.get()
                        # logger.info(f"**Received output data**: {output_data}")
                        if output_data['type'] == 'asr':
                            await websocket.send_json({
                                'type': 'asr',
                                'data': output_data['data']
                            })
                        elif output_data['type'] == 'streaming':
                            await websocket.send_json({
                                'type': 'streaming',
                                'data': output_data['data']
                            })
                    except Exception as e:
                        logger.error(f"Error getting output data: {e}")
                # 短暂休眠，避免CPU占用过高
                await asyncio.sleep(0.01)
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected during output sending for session {session_id}")
        except RuntimeError as e:
            # 处理WebSocket连接错误
            if "WebSocket is not connected" in str(e) or "Cannot call \"send\" once a close message has been sent" in str(e):
                logger.info(f"WebSocket connection error during output sending: {e}")
            else:
                logger.error(f"Runtime error in output sending: {e}")
        except Exception as e:
            logger.error(f"Error in output sending: {e}")
    
    try:
        # 创建两个并发任务
        receive_task = asyncio.create_task(receive_audio())
        send_task = asyncio.create_task(send_output())
        
        # 等待任一任务完成
        await asyncio.gather(receive_task, send_task, return_exceptions=True)
    except Exception as e:
        logger.error(f"Error in WebSocket handler: {e}")
    finally:
        # 确保wave文件被关闭
        wf.close()
        # 保持客户端信息，但将websocket设为None
        if session_id in task_manager.clients:
            task_manager.clients[session_id]['websocket'] = None




