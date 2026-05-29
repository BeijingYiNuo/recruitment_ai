"""
面试对话上下文管理器
- ShortTermMemory: 短期记忆，保留最近 N 轮对话轮次
- LongTermMemory: 长期记忆，对 evict 的旧轮次进行增量压缩摘要
- SpeakerDetector: 基于规则的说话人识别
- ContextManager: 统一入口，管理 STM + LTM + 消息组装
"""

import asyncio
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConversationTurn:
    """一次对话轮次"""
    text: str
    speaker: str           # "interviewer" / "candidate" / "unknown"
    index: int             # 全局递增序号
    detected_stage: Optional[str] = None
    prev_advice: Optional[str] = None
    prev_evaluation: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


# ──────────────────────────────────────────────
# 说话人识别（规则启发式）
# ──────────────────────────────────────────────

class SpeakerDetector:
    """基于规则的说话人识别，零依赖"""

    # 面试官典型句式
    _INTERVIEWER_PATTERNS = [
        re.compile(r"^[好嗯行可以][，。！？]?$"),
        re.compile(r"^(请[问你]?|你|能[否不能]?|可以|那[么]?|这样[吧]?|要不)"),
        re.compile(r"^(谢谢|感谢|没问题|收到|好的)"),
        re.compile(r"[？?]$"),
        re.compile(r"(请你|能[不能]?|给[我你]|介绍下|说说|谈谈|讲讲|聊聊|问[一下]?|想问|我想问)"),
        re.compile(r"^(那[你么]|那你觉得|你认为|你觉得|你怎么看|你怎么理解)"),
        re.compile(r"^(这个|那个|咱们|我们|这样)"),
        re.compile(r"^(要不[然]?|或者|另外)"),
    ]

    # 候选人典型句式
    _CANDIDATE_PATTERNS = [
        re.compile(r"^我(之前|在|做|负责|参与|认为|觉得|想[要到]?|是|毕业于|来自|有\d|的)"),
        re.compile(r"^(我的[项目工作职责经历]|我主要负责|我参与[了过]|我在[之前原先])"),
        re.compile(r"^(其实|我觉得|我认为|在我看来|我个人|对我来说)"),
        re.compile(r"^(我们[组队团队项目]|我们这个|当时我们)"),
    ]

    _CANDIDATE_KEYWORDS = [
        "负责", "参与", "项目", "开发", "设计", "实现",
        "架构", "方案", "技术栈", "框架", "数据库", "系统",
        "优化", "重构", "提升了", "降低了", "实现了",
        "毕业", "工作", "经历", "经验",
    ]

    @classmethod
    def detect(cls, text: str) -> str:
        """返回 interview / candidate / unknown"""
        if not text or not text.strip():
            return "unknown"

        # 面试官模式
        for pat in cls._INTERVIEWER_PATTERNS:
            if pat.search(text):
                return "interviewer"

        # 候选人模式
        for pat in cls._CANDIDATE_PATTERNS:
            if pat.search(text):
                return "candidate"

        # 候选关键词（较长文本更可能是候选人在回答）
        if len(text) > 15:
            for kw in cls._CANDIDATE_KEYWORDS:
                if kw in text:
                    return "candidate"

        return "unknown"


# ──────────────────────────────────────────────
# 短期记忆
# ──────────────────────────────────────────────

