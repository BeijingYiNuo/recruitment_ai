import asyncio
import time
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
from assistant.interview.stage_manager import StageManager
from asyncio import QueueEmpty
from assistant.context.memory_manager import ContextManager
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
        stage_cmd_q = asyncio.Queue(maxsize=10)
        manual_analysis_q = asyncio.Queue(maxsize=5)

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
            'stage_cmd_q': stage_cmd_q,
            'manual_analysis_q': manual_analysis_q,
            'state': ASRState(),
            'status': 'starting',
            'websocket': websocket,
            'req': req,
            'asr_data_list': [],
            'session_id': session_id,
            'round_id': round_id,
            'stage_manager': None,
            'context_manager': ContextManager()
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

            # 初始化面试阶段管理器
            self.clients[composite_key]['stage_manager'] = StageManager()
            logger.info(f"[面试阶段] 阶段管理器已初始化")

            # 初始化上下文管理器并注入LLM客户端（用于LTM压缩）
            ctx_mgr = self.clients[composite_key]['context_manager']
            ctx_mgr.set_llm_client(self.llm_manager.llm_client)
            logger.info(f"[上下文管理] 上下文管理器已初始化")

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
        从text_q中取出内容，按【说话人切换】生成block，放入到block_q中

        策略：
        - 同一说话人的连续 utterances 合并为一个 block
        - 说话人切换时立即 emit 上一个 block
        - max_block_length 作为安全上限（防止单人说太长阻塞）
        - 静默时也触发 emit（当前说话人说完后停顿）

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
        max_block_length = 30  # 同一说话人安全上限
        min_block_chars = 30  # 最短 block 长度（字符），短于此值不触发 LLM 分析
        current_block = []
        current_speaker = None
        prev_silence = False
        logger.info(f"[segment_worker] 启动 (speaker-group mode) session={session_id}")

        async def _emit_block():
            nonlocal current_block, current_speaker
            if not current_block:
                return
            block_text = ' '.join(current_block)

            # 过滤过短的 block（通常是语气回应、嗯、是等），不触发 LLM 分析
            if len(block_text) < min_block_chars:
                logger.info(f"[segment_worker] 丢弃短 block (speaker={current_speaker}, "
                            f"chars={len(block_text)}): {block_text[:60]}...")
                current_block = []
                current_speaker = None
                return

            await block_q.put((block_text, current_speaker))
            logger.info(f"[segment_worker] emit block (speaker={current_speaker}, "
                        f"segments={len(current_block)}): {block_text[:80]}...")
            current_block = []
            current_speaker = None

        async def _on_utterance(text_data: dict):
            nonlocal current_block, current_speaker

            text_content = text_data.get('text', '')
            speaker_id = text_data.get('speaker_id')
            if not text_content:
                return

            # 如果说话人切换了 → 先 emit 之前的 block
            if current_speaker is not None and speaker_id != current_speaker and current_block:
                await _emit_block()

            current_block.append(text_content)
            current_speaker = speaker_id
            logger.debug(f"[segment_worker] 累积 speaker={speaker_id} "
                         f"segments={len(current_block)}")

            # 安全上限触发
            if len(current_block) >= max_block_length:
                await _emit_block()

        while not stop_event.is_set():
            try:
                text = await asyncio.wait_for(text_q.get(), timeout=0.5)
                if text:
                    asr_data_list.append(text)
                    await _on_utterance(text)
                    # 收到文本后重置静默状态
                    prev_silence = False
            except asyncio.TimeoutError:
                pass

            # 检查静默状态 → 说话人停顿后 emit
            async with state.lock:
                is_silence = state.is_silence

            if is_silence and not prev_silence and current_block:
                await _emit_block()

            prev_silence = is_silence
    
    async def task_analysis_worker(self, composite_key: str):
        """
        处理文本，调用LLM分析
        从block_q中获取内容 → Reply Agent (流式) → Flow Agent (每N轮分类阶段)
        同时从stage_cmd_q接收手动阶段切换指令
        """
        client = self.clients[composite_key]
        block_q = client['block_q']
        streaming_q = client['streaming_q']
        result_q = client['result_q']
        stop_event = client['stop_event']
        state = client['state']
        stage_cmd_q = client['stage_cmd_q']
        collection_name = client.get('collection_name') or None
        session_id = client.get('session_id', composite_key)
        logger.info(f"task_analysis_worker started for {composite_key}, collection_name: {collection_name}")

        index = 0
        turn_counter = 0
        flow_check_counter = 0
        FLOW_CHECK_INTERVAL = 3  # Flow Agent 每 N 个 block 分类一次

        from assistant.interview.stage_manager import STAGE_ORDER as _STAGE_ORDER

        async def _send_stage_info(transition_info) -> bool:
            """如果阶段有变化则推送 stage_info 到前端"""
            if not transition_info:
                return False
            logger.info(f"[面试阶段] 当前: {transition_info['display_name']}")
            await streaming_q.put({
                "response_type": "stage_info",
                "stage": transition_info["current_stage"],
                "display_name": transition_info["display_name"],
                "stage_index": transition_info["stage_index"],
                "total_stages": transition_info["total_stages"],
                "description": transition_info["description"],
            })
            return True

        async def _check_stage_cmd() -> bool:
            """检查是否有手动阶段切换指令，有则执行并返回 True"""
            nonlocal flow_check_counter
            try:
                cmd = stage_cmd_q.get_nowait()
            except QueueEmpty:
                return False

            logger.info(f"[手动阶段切换] 命令: {cmd}")
            stage_manager: StageManager = client.get('stage_manager')
            if not stage_manager:
                logger.warning("[手动阶段切换] 阶段管理器不存在")
                return True

            target = cmd.get("target_stage")
            direction = cmd.get("direction", "next")

            if target:
                transition_info = stage_manager.set_stage(target)
            elif direction == "prev":
                # 按列表顺序跳到上一阶段
                try:
                    cur_idx = _STAGE_ORDER.index(stage_manager.current_stage)
                    if cur_idx > 0:
                        transition_info = stage_manager.set_stage(_STAGE_ORDER[cur_idx - 1].value)
                    else:
                        transition_info = None
                except ValueError:
                    transition_info = None
            else:
                # 按列表顺序跳到下一阶段
                try:
                    cur_idx = _STAGE_ORDER.index(stage_manager.current_stage)
                    if cur_idx < len(_STAGE_ORDER) - 1:
                        transition_info = stage_manager.set_stage(_STAGE_ORDER[cur_idx + 1].value)
                    else:
                        transition_info = None
                except ValueError:
                    transition_info = None

            await _send_stage_info(transition_info)
            flow_check_counter = 0  # 重置，避免刚切又被 Flow Agent 改掉
            return True

        context_manager: ContextManager = client.get('context_manager')
        manual_analysis_q: asyncio.Queue = client.get('manual_analysis_q')
        last_analysis_time: float = 0
        MIN_AUTO_ANALYSIS_INTERVAL = 8.0  # 自动分析最小间隔（秒），防止频繁调 LLM

        async def _do_analyze(block_text: str, cur_index: int, turn_index: int, speaker: str = None) -> dict:
            """执行 Reply Agent 分析（萃取公共逻辑）"""
            nonlocal last_analysis_time, flow_check_counter
            last_analysis_time = time.time()

            stage_manager: StageManager = client.get('stage_manager')
            stage_context = stage_manager.build_prompt_context() if stage_manager else ""

            # 知识库检索
            knowledge_base_info = ""
            if collection_name:
                try:
                    knowledge_base_info = await self.llm_manager.knowledge_manager.search_knowledge(
                        search_text=block_text,
                        collection_name=collection_name
                    )
                except Exception as e:
                    logger.error(f"知识库检索失败: {str(e)}")

            if context_manager:
                system_prompt = self.llm_manager.prompt_manager.generate_prompt(
                    user_id="",
                    template_name="analysis",
                    knowledge_base_info=knowledge_base_info,
                    stage_context=stage_context
                )
                reply_messages = context_manager.build_reply_messages(
                    system_prompt, block_text, cur_index,
                    
                )
                flow_prompt = self.llm_manager.prompt_manager.generate_prompt(
                    user_id="",
                    template_name="flow_agent",
                    stage_context=stage_context
                )
                flow_messages = context_manager.build_flow_messages(
                    flow_prompt, block_text
                )
            else:
                reply_messages = None
                flow_messages = None

            # ===== Reply Agent =====
            result = await self.llm_manager.analyze_reply(
                block_text, streaming_q, stop_event, cur_index,
                collection_name, stage_context or "",
                messages=reply_messages
            )

            advice = result.get("advice", "")
            evaluation = result.get("evaluation", "")

            if advice or evaluation:
                logger.info(f"[分析] block#{cur_index} -> ADVICE/EVALUATION 已生成，advice_len={len(advice)}, eval_len={len(evaluation)}")
            else:
                logger.info(f"[分析] block#{cur_index} -> LLM 输出 SKIP，跳过本轮分析")

            # ===== 存入上下文 =====
            if context_manager:
                context_manager.push_turn(block_text, turn_index, speaker=speaker)
                context_manager.update_last_advice(
                    advice=advice,
                    evaluation=evaluation
                )
                logger.info(
                    f"[上下文] block#{cur_index} "
                    f"advice_len={len(advice)} "
                    f"eval_len={len(evaluation)}"
                )

            # ===== Flow Agent（每 N 轮分类一次）=====
            flow_check_counter += 1
            if flow_check_counter >= FLOW_CHECK_INTERVAL and stage_manager:
                flow_check_counter = 0
                logger.info(f"[Flow Agent] 分类阶段 (block #{cur_index})")
                flow_result = await self.llm_manager.analyze_flow(
                    block_text, stage_context or "",
                    messages=flow_messages
                )
                identified_stage = flow_result.get("stage")
                if identified_stage:
                    logger.info(f"[Flow Agent] 分类结果: {identified_stage} "
                                f"(confidence={flow_result.get('confidence')})")
                    transition_info = stage_manager.set_stage(identified_stage)
                    await _send_stage_info(transition_info)

            return result

        while not stop_event.is_set():
            try:
                # ========== 1. 优先检查手动切换指令 ==========
                if await _check_stage_cmd():
                    await asyncio.sleep(0.01)
                    continue

                # ========== 2. 检查手动分析指令 ==========
                try:
                    manual_cmd = manual_analysis_q.get_nowait()
                    logger.info(f"[手动分析] 收到指令: {manual_cmd}")
                    if context_manager:
                        recent = context_manager.stm.get_recent(6)
                        combined = " ".join(t.text for t in recent if t.text)
                        logger.info(f"[手动分析] 取最近 {len(recent)} 条 STM 内容: {combined[:80]}...")
                        if combined.strip():
                            index += 1
                            turn_counter += 1
                            await _do_analyze(combined, index, turn_counter)
                except QueueEmpty:
                    pass

                # ========== 3. 从 block_q 取内容 ==========
                try:
                    block_item = await asyncio.wait_for(block_q.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                if isinstance(block_item, tuple):
                    block_text, block_speaker = block_item
                else:
                    block_text, block_speaker = block_item, None

                if not block_text:
                    continue

                index += 1
                turn_counter += 1
                flow_check_counter += 1

                logger.info(f"[分析] block#{index} speaker={block_speaker}: {block_text[:80]}...")

                # ========== 4. 判断是否触发 LLM 分析（自动分析有最小间隔）==========
                now = time.time()
                if now - last_analysis_time >= MIN_AUTO_ANALYSIS_INTERVAL:
                    await _do_analyze(block_text, index, turn_counter, speaker=block_speaker)
                else:
                    # 间隔内：仅存入 STM，不调 LLM
                    if context_manager:
                        context_manager.push_turn(block_text, turn_counter, speaker=block_speaker)
                    logger.info(f"[分析] 跳过 block#{index}（距上次分析 {now - last_analysis_time:.1f}s < {MIN_AUTO_ANALYSIS_INTERVAL:.0f}s）")

                await asyncio.sleep(0.01)
            except Exception as e:
                logger.error(f"Error in task_analysis_worker: {e}", exc_info=True)
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

    def get_manual_analysis_queue(self, composite_key: str):
        """获取手动分析队列"""
        if composite_key in self.clients:
            return self.clients[composite_key].get('manual_analysis_q')
        return None

    def get_stage_cmd_queue(self, composite_key: str):
        """
        获取指定会话的阶段命令队列

        Args:
            composite_key: 复合键（session_id_round_id）

        Returns:
            asyncio.Queue: 阶段命令队列，如果会话不存在则返回None
        """
        if composite_key in self.clients:
            return self.clients[composite_key].get('stage_cmd_q')
        return None


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

