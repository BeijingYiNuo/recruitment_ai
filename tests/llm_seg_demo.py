from openai import AsyncOpenAI
from time import sleep, perf_counter
import asyncio
import random
import time

TEXT_LINES = [
    "那我们接下来会从一些问题逐步的展开交流。",#第一个问题开始
    "那首先想向您请教。",
    "明确抵触产品介绍的情况。",
    "当时您是如何处理的？",
    "我确实是遇到过这种情况，我当时没有急于推进产品的介绍。",
    "我是先诚恳的道歉，来，就是我，我当时想的是就是缓解一下这客户的这个抵触情绪。",
    "然后我也就是主动询问了一下，就是他的这种。",
    "就是发生抵触的这个原因。",
    "比如说就是鹦鹉主要是考虑它可能是。",
    "因为就是曾经使用过同类的这个产品，然后它因为体验不佳，所以留下了一些这个坏印象。",
    "明确原因以后，我针对性地梳理了，就是我们当时产品的一个相对的其他产品竞品的一个优势。",
    "然后我也把我们的这个详细的资料。",
    "发给客户参考。",
    "那最后通过这种方式就是。",
    "使这个客户最后愿意和我们合作了。",    #第一个问题回复结束
    "再问您一个场景题。",                #第二个问题开始
    "若您跟进了很久的大客户即将签单，竞争对手突然抛出更低报价，您会如何保持这个客户？",
    "就在这种情况下，我是不会盲目的跟风降价的。",
    "因为我认为就是低价的这种。",
    "情况容易让客户质疑产品价值，尤其是在。",
    "随意变动。",
    "首先我会与客户复盘合作推进过程。",
    "重申我们产品的一个核心优势。",
    "包括这种。",
    "我们专属的一个售后的对接快速响应机制的这些就是在。",
    "那其次我也会主动的去了解客户对低价方案的一些顾虑。",
    "最后我会向公司去做一些申请。",
    "做一些这个增值服务，比如说免费的培训，延长售后的这种保质期这种方式。",
    "那这样的话就是可以。",
    "用一些附加的一些产品去让。",
    "用户觉得他没有亏，那这样的话就是。",
    "就是可以容易流出这个客户，我。",
    "过往也有这种，就是成功的经历。",
    "好的，非常好。",                   #第二个问题结束
    "那我们都知道老客户是作为销售的核心资源，那请问您平时是怎么维护老客户关系的？",     #第三个问题开始
    "我主要的一个思路是可以归纳为两个点，一个点是。",
    "围绕价值展开一个点，是围绕着这个情感展开，那首先一方面我是肯定要持续的和老客户维持这个联系的。",
    "推送一些像行业资讯产品新功能，解读这些。",
    "有价值的内容。",                                                       #第三个问题异常中断
]

SEGMENT_JUDGE_PROMPT = """
你是一个【对话切分判定器】。

输入是面试对话的 ASR 连续文本（逐行）。
请你判断：当前是否已经形成了一个【完整的问题-回答单元】。

说明：
- 一个问题由面试官提出
- 回答可能由面试者连续多行组成
- 回答结束后，若语义完整，即认为一个单元完成

你的输出只能是以下三种之一（严格）：
CONTINUE  —— 还在当前问题或回答中
SPLIT     —— 一个完整【问题-回答】已经完成
IGNORE    —— 当前输入是语气词/填充/不影响结构

不要输出任何解释。
"""

async def simulate_human_speech(
        lines,
        text_q: asyncio.Queue,
        min_interval=0.5,
        max_interval=1.5
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
    #local llm
    # openai_url: str = "http://localhost:11434/v1/"
    # openai_apikey: str = "ollama"   # 随便写，占位
    # openai_model: str = "deepseek-r1:1.5b"

class SegmentJudge:

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
    
    
    async def judge(self, recent_text: str) -> str:
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


def emit_split(buffer: list, reason: str):
    print("\n" + "=" * 60)
    print(f"📌 SPLIT ({reason})")
    print("\n".join(buffer))
    print("=" * 60)

async def pipeline(text_q: asyncio.Queue, silence_time: float = 5):
    buffer = []
    segment_judge = SegmentJudge(text_q)
    while True:
        try:
            line = await asyncio.wait_for(text_q.get(), timeout=silence_time)
            buffer.append(line)
            
            # ===== 语义 SPLIT 判定 =====
            judge_input = build_segment_input(buffer)
            decision = await segment_judge.judge(judge_input)
            decision = decision.strip().upper()
            if decision == "IGNORE":
                continue
            if decision == "CONTINUE":
                continue
            if decision == "SPLIT":
                emit_split(buffer,reason="semantic")
                buffer.clear()
            if decision not in {"CONTINUE", "SPLIT", "IGNORE"}:
                decision = "CONTINUE"
        except asyncio.TimeoutError:
            # ===== 时间 SPLIT 判定 =====
            if buffer:
                emit_split(buffer=buffer, reason="silence")
                buffer.clear()

async def main():
    text_q = asyncio.Queue()
    await asyncio.gather(
        simulate_human_speech(TEXT_LINES, text_q=text_q),
        pipeline(text_q=text_q)
    )

if __name__ == "__main__":
    asyncio.run(main())

    

