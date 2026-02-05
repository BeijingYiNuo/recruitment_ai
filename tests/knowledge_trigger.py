import sys
import os
import asyncio
from openai import AsyncOpenAI
import sys
import os
from tests.utils.logger import logger
# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.vector_store.VikingDB_search import search_knowledge
from tests.prompts import KNOWLEDGE_TRIGGER_PROMPT, Prompts
class Conf:
    openai_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    openai_apikey: str = "76a878dc-4905-44c3-858c-8ef33006250f"
    openai_model: str = "doubao-seed-1-6-251015"



class KnowledgeTrigger:
    """
    知识库检索触发判断器
    采用混合策略判断是否需要触发知识库检索
    """
    
    def __init__(self, shared_client: AsyncOpenAI = None):
        # 第一层：关键词快速触发规则
        self.MUST_SEARCH_KEYWORDS = [
            # 公司岗位信息
            "岗位", "招聘", "职位", "工作", "薪资", "福利", "待遇", "入职", "简历",
            # 制度流程
            "制度", "流程", "规定", "政策", "办法", "方案", "流程", "步骤", "要求",
            # 产品参数
            "产品", "参数", "功能", "特性", "规格", "型号", "价格", "报价",
            # 文档内容
            "文档", "资料", "文件", "内容", "信息", "数据", "详情", "说明"
        ]
        self.llm_trigger = shared_client
        
        # 第二层：轻量检索阈值设置
        self.HIGH_THRESHOLD = 0.8  # 高于此分数直接触发
        self.LOW_THRESHOLD = 0.6   # 低于此分数不触发
        # 分数在[LOW_THRESHOLD, HIGH_THRESHOLD]之间时触发第三层
        
        # 第三层：LLM分类提示词
        self.LLM_PROMPT = KNOWLEDGE_TRIGGER_PROMPT
    
    def rule_search(self, block_text):
        """
        第一层：关键词快速触发
        对必须查知识库的问题直接触发
        """
        block_text_lower = block_text.lower()
        for keyword in self.MUST_SEARCH_KEYWORDS:
            if keyword in block_text_lower:
                # print(f"关键词触发: 检测到关键词 '{keyword}'")
                return True
        return False
    
    def probe_search(self, block_text):
        """
        第二层：轻量检索
        看Top1文档相似度的分数，根据阈值决定是否触发
        """
        try:
            # 调用VikingDB_search进行轻量检索，只取top1并返回分数
            contents, scores = search_knowledge(query=block_text, k=1, return_scores=True)
            
            # 获取Top1分数
            if scores:
                top_score = scores[0]
            else:
                # 没有找到结果，使用一个较低的默认分数
                top_score = 0.5
            
            # print(f"轻量检索: Top1相似度分数为 {top_score}")
            
            if top_score >= self.HIGH_THRESHOLD:
                # print("轻量检索触发: 分数高于阈值")
                return True, "high"
            elif top_score < self.LOW_THRESHOLD:
                # print("轻量检索不触发: 分数低于阈值")
                return False, "low"
            else:
                # print("轻量检索: 分数在模糊区间，进入LLM分类")
                return None, "medium"
        except Exception as e:
            # print(f"轻量检索失败: {e}")
            return None, "medium"
    
    async def llm_search(self, block_text):
        """
        第三层：LLM分类层
        用于解决模糊问题、规则覆盖不到的问题
        """
        try:
            # 这里需要调用LLM API进行判断
            # 由于没有实际的LLM API调用，这里使用模拟判断
            # TODO: 实现实际的LLM API调用
            resp = await self.llm_trigger.chat.completions.create(
                model=Conf.openai_model,
                messages=[
                    {"role": "system", "content": self.LLM_PROMPT},
                    {"role": "user", "content": block_text}
                ],
                extra_body={"thinking": {"type": "disabled"}},
                max_tokens=500,
                stream=False
            )
            result = resp.choices[0].message.content.strip()
            if result == "需要":
                return True
            else:
                return False

        except Exception as e:
            # print(f"LLM分类失败: {e}")
            return False
    
    def hybrid_trigger(self, block_text):
        """
        混合策略触发函数
        按照三层策略顺序执行，决定是否触发知识库检索
        """
        logger.info(f"=== 开始混合策略触发判断 ===")
        
        # 第一层：关键词快速触发
        if self.rule_search(block_text):
            logger.info("=== 关键词触发 需要检索知识库 ===")
            return True
        # 第二层：轻量检索
        probe_result, score_level = self.probe_search(block_text)
        if probe_result is True:
            logger.info("=== 轻量检索触发 需要检索知识库 ===")
            return True
        elif probe_result is False:
            logger.info("=== 轻量检索触发 不需要检索知识库 ===")
            return False
        
        # 第三层：LLM分类
        if self.llm_search(block_text):
            logger.info("=== LLM分类触发 需要检索知识库 ===")
            return True
        else:
            logger.info("=== LLM分类触发 不需要检索知识库 ===")
            return False


if __name__ == "__main__":
    # 初始化触发器
    trigger = KnowledgeTrigger()
    
    # 测试案例
    test_cases = [
        "公司现在有哪些岗位在招聘？",
        "请假流程是怎样的？",
        "产品的主要参数有哪些？",
        "你好，最近怎么样？",
        "谢谢，辛苦了！",
        "公司的福利待遇如何？",
        "这个项目的具体要求是什么？"
    ]
    
    for test_case in test_cases:
        result = trigger.hybrid_trigger(test_case)
        print(f"测试结果: {'需要检索' if result else '不需要检索'}\n")
