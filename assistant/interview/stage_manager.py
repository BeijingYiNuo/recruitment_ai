"""
面试阶段管理器
负责定义面试阶段、跟踪当前阶段、生成阶段上下文
采用动态分类模型，不强制顺序推进
"""

import enum
from typing import Dict, Optional

from assistant.utils.logger import logger


class InterviewStage(str, enum.Enum):
    """面试阶段枚举"""
    WELCOME = "welcome"
    SELF_INTRODUCTION = "self_intro"
    PROJECT_DEEP_DIVE = "project"
    TECHNICAL_THEORY = "theory"
    CULTURE_FIT = "culture"
    CANDIDATE_QA = "candidate_qa"
    CLOSING = "closing"


STAGE_DEFINITIONS = {
    InterviewStage.WELCOME: {
        "display_name": "开场介绍",
        "description": "面试官介绍面试流程与规则，营造轻松氛围",
    },
    InterviewStage.SELF_INTRODUCTION: {
        "display_name": "自我介绍",
        "description": "候选人自我介绍，了解教育背景、工作经历、职业目标",
    },
    InterviewStage.PROJECT_DEEP_DIVE: {
        "display_name": "项目深挖",
        "description": "深入追问候选人核心项目经历：技术选型、难点攻克、个人贡献、量化成果",
    },
    InterviewStage.TECHNICAL_THEORY: {
        "display_name": "技术理论",
        "description": "考察岗位相关的技术基础、原理理解、最佳实践",
    },
    InterviewStage.CULTURE_FIT: {
        "display_name": "文化匹配",
        "description": "了解候选人的团队协作风格、抗压能力、职业规划与公司文化匹配度",
    },
    InterviewStage.CANDIDATE_QA: {
        "display_name": "候选人提问",
        "description": "给予候选人提问机会，回答关于岗位、团队、发展的问题",
    },
    InterviewStage.CLOSING: {
        "display_name": "结束总结",
        "description": "总结面试，告知后续流程，友好结束",
    },
}

# 阶段列表顺序（仅用于前端展示和方向导航）
STAGE_ORDER = list(STAGE_DEFINITIONS.keys())


class StageManager:
    """
    面试阶段管理器（动态分类模型）

    职责：
    1. 跟踪当前面试阶段（由 Flow Agent 动态分类或手动设置）
    2. 生成阶段上下文供 LLM Prompt 使用
    """

    def __init__(self):
        self.current_stage: InterviewStage = InterviewStage.WELCOME

    @property
    def config(self) -> Dict:
        return STAGE_DEFINITIONS[self.current_stage]

    def build_prompt_context(self) -> str:
        """构建阶段上下文，注入 LLM Prompt"""
        lines = []
        lines.append(f"当前阶段：{self.config['display_name']}")
        lines.append(f"阶段目标：{self.config['description']}")
        return "\n".join(lines)

    def set_stage(self, target_stage_key: str) -> Optional[Dict]:
        """
        设置当前阶段（不限制顺序，可任意跳转）

        Args:
            target_stage_key: 目标阶段key (如 "project", "theory", "closing")

        Returns:
            Optional[Dict]: 阶段切换信息，无效key或与当前相同返回 None
        """
        try:
            target = InterviewStage(target_stage_key)
        except ValueError:
            logger.error(f"[阶段管理] 无效的目标阶段: {target_stage_key}")
            return None

        if target == self.current_stage:
            # 同一阶段不重复通知
            return None

        old_stage = self.current_stage
        self.current_stage = target
        logger.info(f"[阶段管理] {STAGE_DEFINITIONS[old_stage]['display_name']} → {STAGE_DEFINITIONS[target]['display_name']}")

        try:
            stage_index = STAGE_ORDER.index(target)
        except ValueError:
            stage_index = 0

        return {
            "current_stage": self.current_stage.value,
            "display_name": self.config["display_name"],
            "stage_index": stage_index,
            "total_stages": len(STAGE_ORDER),
            "description": self.config["description"],
        }
