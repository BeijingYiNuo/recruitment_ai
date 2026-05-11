from pydantic import BaseModel
from typing import Optional, List
from assistant.enums.position_enum import PositionStatus, RoundType


class PositionRoundCreate(BaseModel):
    """面试轮次创建模型"""
    round_name: str
    round_type: RoundType = RoundType.TECHNICAL
    duration_minutes: int = 30
    description: Optional[str] = None


class PositionRoundUpdate(BaseModel):
    """面试轮次更新模型"""
    round_name: Optional[str] = None
    round_type: Optional[RoundType] = None
    duration_minutes: Optional[int] = None
    description: Optional[str] = None


class PositionRoundReorder(BaseModel):
    """面试轮次重排序模型"""
    round_ids: List[int]


class PositionCreate(BaseModel):
    """岗位创建模型"""
    name: str
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    rounds: List[PositionRoundCreate] = []


class PositionUpdate(BaseModel):
    """岗位更新模型"""
    name: Optional[str] = None
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    status: Optional[PositionStatus] = None
