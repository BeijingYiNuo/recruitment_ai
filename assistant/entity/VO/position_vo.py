from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from assistant.enums.position_enum import PositionStatus, RoundType


class PositionRoundResponse(BaseModel):
    """面试轮次响应模型"""
    id: int
    position_id: int
    round_number: int
    round_name: str
    round_type: RoundType
    duration_minutes: int
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PositionResponse(BaseModel):
    """岗位响应模型"""
    id: int
    name: str
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    salary_range: Optional[str] = None
    status: PositionStatus
    created_by: int
    created_at: datetime
    updated_at: datetime
    rounds: List[PositionRoundResponse] = []

    class Config:
        from_attributes = True


class PositionListResponse(BaseModel):
    """岗位列表响应模型"""
    id: int
    name: str
    department: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    status: PositionStatus
    round_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True