class ShortTermMemory:
    """短期记忆，固定大小环形缓冲区"""

    def __init__(self, maxlen: int = 12):
        self.buffer: deque[ConversationTurn] = deque(maxlen=maxlen)
        self._maxlen = maxlen

    def push(self, turn: ConversationTurn) -> Optional[ConversationTurn]:
        """
        推入一个轮次。如果缓冲区已满返回被 evict 的旧轮次，否则返回 None。
        """
        evicted = None
        if len(self.buffer) >= self._maxlen:
            evicted = self.buffer[0]  # maxlen deque 会自动 pop 最老的
            # 但 deque 不给我们返回值，我们手动拿一下
        self.buffer.append(turn)
        # 再次检查：如果超过 maxlen，新 append 导致旧项被丢弃
        # 但我们拿不到那个被丢弃的项。改用判断 buffer 长度变化的方式。
        # 其实 deque(maxlen=N) 当 len==N 时 append 新项会丢弃最左的一项。
        # 上面 evicted 拿到的可能是 append 前的 buffer[0]，
        # 但如果之前 len<maxlen，则 evicted=None 是正确的。
        if evicted is not None and len(self.buffer) == self._maxlen:
            return evicted
        # 另一种情况：append 之后 buffer 长度反而没变（满的），
        # 说明 buffer[0] 被丢弃了，但 evicted 在上面就已经拿到了 buffer[0]
        # 唯一问题：如果 buffer 满时 evicted 取了 buffer[0]，而 append 后 buffer[0] 变成了以前 buffer[1]，
        # evicted 正好就是要丢弃的项，正确。
        return evicted

    def get_recent(self, n: int) -> list[ConversationTurn]:
        return list(self.buffer)[-n:]

    def get_all(self) -> list[ConversationTurn]:
        return list(self.buffer)

    def update_last(self, *, advice: str = None, evaluation: str = None, stage: str = None):
        if self.buffer:
            last = self.buffer[-1]
            if advice is not None:
                last.prev_advice = advice
            if evaluation is not None:
                last.prev_evaluation = evaluation
            if stage is not None:
                last.detected_stage = stage


# ──────────────────────────────────────────────
# 长期记忆（增量压缩）
# ──────────────────────────────────────────────

class LongTermMemory:
    """长期记忆，对 evicted 旧轮次做增量摘要压缩"""

    def __init__(self, max_tokens: int = 500):
        self.summary: str = ""
        self._max_tokens = max_tokens
        self._compressed_count: int = 0

    async def incremental_summarize(self, turns: list[ConversationTurn], llm_client) -> None:
        """将一批被 evict 的轮次增量压缩进摘要"""
        if not turns or not llm_client:
            return

        evicted_text = "\n".join(
            f"[{t.speaker}] {t.text}" for t in turns
        )

        summary_prompt = _build_summary_prompt(self._max_tokens)

        messages = [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": (
                f"已有的摘要：\n{self.summary}\n\n"
                f"新的对话内容：\n{evicted_text}"
            )},
        ]

        try:
            response = await llm_client.chat.completions.create(
                messages=messages,
                model=llm_client.model if hasattr(llm_client, 'model') else None,
                max_tokens=self._max_tokens,
                temperature=0.3,
                stream=False,
            )
            new_summary = response.choices[0].message.content.strip()
            if new_summary:
                self.summary = new_summary
            self._compressed_count += len(turns)
        except Exception:
            pass  # 压缩失败不影响主流程


def _build_summary_prompt(max_tokens: int) -> str:
    return (
        "你是一个面试对话【摘要生成器】。请将输入的新的对话内容合并到已有的摘要中。\n\n"
        "要求：\n"
        "1. 保留关键信息：候选人技术栈、项目经验、能力评估、面试官关注点、阶段变化\n"
        "2. 删除冗余细节、语气词、重复内容\n"
        f"3. 输出的新摘要控制在 {max_tokens} tokens 以内\n"
        "4. 保持时间线顺序，重要信息优先保留\n\n"
        "新摘要："
    )


# ──────────────────────────────────────────────
# 统一上下文管理器
# ──────────────────────────────────────────────

