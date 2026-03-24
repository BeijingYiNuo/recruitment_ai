import asyncio
import json
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from user_management.session_manager import SessionManager
from config.config_manager import ConfigManager
from audio.audio_manager import AudioManager
from ASR.asr_manager import ASRManager
from LLM.llm_manager import LLMManager
from context.context_manager import ContextManager
from knowledge.knowledge_manager import KnowledgeManager
from prompt.prompt_manager import PromptManager
from file.file_manager import FileManager
from report.report_manager import ReportManager

from utils.logger import logger

app = FastAPI(title="Recruitment Service")

# 配置CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化各个管理器
session_manager = SessionManager()
config_manager = ConfigManager()
audio_manager = AudioManager()
llm_manager = LLMManager()
asr_manager = ASRManager(llm_manager=llm_manager)
context_manager = ContextManager()
knowledge_manager = KnowledgeManager()
prompt_manager = PromptManager()
file_manager = FileManager()
report_manager = ReportManager()

# 启动知识库
def startup_event():
    knowledge_manager.initialize_knowledge_sources()

app.add_event_handler("startup", startup_event)

class StartAsrRequest(BaseModel):
    url: str = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
    seg_duration: int = 200
    mic: bool = True
    file: Optional[str] = None
    use_llm: bool = True

@app.post("/api/sessions")
async def create_session():
    """
    创建新的用户会话
    """
    user_id = session_manager.create_session()
    return {"user_id": user_id, "status": "created"}

@app.get("/api/sessions")
async def list_sessions():
    """
    列出所有会话
    """
    sessions = session_manager.list_sessions()
    return {"sessions": sessions, "count": session_manager.get_session_count()}

@app.get("/api/sessions/{user_id}")
async def get_session(user_id: str):
    """
    获取用户会话
    """
    session = session_manager.get_session(user_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"user_id": user_id, "session": session}

@app.delete("/api/sessions/{user_id}")
async def remove_session(user_id: str):
    """
    移除用户会话
    """
    session_manager.remove_session(user_id)
    return {"status": "removed"}

@app.post("/api/asr/start/{user_id}")
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

@app.post("/api/asr/stop/{user_id}")
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

@app.get("/api/asr/stream/{user_id}")
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
                    # logger.info(f"--------streaming_llm_data--------- :{streaming_llm_data}")
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
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/devices")
async def list_devices():
    """
    列出可用音频设备
    """
    devices = audio_manager.list_devices()
    return {"devices": devices}

@app.post("/api/audio/stream/{user_id}")
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

@app.post("/api/audio/stream/{user_id}/start")
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

@app.post("/api/audio/stream/{user_id}/stop")
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

@app.get("/api/audio/streams")
async def get_active_streams():
    """
    获取活跃音频流列表
    """
    streams = audio_manager.get_active_streams()
    return {"streams": streams}

@app.get("/api/context/{user_id}")
async def get_context(user_id: str):
    """
    获取用户上下文
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    context = context_manager.get_context(user_id)
    return {"context": context}

@app.post("/api/context/{user_id}")
async def update_context(user_id: str, update: dict):
    """
    更新用户上下文
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    context_manager.update_context(user_id, update)
    return {"status": "updated"}

@app.post("/api/context/{user_id}/message")
async def add_message(user_id: str, role: str, content: str):
    """
    添加消息到用户上下文
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    context_manager.add_message(user_id, role, content)
    return {"status": "added"}

@app.delete("/api/context/{user_id}")
async def clear_context(user_id: str):
    """
    清空用户上下文
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    context_manager.clear_context(user_id)
    return {"status": "cleared"}

@app.get("/api/knowledge/search/{user_id}")
async def search_knowledge(user_id: str, query: str, top_k: int = 3):
    """
    为用户搜索知识库
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    results = knowledge_manager.search_knowledge(user_id, query, top_k)
    return {"results": results}

@app.post("/api/report/{user_id}")
async def generate_report(user_id: str, conversation: dict):
    """
    为用户生成报告
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    report = report_manager.generate_report(user_id, conversation)
    return {"report": report}

@app.get("/api/report/{user_id}/{report_id}")
async def get_report(user_id: str, report_id: str):
    """
    获取用户报告
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    report = report_manager.get_report(user_id, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"report": report}

@app.get("/api/files/{user_id}")
async def list_user_files(user_id: str, file_type: Optional[str] = None):
    """
    列出用户的文件
    """
    if not session_manager.get_session(user_id):
        raise HTTPException(status_code=404, detail="Session not found")
    
    files = file_manager.list_user_files(user_id, file_type)
    return {"files": files}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)
