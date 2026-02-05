from openai import AsyncOpenAI
from time import sleep, perf_counter
import asyncio
import random
import time
import pdb
from llm_analysis import llm_analysis
from knowledge_trigger import KnowledgeTrigger
from prompts import SEGMENT_JUDGE_PROMPT, Prompts
from utils.logger import logger
from state_manager import State

async def simulate_human_speech(
        lines,
        text_q: asyncio.Queue,
        min_interval=1,
        max_interval=10
):
    """
    simulate_human_speech 的 Docstring
    
    :param lines: 说话文本内容
    :param on_text: 说明
    :param min_interval: 模拟说话的最小间隔
    :param max_interval: 模拟说话的最大间隔
    """
    for line in lines:
        delay = random.uniform(min_interval, max_interval)
        await asyncio.sleep(delay)
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] 🎤 ASR definite: {line}")
        await text_q.put(line)


class Conf:
    openai_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    openai_apikey: str = "76a878dc-4905-44c3-858c-8ef33006250f"
    openai_model: str = "doubao-seed-1-6-251015"

class llm_SegmentJudge:

    def __init__(self,text_q: asyncio.Queue):
        self.messages = [
            {"role":"system","content": SEGMENT_JUDGE_PROMPT}
        ]
        self.client = AsyncOpenAI(
            api_key=Conf.openai_apikey,
            base_url=Conf.openai_url,
        )
        self.extra_body = {"thinking": {"type": "disabled"}}
        self.text_q = text_q
        self.llm_call_count = 0  # 记录LLM调用次数
    
    
    async def judge(self, recent_text: str) -> str:
        self.llm_call_count += 1
        ts = time.strftime("%H:%M:%S")
        logger.info(f"[{ts}] Seg LLM Call #{self.llm_call_count}")
        
        messages = [
            {"role": "system", "content": SEGMENT_JUDGE_PROMPT},
            {"role": "user", "content": recent_text}
        ]
        resp = await self.client.chat.completions.create(
            model=Conf.openai_model,
            messages=messages,
            extra_body=self.extra_body, #ollama没有
            max_tokens=20,
            stream=False,
            # temperature=0.0
        )
        return resp.choices[0].message.content.strip()

def build_segment_input(buffer_lines: list[str]):
    text = "\n".join(buffer_lines)
    return f"最近对话：\n{text}"


def emit_split(block_text: str, reason: str):
    print("\n" + "=" * 60)
    print(f"SPLIT ({reason}) ")
    print(block_text)
    print("=" * 60)

async def pipeline(text_q: asyncio.Queue, silence_time: float = 3.0, state=None):
    
    buffer = []
    last_judge_time = time.time()  # 初始化时间戳为当前时间
    last_end_time = None  # 上一个文本的结束时间
    min_batch_size = 5  # 最小批量处理行数，降低到3行，使得在真实对话中更容易触发
    judge_interval_min = 5.0  # 调用LLM的最小时间间隔（秒），降低到2秒
    judge_interval_max = 15.0  # 最大时间间隔降低到15秒
    continue_ignore_count = 0
    max_continue_ignore = 15


    segment_judge = llm_SegmentJudge(text_q)
    analysis = llm_analysis(memory_rounds=5, use_same_api=True, shared_client=segment_judge.client)
    knowledge_trigger = KnowledgeTrigger(shared_client=segment_judge.client)
    
    while True:
        try:
            # 检查是否有静默
            if state and state.is_silence:
                if buffer:
                    logger.info(f"检测到静默，分析buffer内容")
                    block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer])
                    buffer.clear()
                    result = await analysis.analyze(block_text, trigger_type="silence", knowledge_trigger=knowledge_trigger)
                    yield result
                    # 分析完成后重置静默状态
                    state.is_silence = False
            
            # 等待获取队列中的数据
            data = await asyncio.wait_for(text_q.get(), timeout=silence_time)
            
            # 提取文本内容
            if isinstance(data, dict):
                line = data.get("text", "")
                current_start_time = data.get("start_time")
                current_end_time = data.get("end_time")
            else:
                # 兼容旧格式（纯文本）
                line = data
                current_start_time = None
                current_end_time = None
            
            # 检查相邻文本的时间间隔
            if last_end_time and current_start_time:
                time_gap = current_start_time - last_end_time
                logger.info(f"start time {current_start_time} | end time {current_end_time} | Time gap between texts: {time_gap} ms")
                
                # 如果时间间隔超过silence_time，触发超时分析
                if time_gap > silence_time*1000:
                    if buffer:
                        logger.info(f"Time gap ({time_gap}ms) exceeds silence time ({silence_time}ms), triggering timeout analysis")
                        block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer])
                        buffer.clear()
                        result = await analysis.analyze(block_text, trigger_type="timeout", knowledge_trigger=knowledge_trigger)
                        yield result
            
            # 更新last_end_time
            if current_end_time:
                last_end_time = current_end_time
            
            # 将数据添加到缓冲区
            buffer.append(data)
            
            # 检查是否需要调用LLM
            current_time = time.time()
            time_elapsed = current_time - last_judge_time
            
            # 只有当满足以下条件时才调用LLM：
            # 1. 满足最小批量处理行数且满足最小时间间隔
            # 2. 或者超过最大时间间隔
            is_should_call_llm = (
                (len(buffer) >= min_batch_size and time_elapsed >= judge_interval_min)
                or
                (time_elapsed >= judge_interval_max)
            )

            if is_should_call_llm:
                # ===== 语义 SPLIT 判定 =====
                # 构建判定输入时，只使用文本内容
                text_buffer = [item.get("text", item) if isinstance(item, dict) else item for item in buffer]
                judge_input = build_segment_input(text_buffer)
                decision = await segment_judge.judge(judge_input)
                decision = decision.strip().upper()
                last_judge_time = current_time 

                if decision in {"IGNORE","CONTINUE"}:
                    continue_ignore_count += 1
                    
                    if continue_ignore_count >= max_continue_ignore:
                        # 构建分析文本时，只使用文本内容
                        block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer])
                        buffer.clear()
                        continue_ignore_count = 0

                        
                        logger.info(f"LONG CONTINUE FORCE ANALYZE: {block_text}")

                        result = await analysis.analyze(
                            block_text,
                            trigger_type="timeout",
                            knowledge_trigger=knowledge_trigger
                        )
                        yield result
                    continue

                if decision == "SPLIT":
                    # 构建分析文本时，只使用文本内容
                    block_text = "\n".join([item.get("text", item) if isinstance(item, dict) else item for item in buffer]) 
                    buffer.clear()   
                    continue_ignore_count = 0

                    logger.info(f"SPLIT SEG BLOCK: {block_text}")
                    
                    # ===== 分析 block =====
                    result = await analysis.analyze(block_text,trigger_type="semantic",knowledge_trigger=knowledge_trigger)
                    yield result
                    continue
                    
                    
                if decision not in {"CONTINUE", "SPLIT", "IGNORE"}:
                    decision = "CONTINUE"
        except Exception as e:
            pass
        

    

