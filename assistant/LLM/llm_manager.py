from openai import AsyncOpenAI
import asyncio
import time
from typing import Dict, Any, Optional, AsyncGenerator

from assistant.utils.logger import logger
from assistant.knowledge.knowledge_manager import KnowledgeManager, KnowledgeTrigger
from assistant.ASR.state_manager import ASRState
from assistant.prompt.prompt_manager import PromptManager
from assistant.config.config_manager import ConfigManager
import re

ADVICE_TAG = "<<<ADVICE>>>"
EVAL_TAG = "<<<EVALUATION>>>"
END_TAG = "<<<END>>>"
TRANSITION_TAG = "<<<TRANSITION>>>"


class LLMManager:
    def __init__(self):
        self.knowledge_manager = KnowledgeManager()
        self.config_manager: ConfigManager = ConfigManager()
        self.prompt_manager = PromptManager()
        llm_config = self.config_manager.get_llm_config()
        self.llm_client = AsyncOpenAI(
            api_key=llm_config['api_key'],
            base_url=llm_config['url'],
        )

    async def analyze(self, block: str, streaming_llm_q: asyncio.Queue,
                      stop_event: asyncio.Event, index: int,
                      collection_name: str = None,
                      stage_context: str = "") -> dict:
        """
        分析文本

        Args:
            block: 文本块
            streaming_llm_queue: 流式LLM队列
            stop_event: 停止事件
            index: 索引序号
            collection_name: 知识库名称
            stage_context: 面试阶段上下文

        Returns:
            dict: {
                "has_transition": bool,  # LLM是否输出TRANSITION信号
                "stage_done": bool       # 程序判断阶段是否应结束
            }
        """

        # 检索知识库信息
        knowledge_base_info = ""
        if collection_name:
            try:
                logger.info(f"[{time.strftime('%H:%M:%S')}] 开始检索知识库...")
                knowledge_base_info = await self.knowledge_manager.search_knowledge(
                    search_text=block,
                    collection_name=collection_name
                )
                logger.info(f"[{time.strftime('%H:%M:%S')}] 知识库检索结果: {knowledge_base_info}")
            except Exception as e:
                logger.error(f"[{time.strftime('%H:%M:%S')}] 知识库检索失败: {str(e)}")
                knowledge_base_info = ""

        # 使用 PromptManager 生成提示词，动态注入知识库信息和阶段上下文
        system_prompt = self.prompt_manager.generate_prompt(
            user_id="",
            template_name="analysis",
            knowledge_base_info=knowledge_base_info,
            stage_context=stage_context
        )

        messages = [
            {"role": "system", "content": system_prompt}
        ]

        messages.append(
            {"role": "user", "content": f"当前面试对话单元：\n{block}"}
        )
        logger.info(f"[{time.strftime('%H:%M:%S')}] 开始分析文本...")
        stream = await self.llm_client.chat.completions.create(
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            model=self.config_manager.get_llm_config()['model'],
            max_tokens=500,
            stream=True,
        )

        result = await self.parse_llm_stream(stream, streaming_llm_q, stop_event, index)
        return result

    async def parse_llm_stream(self, stream, streaming_q, stop_event, index: int) -> dict:
        """
        解析LLM流式输出

        Returns:
            dict: {"has_transition": bool}
        """
        buffer = ""
        current_type = None
        has_transition = False

        async for chunk in stream:
            if stop_event.is_set():
                break

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = getattr(delta, "content", None)

            if not content:
                continue

            buffer += content

            while True:
                # 🎯 1. 识别 TRANSITION（优先级最高，不送到前端，仅记录信号）
                if TRANSITION_TAG in buffer:
                    has_transition = True
                    buffer = buffer.split(TRANSITION_TAG, 1)[1]
                    continue

                # 🎯 2. 识别 ADVICE
                if ADVICE_TAG in buffer:
                    current_type = "advice"
                    buffer = buffer.split(ADVICE_TAG, 1)[1]
                    continue

                # 🎯 3. 识别 EVALUATION
                if EVAL_TAG in buffer:
                    current_type = "evaluation"
                    buffer = buffer.split(EVAL_TAG, 1)[1]
                    continue

                # 🎯 4. 识别 END（去除标签本身，只发送前面的内容）
                if END_TAG in buffer:
                    content_before = buffer.split(END_TAG, 1)[0].strip()
                    if content_before:
                        await streaming_q.put({
                            "response_type": current_type,
                            "index": index,
                            "content": content_before
                        })
                    buffer = ""
                    current_type = None
                    break

                # 🎯 5. 防止 tag 被截断
                if any(tag.startswith(buffer) for tag in [ADVICE_TAG, EVAL_TAG, END_TAG, TRANSITION_TAG]):
                    break

                # 🎯 6. 正常输出（流式）
                if current_type and buffer:
                    await streaming_q.put({
                        "response_type": current_type,
                        "index": index,
                        "content": buffer
                    })
                    buffer = ""
                    break

                break

        await streaming_q.put({"response_type": "done"})
        return {"has_transition": has_transition}
