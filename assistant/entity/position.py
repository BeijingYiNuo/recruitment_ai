from sqlalchemy import Column, Integer, String, DateTime, Enum, Text, func
from assistant.config.database import Base
from assistant.enums.position_enum import PositionStatus, RoundType


class Position(Base):
    """岗位表"""
    __tablename__ = "position"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="岗位ID")
    name = Column(String(100), nullable=False, comment="岗位名称")
    department = Column(String(100), comment="所属部门")
    description = Column(Text, comment="岗位描述")
    requirements = Column(Text, comment="任职要求")
    salary_range = Column(String(100), comment="薪资范围")
    status = Column(Enum(PositionStatus), nullable=False, default=PositionStatus.ACTIVE, comment="状态")
    created_by = Column(Integer, nullable=False, comment="创建人ID")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")


class PositionRound(Base):
    """岗位面试轮次表"""
    __tablename__ = "position_round"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="轮次ID")
    position_id = Column(Integer, nullable=False, comment="关联岗位ID")
    round_number = Column(Integer, nullable=False, comment="轮次序号(从1开始)")
    round_name = Column(String(100), nullable=False, comment="轮次名称(如:技术一面、HR面)")
    round_type = Column(Enum(RoundType), nullable=False, default=RoundType.TECHNICAL, comment="轮次类型")
    duration_minutes = Column(Integer, nullable=False, default=30, comment="面试时长(分钟)")
    description = Column(Text, comment="面试内容描述")
    created_at = Column(DateTime, nullable=False, default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now(), comment="更新时间")
