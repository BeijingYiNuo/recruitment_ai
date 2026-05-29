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
import json

ADVICE_TAG = "<<<ADVICE>>>"
EVAL_TAG = "<<<EVALUATION>>>"
END_TAG = "<<<END>>>"
SKIP_TAG = "<<<SKIP>>>"
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

    async def analyze_reply(self, block: str, streaming_llm_q: asyncio.Queue,
                            stop_event: asyncio.Event, index: int,
                            collection_name: str = None,
                            stage_context: str = "",
                            messages: list = None) -> dict:
        """
        Reply Agent: 流式分析文本，生成面试建议和评价

        Args:
            block: 文本块
            streaming_llm_queue: 流式LLM队列
            stop_event: 停止事件
            index: 索引序号
            collection_name: 知识库名称
            stage_context: 面试阶段上下文
            messages: 预组装的消息列表（含历史上下文），为 None 时使用默认单轮

        Returns:
            dict: {"advice": str, "evaluation": str} 完整的建议和评价文本
        """

        if messages is None:
            # 无上下文：传统模式，只基于当前 block 和知识库分析
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

            system_prompt = self.prompt_manager.generate_prompt(
                user_id="",
                template_name="analysis",
                knowledge_base_info=knowledge_base_info,
                stage_context=stage_context
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"当前面试对话单元：\n{block}"}
            ]
        else:
            # 有上下文：knowledge_base_info 已在外部注入到 system_prompt 中
            pass

        logger.info(f"[{time.strftime('%H:%M:%S')}] 开始分析文本...")
        stream = await self.llm_client.chat.completions.create(
            messages=messages,
            extra_body={"thinking": {"type": "disabled"}},
            model=self.config_manager.get_llm_config()['model'],
            max_tokens=500,
            stream=True,
        )

        result = await self.parse_reply_stream(stream, streaming_llm_q, stop_event, index)
        return result

    async def parse_reply_stream(self, stream, streaming_q, stop_event, index: int) -> dict:
        """
        解析 Reply Agent 流式输出（仅 ADVICE/EVALUATION/END，不含 TRANSITION）

        Returns:
            dict: {"advice": str, "evaluation": str} 完整的建议和评价文本
        """
        buffer = ""
        current_type = None
        advice_parts = []
        eval_parts = []

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
                # 0. 识别 SKIP → 跳过分析
                if SKIP_TAG in buffer:
                    logger.info(f"[parse_reply_stream] block#{index} LLM 输出 SKIP，跳过分析")
                    await streaming_q.put({"response_type": "done"})
                    return {"advice": "", "evaluation": ""}

                # 1. 识别 ADVICE
                if ADVICE_TAG in buffer:
                    current_type = "advice"
                    buffer = buffer.split(ADVICE_TAG, 1)[1]
                    continue

                # 2. 识别 EVALUATION
                if EVAL_TAG in buffer:
                    current_type = "evaluation"
                    buffer = buffer.split(EVAL_TAG, 1)[1]
                    continue

                # 3. 识别 END
                if END_TAG in buffer:
                    content_before = buffer.split(END_TAG, 1)[0].strip()
                    if content_before:
                        await streaming_q.put({
                            "response_type": current_type,
                            "index": index,
                            "content": content_before
                        })
                        if current_type == "advice":
                            advice_parts.append(content_before)
                        elif current_type == "evaluation":
                            eval_parts.append(content_before)
                    buffer = ""
                    current_type = None
                    break

                # 4. 防止 tag 被截断
                if any(tag.startswith(buffer) for tag in [ADVICE_TAG, EVAL_TAG, END_TAG, SKIP_TAG]):
                    break

                # 5. 正常输出（流式）
                if current_type and buffer:
                    await streaming_q.put({
                        "response_type": current_type,
                        "index": index,
                        "content": buffer
                    })
                    if current_type == "advice":
                        advice_parts.append(buffer)
                    elif current_type == "evaluation":
                        eval_parts.append(buffer)
                    buffer = ""
                    break

                break

        await streaming_q.put({"response_type": "done"})

        return {
            "advice": "".join(advice_parts),
            "evaluation": "".join(eval_parts),
        }

    async def analyze_flow(self, block: str, stage_context: str, messages: list = None) -> dict:
        """
        Flow Agent: 分类当前对话所属阶段（非流式调用，轻量快速）

        Args:
            block: 对话文本块
            stage_context: 阶段上下文（来自 StageManager.build_prompt_context()）
            messages: 预组装的消息列表（含历史上下文），为 None 时使用默认单轮

        Returns:
            dict: {
                "stage": str | None,  # 阶段key (如 "project")，None 表示维持当前
                "confidence": str,    # "high" / "medium" / "low"
                "reason": str,        # 判断理由
            }
        """
        if messages is None:
            system_prompt = self.prompt_manager.generate_prompt(
                user_id="",
                template_name="flow_agent",
                stage_context=stage_context
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"当前面试对话单元：\n{block}"}
            ]

        try:
            response = await self.llm_client.chat.completions.create(
                messages=messages,
                model=self.config_manager.get_llm_config()['model'],
                max_tokens=150,
                temperature=0.3,
                stream=False,
            )

            content = response.choices[0].message.content.strip()
            logger.info(f"[Flow Agent] Classification: {content}")

            try:
                result = json.loads(content)
                return {
                    "stage": result.get("stage"),
                    "confidence": result.get("confidence", "low"),
                    "reason": result.get("reason", ""),
                }
            except json.JSONDecodeError:
                logger.warning(f"[Flow Agent] JSON 解析失败，原始输出: {content}")
                return {"stage": None, "confidence": "low", "reason": "parse_error"}
        except Exception as e:
            logger.error(f"[Flow Agent] 调用失败: {str(e)}")
            return {"stage": None, "confidence": "low", "reason": "api_error"}
