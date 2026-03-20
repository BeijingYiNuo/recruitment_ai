from openai import AsyncOpenAI
import asyncio
import time
from typing import Dict, Any, Optional, AsyncGenerator

from utils.logger import logger
from knowledge.knowledge_manager import KnowledgeManager

class LLMManager:
    def __init__(self):
        self.processors: Dict[str, Dict] = {}
        self.knowledge_manager = KnowledgeManager()
        self.client_cache: Dict[str, AsyncOpenAI] = {}
    
    def get_llm_queue(self, user_id: str) -> Optional[asyncio.Queue]:
        """
        获取用户的LLM队列
        
        Args:
            user_id: 用户ID
            
        Returns:
            Optional[asyncio.Queue]: LLM队列
        """
        if user_id in self.processors:
            return self.processors[user_id].get('llm_queue')
        return None
    
    async def start_llm_processing(self, user_id: str, text_q: asyncio.Queue, 
                                  llm_queue: asyncio.Queue, streaming_llm_queue: asyncio.Queue):
        """
        启动用户的LLM处理
        
        Args:
            user_id: 用户ID
            text_q: 文本队列
            llm_queue: LLM队列
            streaming_llm_queue: 流式LLM队列
        """
        # 停止之前的LLM处理
        if user_id in self.processors:
            await self.stop_llm_processing(user_id)
        
        # 创建停止事件
        stop_event = asyncio.Event()
        
        # 保存处理器信息
        self.processors[user_id] = {
            'stop_event': stop_event,
            'text_q': text_q,
            'llm_queue': llm_queue,
            'streaming_llm_queue': streaming_llm_queue,
            'task': None,
            'status': 'starting'
        }
        
        # 启动LLM处理任务
        task = asyncio.create_task(self._llm_processor(user_id, text_q, llm_queue, streaming_llm_queue, stop_event))
        self.processors[user_id]['task'] = task
        self.processors[user_id]['status'] = 'running'
    
    async def stop_llm_processing(self, user_id: str):
        """
        停止用户的LLM处理
        
        Args:
            user_id: 用户ID
        """
        if user_id not in self.processors:
            return
        
        processor_info = self.processors[user_id]
        if processor_info['stop_event']:
            processor_info['stop_event'].set()
        
        if processor_info['task']:
            try:
                processor_info['task'].cancel()
                await asyncio.wait_for(processor_info['task'], timeout=5.0)
            except Exception:
                pass
        
        del self.processors[user_id]
    
    def get_active_processors(self) -> list:
        """
        获取活跃的LLM处理器列表
        
        Returns:
            list: 活跃处理器列表
        """
        active_processors = []
        for user_id, processor_info in self.processors.items():
            if processor_info.get('status') == 'running':
                active_processors.append(user_id)
        return active_processors
    
    async def _judge_segment(self, block: str, client: AsyncOpenAI) -> str:
        """
        判断对话是否应该分段
        
        Args:
            block: 文本块
            client: LLM客户端
            
        Returns:
            str: 判定结果 (SPLIT, CONTINUE, IGNORE)
        """
        from prompt.prompt_manager import PromptManager
        prompt_manager = PromptManager()
        segment_judge_prompt = prompt_manager.get_prompt_template('segment_judge')
        
        messages = [
            {"role": "system", "content": segment_judge_prompt},
            {"role": "user", "content": f"最近对话：\n{block}"}
        ]
        
        resp = await client.chat.completions.create(
            model="doubao-seed-1-6-251015",
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=20,
            stream=False,
        )
        
        return resp.choices[0].message.content.strip().upper()
    
    async def _llm_processor(self, user_id: str, text_q: asyncio.Queue, 
                             llm_queue: asyncio.Queue, streaming_llm_queue: asyncio.Queue, 
                             stop_event: asyncio.Event):
        """
        LLM处理器
        
        Args:
            user_id: 用户ID
            text_q: 文本队列
            llm_queue: LLM队列
            streaming_llm_queue: 流式LLM队列
            stop_event: 停止事件
        """
        try:
            # 初始化LLM客户端
            client = self._get_or_create_client()
            
            # 初始化知识库触发器
            knowledge_trigger = self.knowledge_manager.get_knowledge_trigger(user_id, client)
            
            buffer = []
            last_judge_time = time.time()
            last_sound_time = time.time()  # 初始化最后一次检测到声音的时间
            min_batch_size = 5
            judge_interval_min = 5.0
            judge_interval_max = 15.0
            continue_ignore_count = 0
            max_continue_ignore = 15
            silence_time = 3.0  # 静默时间阈值
            
            while not stop_event.is_set():
                try:
                    # 检查是否有静默（超过silence_time秒没有新数据）
                    current_time = time.time()
                    if current_time - last_sound_time > silence_time:
                        if buffer:
                            logger.info(f"用户 {user_id} 检测到静默，分析buffer内容")
                            # 构建分析文本
                            block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer])
                            buffer.clear()
                            
                            logger.info(f"Processing block for user {user_id} (silence): {block_text}")
                            
                            # 分析文本
                            result = await self._analyze(block_text, client, knowledge_trigger, 
                                                       streaming_llm_queue, stop_event)
                            
                            # 将结果放入队列
                            if llm_queue:
                                try:
                                    await llm_queue.put(result)
                                except asyncio.QueueFull:
                                    logger.info(f"LLM queue full for user {user_id}")
                    
                    # 等待获取队列中的数据
                    data = await asyncio.wait_for(text_q.get(), timeout=1.0)  # 缩短超时时间，以便更频繁地检查静默
                    
                    # 更新最后一次检测到声音的时间
                    last_sound_time = time.time()
                    
                    # 将数据添加到缓冲区
                    buffer.append(data)
                    
                    # 检查是否需要调用LLM
                    current_time = time.time()
                    time_elapsed = current_time - last_judge_time
                    
                    is_should_call_llm = (
                        (len(buffer) >= min_batch_size and time_elapsed >= judge_interval_min)
                        or
                        (time_elapsed >= judge_interval_max)
                    )

                    if is_should_call_llm:
                        # 构建分析文本
                        block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer])
                        
                        # 使用llm_seg判断是否应该分段
                        decision = await self._judge_segment(block_text, client)
                        last_judge_time = current_time
                        
                        if decision in {"IGNORE", "CONTINUE"}:
                            continue_ignore_count += 1
                            
                            if continue_ignore_count >= max_continue_ignore:
                                # 强制分析
                                buffer.clear()
                                continue_ignore_count = 0
                                
                                logger.info(f"LONG CONTINUE FORCE ANALYZE for user {user_id}: {block_text}")
                                
                                # 分析文本
                                result = await self._analyze(block_text, client, knowledge_trigger, 
                                                           streaming_llm_queue, stop_event)
                                
                                # 将结果放入队列
                                if llm_queue:
                                    try:
                                        await llm_queue.put(result)
                                    except asyncio.QueueFull:
                                        logger.info(f"LLM queue full for user {user_id}")
                            continue
                        
                        if decision == "SPLIT":
                            # 分段处理
                            buffer.clear()
                            continue_ignore_count = 0
                            
                            logger.info(f"SPLIT SEG BLOCK for user {user_id}: {block_text}")
                            
                            # 分析文本
                            result = await self._analyze(block_text, client, knowledge_trigger, 
                                                       streaming_llm_queue, stop_event)
                            
                            # 将结果放入队列
                            if llm_queue:
                                try:
                                    await llm_queue.put(result)
                                except asyncio.QueueFull:
                                    logger.info(f"LLM queue full for user {user_id}")
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error in LLM processor for user {user_id}: {e}")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            logger.debug(f"LLM processor cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"Unexpected error in LLM processor for user {user_id}: {e}")
        finally:
            logger.info(f"LLM processor exited for user {user_id}")
            if user_id in self.processors:
                self.processors[user_id]['status'] = 'stopped'

    
    def _get_or_create_client(self) -> AsyncOpenAI:
        """
        获取或创建LLM客户端
        
        Returns:
            AsyncOpenAI: LLM客户端
        """
        cache_key = "default"
        if cache_key not in self.client_cache:
            self.client_cache[cache_key] = AsyncOpenAI(
                api_key="76a878dc-4905-44c3-858c-8ef33006250f",
                base_url="https://ark.cn-beijing.volces.com/api/v3/",
            )
        return self.client_cache[cache_key]
    
    async def _analyze(self, block: str, client: AsyncOpenAI, knowledge_trigger: Any, 
                      streaming_llm_queue: asyncio.Queue, stop_event: asyncio.Event) -> dict:
        """
        分析文本
        
        Args:
            block: 文本块
            client: LLM客户端
            knowledge_trigger: 知识库触发器
            streaming_llm_queue: 流式LLM队列
            stop_event: 停止事件
            
        Returns:
            dict: 分析结果
        """
        # 检查是否需要停止
        if stop_event.is_set():
            return {
                'follow_up_questions': [],
                'evaluation': "",
                'block': block
            }
        
        # 判断是否需要检索知识库
        result = knowledge_trigger.hybrid_trigger(block)
        
        # 处理知识库检索结果
        knowledge_base_info = "无相关知识库信息需要参考"
        if result:
            # 调用知识库检索，获取相关文档
            from knowledge.knowledge_manager import KnowledgeManager
            knowledge_manager = KnowledgeManager()
            retrieval_start_time = time.time()
            knowledge_results = knowledge_manager.search_knowledge("", block, top_k=3)
            retrieval_end_time = time.time()
            retrieval_time = retrieval_end_time - retrieval_start_time
            logger.info(f"[{time.strftime('%H:%M:%S')}] RAG检索耗时: {retrieval_time:.4f} 秒")
            if knowledge_results:
                knowledge_base_info = "\n".join([f"- {item[:200]}..." for item in knowledge_results])
                logger.info(f"[{time.strftime('%H:%M:%S')}] RAG检索结果数量: {len(knowledge_results)}")
        
        # 构建系统提示词
        from prompt.prompt_manager import PromptManager
        prompt_manager = PromptManager()
        ANALYSIS_PROMPT = prompt_manager.get_prompt_template('analysis')
        system_prompt = ANALYSIS_PROMPT.replace("{knowledge_base_info}", knowledge_base_info)

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        
        # 添加当前对话
        messages.append(
            {"role":"user", "content": f"当前面试对话单元：\n{block}"}
        )

        llm_analysis_start_time = time.time()
        first_token_time = None
        
        # 使用流式响应
        stream = await client.chat.completions.create(
            model="doubao-seed-1-6-251015",
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=500,
            stream=True,
        )
        
        # 处理流式响应
        full_content = ""
        async for chunk in stream:
            if stop_event.is_set():
                break
            if chunk.choices and chunk.choices[0].delta:
                if chunk.choices[0].delta.content:
                    # 记录第一个token的时间
                    if first_token_time is None:
                        first_token_time = time.time()
                        time_to_first_token = first_token_time - llm_analysis_start_time
                        logger.info(f"[{time.strftime('%H:%M:%S')}] 到第一个token的时间: {time_to_first_token:.4f} 秒")
                    # 累加内容
                    full_content += chunk.choices[0].delta.content
                    # 实时传递数据到前端
                    if streaming_llm_queue:
                        try:
                            await streaming_llm_queue.put({
                                'type': 'follow_up' if '建议' in chunk.choices[0].delta.content else 'evaluation',
                                'content': chunk.choices[0].delta.content
                            })
                        except asyncio.QueueFull:
                            logger.info("流式队列已满，有丢失数据")
        
        llm_analysis_end_time = time.time()
        llm_use_time = llm_analysis_end_time - llm_analysis_start_time
        logger.info(f"[{time.strftime('%H:%M:%S')}] llm_analysis耗时: {llm_use_time:.4f} 秒")
        
        # 记录Token使用情况
        logger.info(f"[{time.strftime('%H:%M:%S')}] Token使用情况 - 响应中未包含Token信息（流式响应）")

        result = full_content.strip()
        
        return self._parse_result(result, block=block)
    
    def _parse_result(self, result: str, block: str) -> dict:
        """
        解析LLM返回的结果
        
        Args:
            result: LLM返回的原始结果
            block: 原始文本块
            
        Returns:
            dict: 包含追问问题和评价的字典
        """
        follow_up_questions = []
        evaluation = ""
        
        lines = result.split('\n')
        current_section = None
        got_question = False
        
        for line in lines:
            line = line.strip()
            if line.startswith('建议'):
                current_section = 'questions'
                got_question = False
            elif line.startswith('面试者评价'):
                current_section = 'evaluation'
            elif current_section == 'questions' and line:
                if not got_question:
                    # 提取建议内容，无论是否有编号
                    if line.startswith(('1.', '2.', '3.', '4.', '5.')):
                        follow_up_questions = [line[2:].strip()]
                    else:
                        follow_up_questions = [line.strip()]
                    got_question = True
            elif current_section == 'evaluation' and line:
                # 收集完整的评价内容，直到遇到下一个部分或文件结束
                evaluation += line + ' '
        logger.info(f"follow_up_questions: {follow_up_questions[:100]}")
        logger.info(f"evaluation: {evaluation[:100]}")
        # 去除评价末尾的空格
        evaluation = evaluation.strip()
        return {
            'follow_up_questions': follow_up_questions,
            'evaluation': evaluation,
            'block': block
        }