class ContextManager:
    """
    面试上下文管理器

    职责：
    1. 管理短期记忆（STM）+ 长期记忆（LTM）
    2. 说话人识别
    3. 组装 Reply Agent / Flow Agent 的 messages

    使用方式：
        ctx = ContextManager()
        ctx.set_llm_client(llm_manager.llm_client)   # 用于 LTM 压缩

        # 每次收到 block：
        messages = ctx.build_reply_messages(system_prompt, block_text, index)
        result = await analyze_reply(..., messages=messages)
        ctx.push_turn(block_text, index)
        ctx.update_last_advice(advice=result["advice"], evaluation=result["evaluation"])
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.stm = ShortTermMemory(maxlen=cfg.get("stm_maxlen", 12))
        self.ltm = LongTermMemory(max_tokens=cfg.get("ltm_max_tokens", 500))
        self.speaker_detector = SpeakerDetector()
        self.llm_client = None
        self._summarize_sem = asyncio.Semaphore(1)
        self._pending_summarize: list[ConversationTurn] = []

    def set_llm_client(self, client) -> None:
        self.llm_client = client

    def push_turn(self, text: str, index: int, speaker: str = None) -> None:
        """
        将当前 block 作为一次对话轮次推入 STM。
        如果触发 eviction 则异步启动 LTM 增量压缩。

        Args:
            speaker: ASR 返回的说话人标识，为空时由 SpeakerDetector 自动识别
        """
        if not speaker:
            speaker = self.speaker_detector.detect(text)
        turn = ConversationTurn(text=text, speaker=speaker, index=index)

        evicted = self.stm.push(turn)
        if evicted is not None:
            self._pending_summarize.append(evicted)
            asyncio.create_task(self._trigger_summarize())

    def update_last_advice(self, *, advice: str = None, evaluation: str = None) -> None:
        """更新 STM 最近一个轮次的建议/评价"""
        self.stm.update_last(advice=advice, evaluation=evaluation)

    # ─── 消息组装 ────────────────────────────

    def build_reply_messages(self, system_prompt: str, current_block: str,
                             index: int) -> list[dict]:
        """
        构建 Reply Agent 的 messages。
        结构：system → [LTM摘要] → STM历史轮次(纯文本，不含prev分析) → 当前block

        Args:
            system_prompt: 系统提示词
            current_block: 当前要分析的文本块
            index: 当前块序号
        """
        speaker = self.speaker_detector.detect(current_block)
        messages = [{"role": "system", "content": system_prompt}]

        # 长期记忆（压缩摘要）
        if self.ltm.summary:
            messages.append({
                "role": "system",
                "content": f"[对话历史摘要]\n{self.ltm.summary}",
            })

        # 短期记忆（仅保留对话文本，不包含上次 LLM 的追问建议和评价）
        for turn in self.stm.get_all():
            messages.append({
                "role": "user",
                "content": f"[{turn.speaker}] {turn.text}"
            })

        # 当前 block
        messages.append({
            "role": "user",
            "content": f"[{speaker}] {current_block}",
        })

        return messages

    def build_flow_messages(self, system_prompt: str, current_block: str) -> list[dict]:
        """
        构建 Flow Agent 的 messages（更轻量，只取最近 6 条 + 当前）
        """
        speaker = self.speaker_detector.detect(current_block)
        messages = [{"role": "system", "content": system_prompt}]

        # 只取最近 6 条
        for turn in self.stm.get_recent(6):
            messages.append({
                "role": "user",
                "content": f"[{turn.speaker}] {turn.text}",
            })

        messages.append({
            "role": "user",
            "content": f"[{speaker}] {current_block}",
        })

        return messages

    # ─── 内部 ────────────────────────────────

    async def _trigger_summarize(self) -> None:
        """异步触发 LTM 增量压缩（带信号量限制并发）"""
        async with self._summarize_sem:
            if not self._pending_summarize or not self.llm_client:
                return
            pending = list(self._pending_summarize)
            self._pending_summarize.clear()

        await self.ltm.incremental_summarize(pending, self.llm_client)

    def get_state_summary(self) -> dict:
        """当前上下文状态（日志/监控用）"""
        return {
            "stm_len": len(self.stm.buffer),
            "ltm_exists": bool(self.ltm.summary),
            "ltm_compressed": self.ltm._compressed_count,
            "ltm_summary_preview": self.ltm.summary[:100] if self.ltm.summary else "",
        }
