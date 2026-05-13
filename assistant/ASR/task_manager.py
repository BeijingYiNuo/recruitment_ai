import asyncio
from typing import Dict, Any, Optional
from assistant.config.config_manager import ConfigManager
from assistant.utils.logger import logger
from assistant.LLM.llm_manager import LLMManager
from assistant.ASR.state_manager import ASRState
from assistant.ASR.ASRWsClient import AsrWsClient
from assistant.file.file_manager import TosFileManager
from sqlalchemy.orm import Session
import wave
import io
from assistant.entity import InterviewSession, UserKnowledge
# 常量定义
DEFAULT_SAMPLE_RATE = 16000

class TaskManager:
    def __init__(self, llm_manager=None):
        self.clients: Dict[str, Dict] = {}
        if llm_manager:
            self.llm_manager = llm_manager
        else:
            from assistant.LLM.llm_manager import LLMManager
            self.llm_manager = LLMManager()
        # 初始化配置管理器
        self.config_manager = ConfigManager()
        self.file_manager = TosFileManager()

    async def build_asr_client(self) -> AsrWsClient:
        """
        建立ASR客户端连接
        
        Returns:
            AsrWsClient: 初始化好的ASR客户端
        """
        # 从配置管理器获取ASR配置
        asr_config = self.config_manager.get_asr_config()
        url = asr_config.get('url', 'wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async')
        segment_duration = asr_config.get('seg_duration', 200)
        app_key = asr_config.get('app_key', '')
        access_key = asr_config.get('access_key', '')
        
        # 创建ASR客户端实例
        client = AsrWsClient(url, segment_duration, app_key, access_key)
        return client
        

    async def init_interview_task(self, session_id: str, round_id: str, req: Any, websocket=None) -> None:
        """
        初始化面试任务

        Args:
            session_id: 会话ID
            round_id: 轮次ID
            req: ASR请求参数
            websocket: WebSocket连接对象
        """
        composite_key = f"{session_id}_{round_id}"
        if composite_key in self.clients:
            await self.stop_asr(composite_key)

        # 创建停止事件和队列
        stop_event = asyncio.Event()

        # 初始化各队列
        audio_q = asyncio.Queue(maxsize=500)
        asr_q = asyncio.Queue(maxsize=500)
        text_q = asyncio.Queue(maxsize=500)
        block_q = asyncio.Queue(maxsize=500)
        streaming_q = asyncio.Queue(maxsize=500)
        result_q = asyncio.Queue(maxsize=500)
        output_q = asyncio.Queue(maxsize=500)

        # 创建ASR客户端实例
        asr_client = await self.build_asr_client()

        # 保存客户端信息
        self.clients[composite_key] = {
            'asr_client': asr_client,
            'stop_event': stop_event,
            'audio_q': audio_q,
            'asr_q': asr_q,
            'text_q': text_q,
            'block_q': block_q,
            'streaming_q': streaming_q,
            'result_q': result_q,
            'output_q': output_q,
            'state': ASRState(),
            'status': 'starting',
            'websocket': websocket,
            'req': req,
            'asr_data_list': [],
            'session_id': session_id,
            'round_id': round_id
        }
    async def start_interview(self, session_id: str, round_id: str, req: Any, record_voice: bool = False, current_user_id: int = None, db: Session = None):
        """
        为指定轮次启动面试服务

        Args:
            session_id: 会话ID
            round_id: 轮次ID
            req: ASR请求参数
            record_voice: 是否记录语音
            current_user_id: 当前用户ID
            db: 数据库会话（可选）
        """
        composite_key = f"{session_id}_{round_id}"
        try:
            # 初始化面试任务
            await self.init_interview_task(session_id, round_id, req)
            knowledge_id = db.query(InterviewSession).filter(InterviewSession.id == session_id).first().knowledge_id
            if knowledge_id:
                collection_name = db.query(UserKnowledge).filter(UserKnowledge.id == knowledge_id).first().name
                if collection_name:
                    self.clients[composite_key]['collection_name'] = collection_name
                    logger.info(f"[启动知识库检索: {collection_name}")
                else:
                    logger.info(f"[未启动知识库检索]")

            # 存储 db 和 current_user_id 到客户端信息中
            self.clients[composite_key]['db'] = db
            self.clients[composite_key]['current_user_id'] = current_user_id

            # 建立ASR客户端连接
            asr_client = self.clients[composite_key]['asr_client']
            await asr_client.create_asr_connection()

            # 更新状态
            self.clients[composite_key]['status'] = 'running'

            # 启动各个子任务（使用create_task而不是gather）
            asr_sender_task = asyncio.create_task(self.asr_sender(composite_key, record_voice, current_user_id, db))
            asr_receive_task = asyncio.create_task(self.asr_receive(composite_key))
            segment_task = asyncio.create_task(self.task_segment_worker(composite_key))
            analysis_task = asyncio.create_task(self.task_analysis_worker(composite_key))
            send_task = asyncio.create_task(self.task_send_worker(composite_key))

            # 保存任务引用，便于后续取消
            self.clients[composite_key]['tasks'] = [asr_sender_task, asr_receive_task, segment_task, analysis_task, send_task]

            logger.info(f"ASR service started for session {session_id}, round {round_id}")
        except Exception as e:
            logger.error(f"Error starting ASR service for session {session_id}, round {round_id}: {e}")
            # 清理资源
            if composite_key in self.clients:
                await self.stop_asr(composite_key)
            raise
    
    async def asr_sender(self, composite_key: str, record_voice: bool = False, current_user_id: int = None, db: Session = None):
        """
        给ASR服务端发送音频数据

        Args:
            composite_key: 复合键（session_id_round_id）
        """
        client = self.clients[composite_key]
        asr_client = client['asr_client']
        audio_q = client['audio_q']
        stop_event = client['stop_event']
        session_id = client.get('session_id', composite_key)
        round_id = client.get('round_id', '')
        first_packet = True
        SAMPLE_RATE = 16000 
        wav_buffer = None
        wf = None
        if record_voice:
            wav_buffer = io.BytesIO()
            wf = wave.open(wav_buffer, "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)

        # 在一个循环中不断发送音频数据
        while not stop_event.is_set():
            try:
                # 为audio_q.get()添加超时，避免长时间阻塞
                audio_data = await asyncio.wait_for(audio_q.get(), timeout=0.1)
                if record_voice and wf:
                    wf.writeframes(audio_data)
                # 检查音频格式
                if not isinstance(audio_data, bytes):
                    logger.warning(f"Invalid audio data format: {type(audio_data)}")
                    continue
                
                # 为第一个数据包添加wav格式头
                if first_packet:
                    wav_header = asr_client.build_wav_header(
                        sample_rate=SAMPLE_RATE,
                        channels=1,
                        bits_per_sample=16,
                        data_size=0,
                    )
                    audio_data = wav_header + audio_data
                    first_packet = False
                    # logger.info(f"Added wav header to audio data for session {session_id}")
                
                # 发送音频数据
                try:
                    await asr_client.send_audio2asr(audio_data)
                    # logger.info(f"Sent audio data for session {session_id}, data length: {len(audio_data)}")
                except Exception as e:
                    # 检查是否是WebSocket关闭错误
                    if "Cannot write to closing transport" in str(e) or "WebSocket connection closed" in str(e):
                        logger.info(f"WebSocket connection closed, stopping ASR sender for session {session_id}")
                        stop_event.set()
                    else:
                        logger.error(f"Error in ASR sender: {e}")
                    # 短暂休眠，避免CPU占用过高
                    await asyncio.sleep(0.1)
                
                # 短暂休眠，让出控制权给其他任务
                await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                # 超时后继续循环，避免阻塞
                continue
            except Exception as e:
                logger.error(f"Error in asr_sender: {e}")
                # 发生异常时短暂休眠，避免CPU占用过高
                await asyncio.sleep(0.1)
                continue
        if record_voice and wf:
            try:
                wf.close()
                self.file_manager.upload_file(
                    db=db,
                    user_id=current_user_id,
                    session_id=session_id,
                    file_content=wav_buffer.getvalue(),
                    filename=f"{current_user_id}_{session_id}_{round_id}.wav",
                    file_type='voice'
                )
                logger.info(f"Uploaded audio file for session {session_id}, round {round_id}")
            except Exception as e:
                logger.error(f"Error in asr_sender upload: {e}")



    async def asr_receive(self, composite_key: str):
        """
        从ASR服务端接收结果

        Args:
            composite_key: 复合键（session_id_round_id）
        """
        client = self.clients[composite_key]
        asr_client = client['asr_client']
        asr_q = client['asr_q']
        text_q = client['text_q']
        stop_event = client['stop_event']
        state = client['state']
        session_id = client.get('session_id', composite_key)
        

        # 在一个循环中不断接收ASR结果
        while not stop_event.is_set():
            try:
                # 接收ASR结果
                await asr_client.receive_asr_response(
                    asr_queue=asr_q,
                    text_q=text_q,
                    state=state,
                    session_id=session_id
                )
                
                # 短暂休眠，让出控制权给其他任务
                await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                # 超时后继续循环，避免阻塞
                continue
            except Exception as e:
                # 检查是否是WebSocket关闭错误
                if "Cannot write to closing transport" in str(e) or "WebSocket connection closed" in str(e):
                    logger.info(f"WebSocket connection closed, stopping ASR receiver for session {session_id}")
                    stop_event.set()
                else:
                    logger.error(f"Error in ASR receiver: {e}")
                # 发生异常时短暂休眠，避免CPU占用过高
                await asyncio.sleep(0.1) 
                continue

    async def task_segment_worker(self, composite_key: str):
        """
        处理ASR结果，提取文本
        从text_q中取出内容，经过一些策略聚集一些内容生成block，放入到block_q中

        Args:
            composite_key: 复合键（session_id_round_id）
        """
        client = self.clients[composite_key]
        text_q = client['text_q']
        block_q = client['block_q']
        stop_event = client['stop_event']
        state = client['state']
        asr_data_list = client['asr_data_list']
        session_id = client.get('session_id', composite_key)
        max_block_length = 5  # 最大block长度
        current_block = []
        prev_silence = False
        logger.info(f"task_segment_worker started for session {session_id}")
        
        while not stop_event.is_set():
            try:
                # 为text_q.get()添加超时，避免长时间阻塞
                text = await asyncio.wait_for(text_q.get(), timeout=0.5)
                if text:
                    asr_data_list.append(text)
                    logger.info(f"[segment_worker] Received text from text_q: {text}")

                if text is not None:
                    text_content = text.get('text')
                    if text_content:
                        current_block.append(text_content)
                        logger.info(f"[segment_worker] Added to current_block, length: {len(current_block)}")
                        
                        # 长度触发
                        if len(current_block) >= max_block_length:
                            block_text = ' '.join(current_block)
                            await block_q.put(block_text)
                            logger.info(f"[length ]Generated block: {block_text}")
                            current_block.clear()
                            
                        # 收到文本后重置静默状态
                        prev_silence = False
            except asyncio.TimeoutError:
                pass
            
            # 检查静默状态
            async with state.lock:
                is_silence = state.is_silence
            
            logger.debug(f"[segment_worker] is_silence: {is_silence}, prev_silence: {prev_silence}, current_block len: {len(current_block)}")
            
            # 静默触发：从有声音变为静默时触发
            if is_silence and not prev_silence and current_block:
                block_text = ' '.join(current_block)
                await block_q.put(block_text)
                logger.info(f"[silence ]Generated block: {block_text}")
                current_block.clear()
            
            prev_silence = is_silence
    
    async def task_analysis_worker(self, composite_key: str):
        """
        处理文本，调用LLM分析
        从block_q中获取内容，经过llm_analysis分析，生成结果并放入streaming_q、当生成完一整句话后放入result_q
        Args:
            composite_key: 复合键（session_id_round_id）
        """
        client = self.clients[composite_key]
        block_q = client['block_q']
        streaming_q = client['streaming_q']
        result_q = client['result_q']
        stop_event = client['stop_event']
        state = client['state']
        # 使用get方法避免KeyError，collection_name可能不存在
        collection_name = client.get('collection_name') or None
        session_id = client.get('session_id', composite_key)
        logger.info(f"task_analysis_worker started for {composite_key}, collection_name: {collection_name}")

        index = 0
        
        while not stop_event.is_set():
            try:
                # 检查队列状态
                if stop_event.is_set():
                    logger.info(f"task_analysis_worker stop_event set, exiting")
                    break
                    
                logger.debug(f"task_analysis_worker waiting for block_q, current qsize: {block_q.qsize()}")
                
                # 为block_q.get()添加超时，避免长时间阻塞
                block_text = await asyncio.wait_for(block_q.get(), timeout=0.1)
                logger.info(f"Received block from block_q: {block_text}")
                if block_text:
                    # 调用LLM分析
                    index += 1
                    llm_result = await self.llm_manager.analyze(block_text, streaming_q, stop_event,index,collection_name)
                    
                    if llm_result:
                        # 放入streaming_q（流式输出）
                        await streaming_q.put(llm_result)
                        
                        # 检查是否是完整的句子（简单判断：以句号、问号或感叹号结尾）
                        if any(block_text.endswith(punct) for punct in ['.', '。', '?', '？', '!', '！']):
                            await result_q.put(llm_result)
                
                # 短暂休眠，让出控制权给其他任务
                await asyncio.sleep(0.01)
            except asyncio.TimeoutError:
                # 超时后继续循环，避免阻塞
                continue
            except Exception as e:
                logger.error(f"Error in task_analysis_worker: {e}")
                # 发生异常时短暂休眠，避免CPU占用过高
                await asyncio.sleep(0.1)
                continue

    async def task_send_worker(self, composite_key: str):
        """
        发送ASR结果到WebSocket
        1. asr_q,streaming_q,result_q 中的内容放入output_q
        Args:
            composite_key: 复合键（session_id_round_id）
        """
        client = self.clients[composite_key]
        asr_q = client['asr_q']
        result_q = client['result_q']
        streaming_q = client['streaming_q']
        output_q = client['output_q']
        stop_event = client['stop_event']
        
        while not stop_event.is_set():
            try:
                # 检查asr_q
                if not asr_q.empty():
                    try:
                        asr_data = await asyncio.wait_for(asr_q.get(), timeout=0.05)
                        await output_q.put({'type': 'asr', 'data': asr_data})
                    except asyncio.TimeoutError:
                        pass
                
                # 检查result_q
                if not result_q.empty():
                    try:
                        result_data = await asyncio.wait_for(result_q.get(), timeout=0.05)
                        await output_q.put({'type': 'result', 'data': result_data})
                    except asyncio.TimeoutError:
                        pass
                
                # 检查streaming_q
                if not streaming_q.empty():
                    try:
                        streaming_data = await asyncio.wait_for(streaming_q.get(), timeout=0.05)
                        await output_q.put({'type': 'streaming', 'data': streaming_data})
                    except asyncio.TimeoutError:
                        pass
                
                # 短暂休眠，让出控制权给其他任务
                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in task_send_worker: {e}")
                # 发生异常时短暂休眠，避免CPU占用过高
                await asyncio.sleep(0.1)
    
    def get_output_queue(self, composite_key: str):
        """
        获取指定会话的输出队列

        Args:
            composite_key: 复合键（session_id_round_id）

        Returns:
            asyncio.Queue: ASR队列，如果会话不存在则返回None
        """
        if composite_key in self.clients:
            return self.clients[composite_key]['output_q']
        return None

    def get_audio_queue(self, composite_key: str):
        """
        获取指定会话的音频队列

        Args:
            composite_key: 复合键（session_id_round_id）

        Returns:
            asyncio.Queue: 音频队列，如果会话不存在则返回None
        """
        if composite_key in self.clients:
            return self.clients[composite_key]['audio_q']
        return None

    def set_websocket(self, composite_key: str, websocket):
        """
        将websocket连接与composite_key关联

        Args:
            composite_key: 复合键（session_id_round_id）
            websocket: WebSocket连接对象
        """
        if composite_key in self.clients:
            self.clients[composite_key]['websocket'] = websocket
            logger.info(f"WebSocket connection updated for {composite_key}")


    async def stop_asr(self, composite_key: str) -> None:
        """
        为用户停止ASR服务

        Args:
            composite_key: 复合键（session_id_round_id）
        """
        if composite_key not in self.clients:
            return

        client_info = self.clients[composite_key]
        state = client_info.get("state")
        asr_data_list = client_info.get("asr_data_list")

        # 1️⃣ 标记状态
        if state:
            state.connected = False

        # 2️⃣ stop event
        if client_info.get("stop_event"):
            client_info["stop_event"].set()

        # 3️⃣ 关闭 websocket（防止新数据）
        ws = client_info.get("websocket")
        if ws:
            try:
                await ws.close()
            except Exception:
                pass

        # 4️⃣ cancel tasks
        tasks = client_info.get("tasks", [])
        for task in tasks:
            task.cancel()

        # 5️⃣ 等待任务结束
        await asyncio.gather(*tasks, return_exceptions=True)

        # 6️⃣ 关闭 ASR
        asr_client = client_info.get("asr_client")
        if asr_client and hasattr(asr_client, "session"):
            try:
                await asr_client.session.close()
            except Exception:
                pass

        # 7️⃣ 处理 asr_data_list 并写入 Markdown 文件
        if asr_data_list:
            current_user_id = client_info.get('current_user_id') or (getattr(client_info.get('req'), 'user_id', None) if client_info.get('req') else None)
            if current_user_id:
                try:
                    from assistant.file.file_manager import TosFileManager
                    file_manager = TosFileManager()
                    session_id = client_info.get('session_id', composite_key)
                    round_id = client_info.get('round_id', '')
                    file_manager.save_asr_data_to_markdown(
                        asr_data_list=asr_data_list,
                        session_id=session_id,
                        current_user_id=current_user_id,
                        db=client_info.get('db')
                    )
                except Exception as e:
                    logger.error(f"Error saving ASR data to markdown: {e}")

        # 8️⃣ 删除
        if composite_key in self.clients:
            del self.clients[composite_key]

