
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

    
    



    

    async def parse_llm_stream(self, stream, streaming_q, stop_event, index: int):
        buffer = ""
        current_type = None

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
                # 🎯 1. 识别 ADVICE
                if ADVICE_TAG in buffer:
                    current_type = "advice"
                    buffer = buffer.split(ADVICE_TAG, 1)[1]
                    continue

                # 🎯 2. 识别 EVALUATION
                if EVAL_TAG in buffer:
                    current_type = "evaluation"
                    buffer = buffer.split(EVAL_TAG, 1)[1]
                    continue

                # 🎯 3. 识别 END
                if END_TAG in buffer:
                    # 输出剩余内容
                    if buffer.strip():
                        await streaming_q.put({
                            "response_type": current_type,
                            "index": index,
                            "content": buffer.strip()
                        })
                    buffer = ""
                    current_type = None
                    break

                # 🎯 4. 防止 tag 被截断（关键！！！）
                if any(tag.startswith(buffer) for tag in [ADVICE_TAG, EVAL_TAG, END_TAG]):
                    break

                # 🎯 5. 正常输出（流式）
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
