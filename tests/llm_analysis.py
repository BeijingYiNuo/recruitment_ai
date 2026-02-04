from openai import AsyncOpenAI
import sys
import os
from utils.logger import logger

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.knowledge_trigger import KnowledgeTrigger
from tests.vector_store.VikingDB_search import search_knowledge
from tests.prompts import ANALYSIS_PROMPT, Prompts
import time
class Conf:
    openai_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    openai_apikey: str = "76a878dc-4905-44c3-858c-8ef33006250f"
    openai_model: str = "doubao-seed-1-6-251015"

class llm_analysis:
    def __init__(self, memory_rounds: int = 5, use_same_api: bool = False, shared_client: AsyncOpenAI = None):
        """
        初始化面试分析类
        
        Args:
            memory_rounds: 短期记忆的轮次数，超过此轮次的历史将被总结
            use_same_api: 是否与 llm_SegmentJudge 共用同一个豆包API客户端
            shared_client: 共享的API客户端实例（如果use_same_api为True）
        """
        self.memory_rounds = memory_rounds
        self.short_term_memory = []
        self.long_term_summary = ""
        self.knowledge_base = {}
        self.conversation_rounds = 0
        self.llm_call_count = 0
        self.timeout_call_count = 0
        
        if use_same_api and shared_client:
            self.client = shared_client
        elif use_same_api:
            self.client = None
        else:
            self.client = AsyncOpenAI(
                api_key=Conf.openai_apikey,
                base_url=Conf.openai_url,
            )
        
        self.extra_body = {"thinking": {"type": "disabled"}}
    
    
    
    def _update_memory(self, block: str) -> str:
        """
        更新记忆管理
        
        Args:
            block: 当前的问答单元
        """
        
        self.conversation_rounds += 1

        if not self.short_term_memory:
            self.short_term_memory.append(block)
            return ""
        
        context = "\n\n".join(
            [f"[历史对话单元{i+1}]\n{b}" for i,b in enumerate(self.short_term_memory)]
        )
        self.short_term_memory.append(block)
        return context
        
        
    
    async def analyze(self, block: str, external_client: AsyncOpenAI = None, trigger_type: str = "semantic", knowledge_trigger: KnowledgeTrigger = None) -> dict:
        """
        分析面试者的回答
        
        Args:
            block: 面试对话的一个完整问答单元
            external_client: 外部提供的API客户端（如果共用API）
            
        Returns:
            包含追问问题和评价的字典
        """
        result = knowledge_trigger.hybrid_trigger(block)
        
        # 处理知识库检索结果
        knowledge_base_info = "无相关知识库信息需要参考"
        if result:
            # 调用知识库检索，获取相关文档
            knowledge_results = search_knowledge(query=block, k=3)
            if knowledge_results:
                knowledge_base_info = "\n".join([f"- {item[:200]}..." for item in knowledge_results])
        
        # 构建系统提示词
        system_prompt = ANALYSIS_PROMPT.replace("{knowledge_base_info}", knowledge_base_info)

        messages = [
            {"role": "system", "content": system_prompt}
        ]
        short_context = self._update_memory(block)
        if short_context:
            messages.append(
                {"role": "user", "content":f"以下是最近几轮面试对话上下文(短期记忆):\n{short_context}"}
            )
        messages.append(
            {"role":"user", "content": f"当前面试对话单元：\n{block}"}
        )

        client = external_client if external_client else self.client
        
        resp = await client.chat.completions.create(
            model=Conf.openai_model,
            messages=messages,
            extra_body=self.extra_body,
            max_tokens=500,
            stream=False,
        )
        if trigger_type == "semantic":
            self.llm_call_count += 1
            logger.info(f"[{time.strftime('%H:%M:%S')}] Analysi_Call #{self.llm_call_count}")
        else:
            logger.info(f"[{time.strftime('%H:%M:%S')}] time out Analysi_Call #{self.timeout_call_count}")


        result = resp.choices[0].message.content.strip()
        
        return self._parse_result(result, block=block)
    
    def _parse_result(self, result: str,block: str) -> dict:
        """
        解析LLM返回的结果
        
        Args:
            result: LLM返回的原始结果
            
        Returns:
            包含追问问题和评价的字典
        """
        follow_up_questions = []
        evaluation = ""
        
        lines = result.split('\n')
        current_section = None
        got_question = False
        
        for line in lines:
            line = line.strip()
            if line.startswith('【建议】'):
                current_section = 'questions'
                got_question = False
            elif line.startswith('【面试者评价】'):
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
    
    def get_memory_summary(self) -> str:
        """
        获取记忆摘要
        
        Returns:
            长期记忆和短期记忆的摘要
        """
        summary = f"长期记忆摘要：\n{self.long_term_summary}\n\n"
        summary += f"短期记忆（最近{len(self.short_term_memory)}轮）：\n"
        summary += "\n".join(self.short_term_memory)
        return summary
    
    def clear_memory(self):
        """
        清空所有记忆
        """
        self.short_term_memory = []
        self.long_term_summary = ""
        self.conversation_rounds = 0