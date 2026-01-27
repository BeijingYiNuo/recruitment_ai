from openai import AsyncOpenAI
from time import sleep, perf_counter
import asyncio
import random
import time

TEXT_LINES = [
    "再问您一个场景题，若您跟进了很久的大客户即将签单，竞争对手突然抛出更低报价，您会如何保留这个客户？",
    "就在这种情况下，我是不会盲目的跟风降价的。",
    "因为我认为就是低价的这种。",
    "情况容易让客户质疑产品价值，尤其是在。",
    "马上要签单的时候，这个价格这个随意变动。",
    "首先我会与客户复盘合作推进过程。",
    "重申我们产品的一个核心优势。",
    "包括这种我们专属的一个售后的对接快速响应机制等，这些就是在。",
    "竞争对手这边是相对较弱的一些点。",
    "那其次我也会主动的去了解客户对低价方案的一些这个顾虑。嗯，最后我会向公司去做一些申请。",
    "做一些这个增值服务，比如说免费的培训，延长售后的这种保质期这种方式。",
    "那这样的话就是可以。",
    "用一些附加的一些产品去让。",
    "用户觉得他没有亏，那这样的话就是。",
    "就是可以容易流出这个客户服务。",   #*****************llm划分***************
    "过往也有这种，就是成功的经历。",   #---------------人工划分----------------
    "那我们都知道老客户是作为销售的核心资源，那请问您平时任务怎么维护老客户关系的？",
    "我主要的一个思路是可以归纳为两个点，一个点是。",
    "围绕价值展开一个点，是围绕着这个情感展开，那首先一方面我是肯定要持续的和老客户维持这个联系。",
    "然后我向他推送一些像行业资讯产品新功能，解读这些有价值的内容。",
    "也避免说就是单纯的给他推送广告，让他觉得我在骚扰老客户。",
    "另一方面，逢年过节我会一对一的去发送祝福。",
    "然后也不会有一个自己的记录本去记录这个客户的个性化偏好。",
    "这样子就是在这个情感上能比较好的维系。",
    "你说，然后最后就是这个客户的有什么问题，我会尽量就是第一时间去做响应。",
    "然后这样的话就是除了能建立信任，然后促进老客户复购，还可以就是说获得一些这种，就是让老客户去帮我去推荐一些其他的人来一起使用这个产品，那我之前也有，我在做这个手机销售的时候也这样的，有一个老客户他给我推了额外的推了。",
    "好的，了解了，那么您认为一名优秀的销售应该具备哪些核心能力？您自身在这些能力上的适配度如何？",         #---------------人工划分----------------
    "我觉得。",
    "我觉得核心的能力主要是3点。",
    "首先是这个共情能力问题，这解决能力，还有就是这种目标导向的意识。",
    "首先共情能力是，主要是可以让我就是能够快速的理解这种客户的需求。",
    "然后问题解决能力可以有效的就是打消客户的这个顾虑，而这个目标导向意识则能够保证。",
    "我在沟通过程中我会。",
    "秉持的是这种换位思考的原则，就是我尽量站在客户的这个角度，包括他在这个成本效率角度。",
    "他的一些这个顾虑，然后再向他推荐产品。",
    "那也以前也有这种客户的一些反应，就是体现的说，就是我还是比较能够精准的把握他们这个需求的，这也是我个人认为我比较适合。",
    "贵公司咱们这个岗位的一个原因。",
    "那好的。",
    "销售岗位的业绩压力相对是较大的。",
    "那您在过去的工作中是怎么调节心态应对高压的？如果是您有这方面的案例，能否能举一个实例出来？",           #---------------人工划分----------------
    "就结合我过往的一些经历，我主要是，我主要还是给自己定了一套这个方法论，把这个一个是要把目标拆解开来，一个是要对过往的一些问题去做复盘。",
    "我之前，我，我之前在工作的过程中，我有一个月我那个业绩完成率只有50%，那我其实当时也是冷静下来思考了一下，我首先是拆解了目标，分析出我当时遇到一个核心问题，是这个在。",
    "就是新客户的这个渠道上面就可能有一些不足。",
    "所以我也对应的去调整一下这个获客的这个渠道，增加了一些这个像。",
    "行业社群运营精准话术触达这些这一些思路，同时我也向我们团队里面这些，就是当时是比较优秀的这个同事请教了一些技巧，从而在这个月的月底完成了这个。",
    "业绩目标。",
    "那日常的我也会有一些自己的这种娱乐活动，包括就是以运动为主，然后在调节我自己的这个状态，确保以积极心态投入工作。",
    "你对刚才的这个问题中提到了说像团队优秀同事请教博客技巧。",
    "那团队协作在销售工作中也非常重要。",
    "我来举一个这个场景，比如说您的同事和您的客户产生了这个，与您产生了这个客户归属问题，您会怎么处理？这个我主要还是。",       #---------------人工划分----------------
    "用这个证据说话，那就是因为我会。",
    "持续的去梳理这个自己跟客户的这个跟进记录，那确保说。",
    "就是我在有争执的时候，我能拿出来这个证据告诉。",
    "对方说就是这个客户，比如说是一直我在跟进的。",
    "那同时就是我也会。",
    "尽量的在跟同事的交流中，就是用这些私下的这种。",
    "打，敢打一下，敢情牌。",
    "通过沟通的方式。",
    "把这个问题尽可能去解决，好吧？那如果说实在是解决不了的话，我就会把我这些证据，把这些记录就是客观的这个拿出来，然后让。",
    "上面的这些领导。",
    "把这些去决定一下，来解决这个问题。",                   #*****************llm划分***************
    "因为虽然说这个跟同事关系比较重要，但是也。",            
    "但是确实是这个。",
    "这个权益也是需要，就是要讲理的，维护一下是要好的，你在简历中提到。",                                               #---------------人工划分----------------
    "这个 SPIN 法则是挖掘客户需求的重要工具。那您在实际销售过程中是否应用？具体如何通过这一法则探寻客户的显性与隐性需求？",     
    "这个 spin 法则也是我就是经常使用的一套这个方法论，那首先是我要通过这个现状去提问的方式来了解基础情况。",
    "就是要先先向客户问问题，比如说问他。",
    "比如说在目前的这个。",
    "这个工作过程中主要是对接了哪些这个？",
    "这些需求。",
    "然后现有的这些几种工具和方法，这个使用的频率如何？然后我再会。",
    "通过这个问题提问的方式去问他，就比如说我会主要是问他说对方目前遇到了什么问题，我尤其或者说就是目前对他带来最大烦恼的问题是什么？", 
    "然后那接下来就是这个影响提问，就是我会通过影响提问的方式来放大这个痛点。",
    "比如说就是问他说那这个问题目前有没有对你造成？",
    "严重的后果造成了什么样的这个严重后果？",
    "那最后就是用这种。",
    "一个需求回报提问来给出这个价值预期，比如说如果问，他说如果有一个解决方案可以帮您去改进。",
    "这个改进这个现状，那您对这个工具的能达到的成效有没有什么这个期望？",
    "通过这种方式就是我可以比较明确的把握这个客户的一个完整的需求，也更方便的去我对后面去做推销产品的一些这个方法去做一些优化和改进。",
    "好的，好的，您的这个基本情况我了解了。",
    "那最后这个问题想问您对销售岗位的长期职业规划是什么？",     #*****************llm划分***************        #---------------人工划分----------------
    "你为什么会选择我们行业和公司？",
    "我主要是。",
    "我的这个考虑主要是我觉得就是销售职业这个岗位，它因为我们都知道它和这个薪资是。",
    "挂钩还是比较明显的。",
    "那我个人对我自己的这个。",
    "个人能力还是比较有。",
    "有自信的，我觉得我在这个岗位上做，我能够较好地发挥出这个上限，也避免说就是。",
    "就是纯拿这个死工资，同时我也觉得。",
    "销售岗位就它的这个。",
    "他的这个主观能动性比较强，也比较适合像我这种就是比较外向，如果性格比较外向，我比较适合我，我就是在这个领域去发挥我的一些优势。",
    "那对于咱公司的这个岗位，我也有一些，我在事前也调研过。",
    "有什么是一个业务？因为代理记账这块它确实是一个，我认为是在国家领域上它就是一个非常好的一个再到和趋势，因为国家现在鼓励这个中小企业创业。",
    "创业，那这些中小企业它针对于这种人力带来的这个记账成本。",
    "就是非常显着的那我通过这种。",
    "咱们公司代理记账，这个相对比较在行业内比较有优势的，这个产品能够非常好的解决他们这个需求，同时也响应了趋势，所以无论从解决的这个小问题和解决的这个大问题上。",
    "我都认为咱们公司非常有前景，也非常希望得到这个工作。",
    "好的好的，可以了，最后。",                             #*****************llm划分***************        #---------------人工划分----------------
    "那个您有什么问题想问吗？",
    "就是我想了解一下，就是咱们公司的这个具体的这个业务，我。",
    "我这个具体这个工作形式到底是什么样的？",
    "是本公司是。",
    "记账机构。",
    "那核心是为中小微企业提供全生命周期的财税服务，那咱们的业务是涵盖了代理记账、工商注册、税务筹划、资质代办等一站式。",
    "白税配套服务。",
    "那现在我们拥有30多的这个。",
    "我搭配了智能财税系统，提供了定制化的合规方案。",
    "目前我们也在和这个。",
    "服务了将近800家的跨行业企业。",
    "客户年留存率也在85%以上，本地市场的口碑也非常的良好。",
    "我觉得我们的这个公司整体团队氛围还是非常不错的。",
    "这个岗位上的这个竞争压力，包括同事之间的这种。",
    "如果您愿意这个。",
    "好的好的，了解了，我觉得确实是团队氛围也是比较我觉得很重要的一点，我这边目前没有什么别的问题了。好的，面试就结束。",
    "好嘞好嘞，感谢感谢。",                                 #*****************llm划分***************        #---------------人工划分----------------
]

