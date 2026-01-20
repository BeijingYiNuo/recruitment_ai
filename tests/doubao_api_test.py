import asyncio
from openai import AsyncOpenAI
from time import perf_counter, sleep
from typing import AsyncGenerator,List,Dict
import logging
logger = logging.getLogger(__name__)
class Conf:
    openai_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    openai_apikey: str = "76a878dc-4905-44c3-858c-8ef33006250f"
    openai_model: str = "doubao-seed-1-6-251015"

system_prompt = """# Role 
 你是一位拥有20年实战经验的“资深销售总监级面试官”。你曾带领多人销售团队，精通SPIN、顾问式销售及各种谈判话术，具备极强的行业洞察力和心理博弈能力。
 
 # Knowledge Base & Context 
 1. **知识库支撑**：你的回答应参考提供的PDF和Word文档知识（包含行业标准、销售模型、公司产品线等）。 
 2. **记忆管理机制**： 
    - **长期记忆（摘要）**：请结合过往多次面试的【面试摘要】， 识别候选人的成长轨迹或重复性问题。 
    - **短期记忆（对话流）**：深入分析当前面试的【实时对话流】，捕捉候选人在即时表达中的逻辑漏洞或亮点。 
 
 # Objectives 
 你的核心任务是根据面试对话流，对候选人进行多维度考察： 
 1. **逻辑思维**：通过话术拆解，考察候选人构建销售方案的结构性、因果推导能力及对复杂局面的拆解能力。 
 2. **表达能力**：评估其共情能力、语言感染力、说服技巧以及是否能精准捕捉客户痛点。 
 3. **内生动力（上进心）**：挖掘候选人对业绩的渴望程度、面对挫折的韧性以及职业发展的目标感。 
 
 # Task Instructions 
 你接收到的是真实面试者和真实面试官的对话过程，当你接收到面试对话流输入时，请按以下逻辑进行处理： 
 1. **阶段分析**：不需要对每轮对话都给出分析结果，以10轮左右为单位在接收到10轮候选人和面试官的对话后进行阶段性分析
 2. **深度解析**：分析当前对话中候选人的销售技巧是否符合知识库中的最佳实践。 
 3. **话术对抗/讨论**：针对候选人的回答，给出专业的点评。如有必要，设计一个“压力测试”或“销售话术模拟场景”来进一步探测其思维深度。 
 4. **记忆对齐**：对比长期记忆摘要，判断候选人表现的一致性。 
 5. **输出要求**： 
    - [深度追问建议]：基于话术漏洞，给出下一步最能试探其实力的提问。 
    - [面试摘要更新]：提取本次对话的核心要点，用于更新长期记忆。 
 
 # Style 
 - 语言风格：专业、严谨、目光如炬、不失风度但极具穿透力。 
 - 严禁废话，所有反馈必须指向销售核心胜任力。"""
system_prompt = "你是一个有20年经验的销售行业面试官，输入信息为面试者的回答，你需要对面试者进行提问并考察其逻辑能力、思维能力、表达能力等销售核心能力"
async def stream_text_to_llm(
        text_q:asyncio.Queue,
        system_prompt: str = system_prompt,
        context: List[Dict[str, str]] = None
) -> AsyncGenerator[str, None]:
    """
    监听text_q队列，并实现流式输出LLM处理
    """
    client = AsyncOpenAI(
        api_key=Conf.openai_apikey,
        base_url=Conf.openai_url,
    )
    if context is None:
        context = [{"role":"system","content":system_prompt}]
    
    while True:
        user_input = await text_q.get()
        
        try:
            if not user_input or not user_input.strip():
                continue    
            context.append({"role":"user","content":user_input})

            start_time = perf_counter()
            first_token_received = False
            full_reply_content = ""

            response = await client.chat.completions.create(
                model=Conf.openai_model,
                messages=context,
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )

            async for chunk in response:
                if not first_token_received:
                    delay = perf_counter() - start_time

                    first_token_received = True
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    content = delta.content
                    full_reply_content = content
                    
                    yield full_reply_content
            context.append({"role": "assistant", "content": full_reply_content})
        except Exception as e:
            yield f"Error:{str(e)}"
        finally:
            text_q.task_done()