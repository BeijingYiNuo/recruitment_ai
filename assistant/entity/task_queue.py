from sqlalchemy import Column, Integer, String, DateTime, Text, JSON
from sqlalchemy import func
from assistant.config.database import Base


class TaskQueue(Base):
    """任务队列表：解耦 API 请求与长时间后台任务"""
    __tablename__ = "task_queue"

    id = Column(Integer, primary_key=True, autoincrement=True, comment="任务ID")
    task_type = Column(String(50), nullable=False, comment="任务类型")
    status = Column(String(20), nullable=False, default="PENDING",
                    comment="PENDING / PROCESSING / COMPLETED / FAILED")
    payload = Column(JSON, comment="任务参数（JSON）")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, nullable=False, server_default=func.now(),
                        onupdate=func.now(), comment="更新时间")