SEGMENT_JUDGE_PROMPT = """
你是一个【对话切分判定器】。

输入是面试对话的 ASR 连续文本（逐行）。
请你判断：当前是否已经形成了一个【完整的问题-回答单元】。

说明：
- 一个问题大概率由面试官提出，小概率由面试者提出
- 回答可能由面试者连续多行组成
- 回答结束后，若语义完整，即认为一个单元完成
- 对于问句需要重点关注，问句的上文很有可能为一段【问题-回答单元】的分界点

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
        print(f"[{ts}] Seg LLM Call #{self.llm_call_count}")
        
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
    print(f"SPLIT ({reason})")
    print("\n".join(buffer))
    print("=" * 60)

async def pipeline(text_q: asyncio.Queue, silence_time: float = 5):
    buffer = []
    segment_judge = llm_SegmentJudge(text_q)
    last_judge_time = time.time()  # 初始化时间戳为当前时间
    min_batch_size = 10  # 最小批量处理行数，增加到10行
    judge_interval = 3.0  # 调用LLM的最小时间间隔（秒），增加到3秒
    
    analysis = llm_analysis(memory_rounds=5, use_same_api=True, shared_client=segment_judge.client)
    
    while True:
        try:
            line = await asyncio.wait_for(text_q.get(), timeout=silence_time)
            buffer.append(line)
            
            # 检查是否需要调用LLM
            current_time = time.time()
            time_elapsed = current_time - last_judge_time
            
            # 只有当满足以下条件时才调用LLM：
            # 1. 累积了足够的行数
            # 2. 距离上次调用已经超过了一定时间
            if len(buffer) >= min_batch_size and time_elapsed >= judge_interval:
                # ===== 语义 SPLIT 判定 =====
                judge_input = build_segment_input(buffer)
                decision = await segment_judge.judge(judge_input)
                decision = decision.strip().upper()
                last_judge_time = current_time  # 调用后更新时间戳
                
                if decision == "IGNORE":
                    continue
                if decision == "CONTINUE":
                    continue
                if decision == "SPLIT":
                    block_text = "\n".join(buffer)
                    emit_split(buffer, reason="semantic")
                    
                    # ===== 分析 block =====
                    result = await analysis.analyze(block_text)
                    print(f"给前端的：{result}")
                    yield result
                    # print("*"*60)
                    # print(f"\n分析结果：")
                    # print(f"追问问题建议：")
                    # for i, q in enumerate(result['follow_up_questions'], 1):
                    #     print(f"  {i}. {q}")
                    # print(f"\n面试者评价：{result['evaluation']}\n")
                    # print("*"*60)
                    
                    buffer.clear()
                if decision not in {"CONTINUE", "SPLIT", "IGNORE"}:
                    decision = "CONTINUE"
        except asyncio.TimeoutError:
            # ===== 时间 SPLIT 判定 =====
            if buffer:
                block_text = "\n".join(buffer)
                # emit_split(buffer=buffer, reason="silence")
                
                # ===== 分析 block =====
                result = await analysis.analyze(block_text)
                yield result
                # print("*"*60)
                # print(f"\n 分析结果：")
                # print(f"追问问题建议：")
                # for i, q in enumerate(result['follow_up_questions'], 1):
                #     print(f"  {i}. {q}")
                # print(f"\n面试者评价：{result['evaluation']}\n")
                # print("*"*60)
                
                buffer.clear()

ANALYSIS_PROMPT = """
你是一个专业的【面试分析助手】。

