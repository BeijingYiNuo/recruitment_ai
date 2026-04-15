
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

class LLMManager:
    def __init__(self):
        self.knowledge_manager = KnowledgeManager()
        self.config_manager: ConfigManager = ConfigManager()
        self.prompt_manager = PromptManager()
        self.llm_client = AsyncOpenAI(
            api_key=self.config_manager.get_llm_config()['api_key'],
            base_url=self.config_manager.get_llm_config()['url'],
        )

    async def analyze(self, block: str, streaming_llm_q: asyncio.Queue, stop_event: asyncio.Event,index: int) -> dict:
        """
        分析文本
        
        Args:
            block: 文本块
            streaming_llm_queue: 流式LLM队列
            stop_event: 停止事件
            
        Returns:
            dict: 分析结果
        """
        
        # 构建系统提示词
        ANALYSIS_PROMPT = self.prompt_manager.get_prompt_template('analysis')
        system_prompt = ANALYSIS_PROMPT

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        messages.append(
            {"role":"user", "content": f"当前面试对话单元：\n{block}"}
        )
        
        stream = await self.llm_client.chat.completions.create(
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            model=self.config_manager.get_llm_config()['model'],
            max_tokens=500,
            stream=True,
        )
        # async for chunk in stream:
        #     content = chunk.choices[0].delta.content or ""
        #     print(content, end="", flush=True)      
        await self.parse_llm_stream(stream, streaming_llm_q, stop_event,index)

    
    



    async def parse_llm_stream(self, stream, streaming_q, stop_event,index: int):
        buffer = ""
        sentence_buffer = ""
        SENTENCE_END = re.compile(r'[。！？?！]\s*$')
        current_type = None
        advice_index = 0

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

            # 🎯 1. 类型识别
            if current_type is None and "建议" in buffer:
                current_type = "advice"
                buffer = ""
                continue

            if current_type == "advice" and "面试者评价" in buffer:
                current_type = "evaluation"
                buffer = ""
                sentence_buffer = ""
                continue

            # =========================
            # 🎯 2. advice（流式 + 句子级）
            # =========================
            if current_type == "advice":
                sentence_buffer += content

                # 👉 流式输出（每个chunk）c
                await streaming_q.put({
                    "response_type": "advice",
                    "index": index,  # 当前句 index
                    "content": content
                })

                # 👉 判断句子结束
                if SENTENCE_END.search(sentence_buffer):

                    await streaming_q.put({
                        "response_type": "advice",
                        "index": index,
                        "content": sentence_buffer.strip()
                    })

                    sentence_buffer = ""

            # =========================
            # 🎯 3. evaluation（保持流式）
            # =========================
            elif current_type == "evaluation":
                await streaming_q.put({
                    "response_type": "evaluation",
                    "index": index,
                    "content": content
                })

        # 🎯 收尾
        if sentence_buffer.strip():
            await streaming_q.put({
                "response_type": "advice",
                "index": index,
                "content": sentence_buffer.strip()
            })

        await streaming_q.put({"response_type": "done"})