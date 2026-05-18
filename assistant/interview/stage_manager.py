"""
面试阶段管理器
负责定义面试流程阶段、跟踪进度、决定阶段切换
"""

import enum
from typing import List, Dict, Optional, Set


class InterviewStage(str, enum.Enum):
    """面试阶段枚举"""
    WELCOME = "welcome"
    SELF_INTRODUCTION = "self_intro"
    PROJECT_DEEP_DIVE = "project"
    TECHNICAL_THEORY = "theory"
    CULTURE_FIT = "culture"
    CANDIDATE_QA = "candidate_qa"
    CLOSING = "closing"


INTERVIEW_FLOW = {
    InterviewStage.WELCOME: {
        "display_name": "开场介绍",
        "description": "面试官介绍面试流程与规则，营造轻松氛围",
        "min_exchanges": 1,
        "max_exchanges": 3,
        "next": InterviewStage.SELF_INTRODUCTION,
    },
    InterviewStage.SELF_INTRODUCTION: {
        "display_name": "自我介绍",
        "description": "候选人自我介绍，了解教育背景、工作经历、职业目标",
        "min_exchanges": 2,
        "max_exchanges": 5,
        "next": InterviewStage.PROJECT_DEEP_DIVE,
    },
    InterviewStage.PROJECT_DEEP_DIVE: {
        "display_name": "项目深挖",
        "description": "深入追问候选人核心项目经历：技术选型、难点攻克、个人贡献、量化成果",
        "min_exchanges": 3,
        "max_exchanges": 8,
        "next": InterviewStage.TECHNICAL_THEORY,
    },
    InterviewStage.TECHNICAL_THEORY: {
        "display_name": "技术理论",
        "description": "考察岗位相关的技术基础、原理理解、最佳实践",
        "min_exchanges": 3,
        "max_exchanges": 8,
        "next": InterviewStage.CULTURE_FIT,
    },
    InterviewStage.CULTURE_FIT: {
        "display_name": "文化匹配",
        "description": "了解候选人的团队协作风格、抗压能力、职业规划与公司文化匹配度",
        "min_exchanges": 2,
        "max_exchanges": 5,
        "next": InterviewStage.CANDIDATE_QA,
    },
    InterviewStage.CANDIDATE_QA: {
        "display_name": "候选人提问",
        "description": "给予候选人提问机会，回答关于岗位、团队、发展的问题",
        "min_exchanges": 1,
        "max_exchanges": 4,
        "next": InterviewStage.CLOSING,
    },
    InterviewStage.CLOSING: {
        "display_name": "结束总结",
        "description": "总结面试，告知后续流程，友好结束",
        "min_exchanges": 1,
        "max_exchanges": 3,
        "next": None,
    },
}


class StageManager:
    """
    面试阶段管理器

    职责：
    1. 跟踪当前面试阶段
    2. 记录每阶段的问答轮次和已覆盖关键点
    3. 根据规则决定阶段切换
    4. 生成阶段上下文供 LLM Prompt 使用
    """

    def __init__(self):
        self.stages: List[InterviewStage] = list(INTERVIEW_FLOW.keys())
        self.current_index: int = 0
        self.exchange_count: int = 0  # 当前阶段问答轮次
        self.stage_history: List[Dict] = []  # 已完成的阶段记录

    @property
    def current_stage(self) -> InterviewStage:
        return self.stages[self.current_index]

    @property
    def config(self) -> Dict:
        return INTERVIEW_FLOW[self.current_stage]

    @property
    def is_last_stage(self) -> bool:
        return self.current_index >= len(self.stages) - 1

    def build_prompt_context(self) -> str:
        """构建阶段上下文，注入 LLM Prompt"""
        lines = []
        lines.append("【面试流程】")
        for i, stage in enumerate(self.stages):
            cfg = INTERVIEW_FLOW[stage]
            if i < self.current_index:
                lines.append(f"  {'✓' if self._stage_was_completed(stage) else ' '} {i+1}. {cfg['display_name']} ✅ 已完成")
            elif i == self.current_index:
                lines.append(f"  → {i+1}. {cfg['display_name']} ◀ 当前阶段")
            else:
                lines.append(f"     {i+1}. {cfg['display_name']}")

        lines.append("")
        lines.append(f"当前阶段：{self.config['display_name']}（第{self.current_index + 1}/{len(self.stages)}阶段）")
        lines.append(f"阶段目标：{self.config['description']}")
        lines.append(f"本阶段已问答轮次：{self.exchange_count}")

        if self.stage_history:
            summary = " → ".join(
                INTERVIEW_FLOW[s["stage"]]["display_name"]
                for s in self.stage_history
            )
            lines.append(f"已完成阶段：{summary}")

        # 如果是最后一个阶段，提醒 LLM 准备结束
        if self.is_last_stage:
            lines.append("⚠️ 这是最后一个阶段，请引导面试自然结束，输出总结性评价")

        return "\n".join(lines)

    def _stage_was_completed(self, stage: InterviewStage) -> bool:
        return any(h["stage"] == stage for h in self.stage_history)

    def record_exchange(self) -> None:
        """记录一次问答（一个 block 处理完毕）"""
        self.exchange_count += 1

    def should_transition(self) -> bool:
        """判断是否应切换到下一阶段"""
        cfg = self.config

        # 强制切分：超过最大轮次
        if self.exchange_count >= cfg["max_exchanges"]:
            return True

        # 最少轮次未到，不切换
        if self.exchange_count < cfg["min_exchanges"]:
            return False

        # 最后一个阶段不需要额外条件
        if self.is_last_stage:
            return False

        return True

    def transition_to_next(self) -> Optional[Dict]:
        """
        切换到下一阶段
        Returns: 阶段切换信息 dict，如果已经是最后阶段则返回 None
        """
        # 存档当前阶段
        self.stage_history.append({
            "stage": self.current_stage,
            "display_name": self.config["display_name"],
            "exchanges": self.exchange_count,
        })

        if self.is_last_stage:
            return None

        self.current_index += 1
        self.exchange_count = 0
        return {
            "current_stage": self.current_stage.value,
            "display_name": self.config["display_name"],
            "stage_index": self.current_index,
            "total_stages": len(self.stages),
            "description": self.config["description"],
        }