输入是面试对话的一个完整问答单元（block），你需要分析面试者的回答过程，重点评判以下三个方面：
1. 逻辑能力：回答是否有条理、逻辑是否清晰、论证是否充分
2. 表达能力：语言表达是否流畅、用词是否准确、重点是否突出
3. 内生动力：是否展现出积极主动的态度、学习意愿和职业热情

你的输出必须严格按照以下格式（仅输出这两部分，不要输出任何其他内容）：

【追问问题建议】
1. 问题一
2. 问题二

【面试者评价】
评价内容（300字以内）

要求：
- 追问问题建议：1-2个问题，针对回答中的不足或需要深入了解的点
- 面试者评价：简洁明了，300字以内，包括但不限于逻辑、表达、动力三个方面
- 不要输出任何解释或额外内容
"""

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
    
    def add_knowledge(self, key: str, value: str):
        """
        添加外部知识库信息
        
        Args:
            key: 知识点的键（如"岗位空缺数量"）
            value: 知识点的值
        """
        self.knowledge_base[key] = value
    
    def search_knowledge(self, query: str) -> dict:
        """
        搜索外部知识库
        
        Args:
            query: 查询关键词
            
        Returns:
            匹配的知识点字典
        """
        results = {}
        for key, value in self.knowledge_base.items():
            if query.lower() in key.lower() or query.lower() in value.lower():
                results[key] = value
        return results
    
    def _update_memory(self, block: str):
        """
        更新记忆管理
        
        Args:
            block: 当前的问答单元
        """
        self.short_term_memory.append(block)
        self.conversation_rounds += 1
        
        if len(self.short_term_memory) > self.memory_rounds:
            oldest_block = self.short_term_memory.pop(0)
            if self.long_term_summary:
                self.long_term_summary += f"\n{oldest_block}"
            else:
                self.long_term_summary = oldest_block
    
    async def analyze(self, block: str, external_client: AsyncOpenAI = None) -> dict:
        """
        分析面试者的回答
        
        Args:
            block: 面试对话的一个完整问答单元
            external_client: 外部提供的API客户端（如果共用API）
            
        Returns:
            包含追问问题和评价的字典
        """
        self.llm_call_count += 1
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] Analysis Call #{self.llm_call_count}")
        
        self._update_memory(block)
        
        client = external_client if external_client else self.client
        
        messages = [
            {"role": "system", "content": ANALYSIS_PROMPT},
            {"role": "user", "content": f"面试对话单元：\n{block}"}
        ]
        
        resp = await client.chat.completions.create(
            model=Conf.openai_model,
            messages=messages,
            extra_body=self.extra_body,
            max_tokens=500,
            stream=False,
        )
        
        result = resp.choices[0].message.content.strip()
        
        return self._parse_result(result, block)
    
    def _parse_result(self, result: str, block: str) -> dict:
        """
        解析LLM返回的结果
        
        Args:
            result: LLM返回的原始结果
            block: 面试对话的一个完整问答单元
            
        Returns:
            包含追问问题和评价的字典
        """
        follow_up_questions = []
        evaluation = ""
        
        lines = result.split('\n')
        current_section = None
        
        for line in lines:
            line = line.strip()
            if line.startswith('【追问问题建议】'):
                current_section = 'questions'
            elif line.startswith('【面试者评价】'):
                current_section = 'evaluation'
            elif current_section == 'questions' and line:
                if line.startswith(('1.', '2.', '3.', '4.', '5.')):
                    follow_up_questions.append(line[2:].strip())
            elif current_section == 'evaluation':
                evaluation = line
                break
        
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
        



async def main():
    text_q = asyncio.Queue()
    
    # 启动模拟人类说话的任务
    speech_task = asyncio.create_task(simulate_human_speech(TEXT_LINES, text_q=text_q))
    
    # 处理pipeline生成的结果
    async for result in pipeline(text_q=text_q):
        print("*"*60)
        print(f"\n分析结果：")
        print(f"追问问题建议：")
        for i, q in enumerate(result['follow_up_questions'], 1):
            print(f"  {i}. {q}")
        print(f"\n面试者评价：{result['evaluation']}\n")
        print("*"*60)
    
    # 等待说话任务完成
    await speech_task

if __name__ == "__main__":
    asyncio.run(main())

    

